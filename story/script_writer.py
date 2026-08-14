"""
story/script_writer.py — сценарий ролика через LLM + ЖЁСТКАЯ нормализация ответа.

Нормализация важнее самого запроса: LLM регулярно отдаёт лишний шот, реплику
вдвое длиннее нужной или markdown-обёртку. Всё это чинится здесь, чтобы дальше
по конвейеру пришла заведомо валидная структура.
"""

from __future__ import annotations

import json
import logging
import re

import config as C
from story import orclient
from story.prompts import (build_script_user_prompt, fill_script_system,
                           is_direct_address)

log = logging.getLogger("script")


# ── ПАРСИНГ ────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Достаёт JSON даже если модель обернула его в ```json или добавила текст."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, depth = None, 0
    for i, ch in enumerate(t):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}" and start is not None:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError:
                    start, depth = None, 0
    raise ValueError(f"Не удалось распарсить JSON сценария: {t[:300]}")


# ── ЧИСТКА ТЕКСТА ОЗВУЧКИ ──────────────────────────────────────────────────────

# Типографские кавычки перечисляем кодами: в исходнике они визуально
# неотличимы от прямых, и набранный «на глаз» список их пропускает — именно
# так открывающая « в начале текста доезжала до субтитра как часть слова.
# Апостроф U+2019 НЕ трогаем: он внутри слов (Babbage's) и нужен для речи.
_STRIP_CHARS = dict.fromkeys(
    [ord(c) for c in '«»"`*_#']
    + [0x201C, 0x201D, 0x201E, 0x201F, 0x2039, 0x203A],
    None,
)

# Апостроф внутри слова обязателен для английского: убрав его, получаем
# «Theres» и «Blancs» — и в субтитрах, и в тексте на озвучку. Поэтому кавычки
# вида ' и ’ снимаем только на границах слова, а внутри оставляем.
_EDGE_QUOTES = re.compile(r"(?<!\w)['\u2018\u201A\u2019]|['\u2018\u201A\u2019](?!\w)")


