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
from story.prompts import build_script_user_prompt, fill_script_system

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

_STRIP_CHARS = dict.fromkeys(map(ord, '«»""„”\'`*_#'), None)


def clean_narration(text: str) -> str:
    """
    Чистит реплику под TTS и под субтитры одновременно:
    убирает эмодзи/кавычки/скобки, схлопывает пробелы, снимает финальную точку
    (она визуально мусорит в караоке-плашке).
    """
    t = str(text or "").strip()
    t = t.translate(_STRIP_CHARS)
    t = re.sub(r"[\(\)\[\]\{\}]", "", t)
    t = re.sub(r"#\S+", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", t)   # эмодзи
    t = re.sub(r"\s+", " ", t).strip()
    t = t.rstrip(".")
    return t


def _trim_words(text: str, max_words: int) -> str:
    """Режет реплику по границе слов, если модель написала длиннее бюджета."""
    words = text.split()
    if len(words) <= max_words:
        return text
    log.warning("Реплика длиннее бюджета (%d>%d) — обрезаю", len(words), max_words)
    return " ".join(words[:max_words])


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
            "narration": _trim_words(narration, hard_max),
            "visual": visual,
            "motion": str(s.get("motion") or "").strip(),
            "beat": str(s.get("beat") or "").strip(),
            "brand_surface": str(s.get("brand_surface") or "").strip(),
        })

    if len(out_shots) > shots:
        log.warning("Шотов %d > плана %d — отрезаю хвост", len(out_shots), shots)
        out_shots = out_shots[:shots]
    if len(out_shots) < 3:
        raise ValueError(f"Слишком мало валидных шотов: {len(out_shots)}")

    _assign_brand(out_shots)

    return {
        "title": str(data.get("title") or "story").strip(),
        "language": str(data.get("language") or C.LANG).strip(),
        "hook": clean_narration(data.get("hook") or ""),
        "character": character,
        "world": str(data.get("world") or "").strip(),
        "shots": out_shots,
        "cta": clean_narration(data.get("cta") or ""),
        "style_preset": str(data.get("style_preset") or C.STYLE_PRESET),
    }


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

    system = fill_script_system(shots, words)
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