def clean_narration(text: str) -> str:
    """
    Чистит реплику под TTS и под субтитры одновременно:
    убирает эмодзи/кавычки/скобки, схлопывает пробелы, снимает финальную точку
    (она визуально мусорит в караоке-плашке).
    """
    t = str(text or "").strip()
    t = t.translate(_STRIP_CHARS)
    t = _EDGE_QUOTES.sub("", t)
    t = re.sub(r"[\(\)\[\]\{\}]", "", t)
    t = re.sub(r"#\S+", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", t)   # эмодзи
    t = re.sub(r"\s+", " ", t).strip()
    t = t.rstrip(".")
    return t


def _check_length(text: str, max_words: int, idx: int) -> str:
    """
    Раньше здесь реплика резалась по границе слов — и это было хуже болезни:
    фраза обрывалась на середине, диктор произносил огрызок, а зритель читал
    бессмыслицу. Лишняя секунда шота — меньшее зло, чем сломанное предложение.

    Поэтому теперь только предупреждаем. Если шот перерастёт потолок клипа
    видеомодели, об этом отдельно скажет visuals._quantize().
    """
    n = len(text.split())
    if n > max_words:
        log.warning("Шот %d: реплика %d слов при бюджете %d — шот станет длиннее "
                    "плана. Если так во всех шотах, проверь WORDS_PER_SEC.",
                    idx, n, max_words)
    return text


# ── НОРМАЛИЗАЦИЯ ───────────────────────────────────────────────────────────────

def coerce(data: dict, shots: int = 0, words: int = 0) -> dict:
    shots = shots or C.planned_shot_count()
    words = words or C.words_per_shot()
    hard_max = int(words * 1.6)

    character = data.get("character") or {}
    if not isinstance(character, dict) or not str(character.get("design", "")).strip():
        raise ValueError("В сценарии нет character.design — без него персонаж не будет консистентным")
    character = {
        "name": str(character.get("name") or "Hero").strip(),
        "design": str(character["design"]).strip(),
    }

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("В сценарии нет shots")

    out_shots: list[dict] = []
    for i, s in enumerate(raw_shots):
        if not isinstance(s, dict):
            continue
        narration = clean_narration(s.get("narration") or s.get("line") or "")
        visual = str(s.get("visual") or "").strip()
        if not visual:
            log.warning("Шот %d без visual — подставляю нейтральный", i)
            visual = f"the character in a new location relevant to: {narration}"
        out_shots.append({
            "narration": _check_length(narration, hard_max, i),
            "visual": visual,
            "motion": str(s.get("motion") or "").strip(),
            "beat": str(s.get("beat") or "").strip(),
            "action": str(s.get("action") or "").strip(),
            "key_word": str(s.get("key_word") or "").strip(),
            "framing": str(s.get("framing") or "").strip(),
            "brand_surface": str(s.get("brand_surface") or "").strip(),
            "brand_surface_upper": str(s.get("brand_surface_upper") or "").strip(),
        })

    if len(out_shots) > shots:
        log.warning("Шотов %d > плана %d — отрезаю хвост", len(out_shots), shots)
        out_shots = out_shots[:shots]
    if len(out_shots) < 3:
        raise ValueError(f"Слишком мало валидных шотов: {len(out_shots)}")

    _ensure_framing(out_shots)
    _assign_brand(out_shots)
    _assign_tagline(out_shots)

    result = {
        "title": str(data.get("title") or "story").strip(),
        "language": str(data.get("language") or C.LANG).strip(),
        "hook": clean_narration(data.get("hook") or ""),
        "character": character,
        "world": str(data.get("world") or "").strip(),
        "shots": out_shots,
        "cta": clean_narration(data.get("cta") or ""),
        "style_preset": str(data.get("style_preset") or C.STYLE_PRESET),
    }
    # Уже синтезированная дорожка должна пережить нормализацию: потеряв её,
    # рендер молча озвучит тот же текст второй раз и спишет деньги повторно.
    if data.get("_pre_synth"):
        result["_pre_synth"] = data["_pre_synth"]
    return result


# Ракурсы для подстраховки: если модель не заполнила framing или повторила
# один и тот же, раскладываем по кругу. Однообразная средняя фронталка —
# самый быстрый способ сделать ролик похожим на генерацию.
_FRAMINGS = [
    "medium shot, subject from the waist up with room around them",
    "close-up on the face, shoulders visible at the bottom",
    "low angle looking up at the subject",
    "close-up on the hands at work",
    "over-the-shoulder from behind, subject in the foreground",
    "full-body shot, subject standing with the environment visible around them",
    "three-quarter view from the side",
    "chest-up portrait with the background readable behind",
]


# Ракурсы для стиля «ведущая за столом»: меняется камера, а не место.
_FRAMINGS_SEATED = [
    "medium shot from across the table",
    "close-up on her face",
    "slight low angle from table level",
    "close-up on her hands on the felt",
    "three-quarter side view",
    "over-the-shoulder from behind her",
]


def _ensure_framing(shots: list[dict]) -> None:
    """
    Нормализует ракурсы: убирает пустые, повторы подряд и мелкие планы.

    Мелкий план — главная причина «бледного» кадра на вертикальном экране:
    фигура тонет в общем виде, и ролик проигрывает референсам, где герой
    занимает всю высоту. Инструкции в промпте недостаточно — модель всё равно
    иногда пишет «wide establishing shot», поэтому такие варианты
    перехватываем здесь и заменяем на крупные.
    """
    small = ("wide shot", "wide establishing", "establishing shot", "long shot",
             "aerial", "bird's eye", "birds eye", "from a distance", "far away",
             "small in the frame", "tiny", "extreme wide")

    # В разговорном стиле героиня сидит за столом: планы в полный рост и «с
    # окружением вокруг» ей не подходят, поэтому запасной список свой.
    pool = _FRAMINGS_SEATED if is_direct_address() else _FRAMINGS

    used: list[str] = []
    replaced = 0
    for i, sh in enumerate(shots):
        f = sh.get("framing", "").strip()
        low = f.lower()
        is_small = any(marker in low for marker in small)
        if not f or is_small or (used and low == used[-1].lower()):
            if is_small:
                replaced += 1
            f = pool[i % len(pool)]
            sh["framing"] = f
        used.append(f)

    if replaced:
        log.info("Заменено мелких планов на крупные: %d", replaced)
    if not any(sh.get("action") for sh in shots):
        log.warning("Сценарий без действий персонажа — герой будет статичен в кадре")


def _assign_brand(shots: list[dict]) -> None:
    """
    Помечает часть шотов флагом brand=True — в них картиночная модель нарисует
    название бренда на предмете из brand_surface.

    Почему не во всех: сплошной плейсмент читается как реклама и убивает эффект
    «истории», ради которого формат и работает. Поэтому берём долю шотов и
    распределяем их РАВНОМЕРНО по таймлайну, а не подряд — бренд должен
    периодически напоминать о себе, а не мелькнуть один раз в начале.
    Первый шот пропускаем: он ловит внимание, ему нельзя выглядеть рекламой.
    """
    if C.BRAND_PLACEMENT == "off" or not C.BRAND_NAME:
        for sh in shots:
            sh["brand"] = False
        return

    eligible = [i for i, sh in enumerate(shots) if sh.get("brand_surface")]
    if not eligible:
        log.warning("Сценарий не дал ни одной поверхности под бренд — плейсмента не будет")
        for sh in shots:
            sh["brand"] = False
        return

    # первый шот — только если больше вариантов нет
    pool = [i for i in eligible if i != 0] or eligible
    want = max(1, round(len(shots) * C.BRAND_SHOT_RATIO))
    want = min(want, len(pool))
    step = len(pool) / want
    chosen = {pool[min(int(k * step), len(pool) - 1)] for k in range(want)}

    for i, sh in enumerate(shots):
        sh["brand"] = i in chosen
    log.info("Плейсмент %r в шотах: %s", C.BRAND_NAME, sorted(chosen))


def _assign_tagline(shots: list[dict]) -> None:
    """
    Помечает шоты, где на верхней вывеске будет слоган бренда.

    Слоган ставим РЕЖЕ, чем само имя: вывеска с сообщением — это уже почти
    реклама, и в каждом втором кадре она сжигает доверие к истории. Плюс
    длинная строка чаще выходит с опечаткой, поэтому меньше попыток — меньше
    брака на отбраковку. Первый шот не трогаем: он ловит внимание.
    """
    if not C.BRAND_TAGLINE or C.BRAND_PLACEMENT == "off":
        for sh in shots:
            sh["tagline"] = False
        return

    # Считаем символы, а не слова: «MIN DEP 1 USDT» — четыре «слова», но всего
    # 14 знаков, и рисуется нормально. Ошибки растут именно с длиной строки.
    n_chars = len(C.BRAND_TAGLINE)
    if n_chars > 18:
        log.warning("Слоган %d знаков (%r) — чем длиннее строка, тем выше шанс "
                    "опечатки. До 18 знаков рисуется заметно надёжнее, "
                    "остальное лучше в PROMO_TEXT.", n_chars, C.BRAND_TAGLINE)
    if any("\u0400" <= ch <= "\u04FF" for ch in C.BRAND_TAGLINE):
        log.warning("Слоган кириллицей — рисуется заметно хуже латиницы. "
                    "Латинский вариант даст меньше брака.")

    eligible = [i for i, sh in enumerate(shots)
                if sh.get("brand_surface_upper") and i != 0]
    if not eligible:
        eligible = [i for i in range(1, len(shots))] or [0]

    want = max(1, round(len(shots) * C.BRAND_TAGLINE_RATIO))
    want = min(want, len(eligible))
    step = len(eligible) / want
    chosen = {eligible[min(int(k * step), len(eligible) - 1)] for k in range(want)}

    for i, sh in enumerate(shots):
        sh["tagline"] = i in chosen
    log.info("Слоган %r на вывеске в шотах: %s", C.BRAND_TAGLINE, sorted(chosen))


def estimate_duration(script: dict) -> float:
    """Оценка длины ролика по количеству слов (до реального TTS)."""
    total_words = sum(len(s["narration"].split()) for s in script["shots"])
    per_shot_overhead = len(script["shots"]) * C.VOICE_TAIL_SEC
    return total_words / max(C.WORDS_PER_SEC, 1.0) + per_shot_overhead


# ── ГЕНЕРАЦИЯ ──────────────────────────────────────────────────────────────────

def write_script(topic: str, language: str = "", shots: int = 0, words: int = 0,
                 extra: str = "", vertical: str = "", model: str = "",
                 retries: int = 2) -> dict:
    language = language or C.LANG
    shots = shots or C.planned_shot_count()
    words = words or C.words_per_shot()

    system = fill_script_system(shots, words, is_direct_address())
    user = build_script_user_prompt(topic, language, shots, words, extra, vertical)

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = orclient.chat(system, user, model=model, temperature=0.85)
            script = coerce(_extract_json(raw), shots, words)
            log.info("Сценарий готов: %r, %d шотов, ~%.1fс",
                     script["title"], len(script["shots"]), estimate_duration(script))
            return script
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("Сценарист попытка %d/%d: %s", attempt, retries, str(e)[:200])
    raise RuntimeError(f"Не удалось получить валидный сценарий: {last}")
