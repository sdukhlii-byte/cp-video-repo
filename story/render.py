"""
story/render.py — оркестратор: сценарий → готовый mp4.

Порядок шагов не случаен:
  1. Референс персонажа        — одна картинка, от неё зависит вся консистентность
  2. Кейфреймы шотов           — параллельно, каждый с этим референсом
  3. ОЗВУЧКА                   — до анимации! длина озвучки d_i задаёт длину шота,
                                 а значит и длину клипа, который надо заказать.
                                 Весь текст синтезируется ОДНИМ запросом, иначе
                                 каждая реплика получает финальную интонацию и
                                 речь звучит как набор оборванных фраз.
  4. Анимация шотов            — параллельно, длина квантуется под d_i
  5. Субтитры + сборка
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config as C
from story import captions, compose, export, media, visuals, voice

log = logging.getLogger("render")


def pick_animated(shots: list[dict], ratio: float) -> set[int]:
    """
    Какие шоты идут через видеомодель, а какие — зумом из кейфрейма.

    Живое движение отдаём туда, где оно реально работает: первый шот (он решает,
    досмотрят ли ролик), последний (концовка) и смысловые повороты. Ровные
    «проходные» шоты держат зум — на 4 секундах с крупным словом поверх разницу
    почти не видно, а платить за них незачем.
    """
    n = len(shots)
    if ratio >= 1.0:
        return set(range(n))
    if ratio <= 0.0:
        return set()          # 0 = вообще без видеомодели, весь ролик зумом
    want = max(1, round(n * ratio))
    if want >= n:
        return set(range(n))

    priority = [0, n - 1]                                   # хук и концовка
    priority += [i for i, sh in enumerate(shots) if sh.get("beat") == "turn"]
    priority += [i for i, sh in enumerate(shots) if sh.get("beat") == "payoff"]
    priority += list(range(n))                              # добор по порядку

    chosen: set[int] = set()
    for i in priority:
        if len(chosen) >= want:
            break
        chosen.add(i)
    return chosen


def _resolve(path: str) -> str:
    """
    Относительный путь считаем от корня проекта, а не от текущей директории.

    Рабочую директорию задаёт та среда, что запускает контейнер, и полагаться
    на неё нельзя: стоит ей отличаться от /app — и assets/music перестаёт
    находиться, причём молча.
    """
    if not path or os.path.isabs(path):
        return path
    if os.path.exists(path):
        return path
    return os.path.join(C.ROOT, path)


def pick_music() -> str:
    """
    Трек подложки: явный MUSIC_PATH либо случайный из папки MUSIC_DIR.

    Каждый вариант отказа логируется громко. Раньше несуществующий путь молча
    возвращал пустоту, ролик собирался без музыки, и в логе не было ни слова —
    выглядело так, будто музыка есть, но не слышна.
    """
    if C.MUSIC_PATH:
        path = _resolve(C.MUSIC_PATH)
        if os.path.exists(path):
            log.info("Подложка: %s", path)
            return path
        log.warning("MUSIC_PATH=%r НЕ НАЙДЕН (искал %s, рабочая папка %s) — "
                    "смотрю MUSIC_DIR", C.MUSIC_PATH, path, os.getcwd())

    if C.MUSIC_DIR:
        mdir = _resolve(C.MUSIC_DIR)
        if not os.path.isdir(mdir):
            log.warning("MUSIC_DIR=%r не существует (искал %s) — БЕЗ МУЗЫКИ",
                        C.MUSIC_DIR, mdir)
            return ""
        tracks = [os.path.join(mdir, f) for f in sorted(os.listdir(mdir))
                  if f.lower().endswith((".mp3", ".m4a", ".wav", ".ogg", ".aac"))]
        if tracks:
            choice = random.choice(tracks)
            log.info("Подложка: %s (из %d треков)", os.path.basename(choice), len(tracks))
            return choice
        log.warning("В MUSIC_DIR=%r нет аудиофайлов — ролик будет БЕЗ МУЗЫКИ. "
                    "Положи туда mp3 и закоммить: файлы должны попасть в образ.",
                    C.MUSIC_DIR)
        return ""

    log.info("MUSIC_PATH и MUSIC_DIR не заданы — ролик без музыки")
    return ""


def _workdir(base: str, title: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in title.lower())[:40].strip("_") or "story"
    path = os.path.join(base, f"{slug}_{int(time.time())}")
    os.makedirs(path, exist_ok=True)
    return path


def render(script: dict, out_path: str, workdir_base: str = "work",
           music_path: str = "", logo_path: str = "") -> dict:
    os.makedirs(workdir_base, exist_ok=True)
    wd = _workdir(workdir_base, script.get("title", "story"))
    log.info("Рабочая папка: %s", wd)

    with open(os.path.join(wd, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    shots = script["shots"]

    # Пресет живёт в двух местах: в переменной окружения и запечённым в сценарии
    # (туда он попадает в момент генерации). Раньше сценарий побеждал молча —
    # поменяв STYLE_PRESET, можно было отрендерить старый стиль и не понять,
    # почему два ролика выглядят по-разному. Теперь явно заданная переменная
    # побеждает, а расхождение попадает в лог.
    baked = str(script.get("style_preset") or "").strip()
    if C.STYLE_PRESET_EXPLICIT and baked and baked != C.STYLE_PRESET:
        log.warning("В сценарии записан стиль %r, но STYLE_PRESET=%r — "
                    "беру переменную окружения", baked, C.STYLE_PRESET)
        preset = C.STYLE_PRESET
    else:
        preset = baked or C.STYLE_PRESET

    # Пишем активный стиль в лог. Без этого сравнить два прогона задним числом
    # невозможно: ролики выходят разными, а чем именно отличались настройки —
    # уже не восстановить.
    from story.prompts import style as _style
    st = _style(preset)
    log.info("Стиль: %s%s%s", preset,
             " + STYLE_EXTRA" if C.STYLE_EXTRA else "",
             " (STYLE_IMAGE переопределён)" if C.STYLE_IMAGE else "")
    log.info("  картинка: %s", st["image"][:160])
    if C.STYLE_EXTRA:
        log.info("  STYLE_EXTRA: %s", C.STYLE_EXTRA)
    world = script.get("world", "")
    character = script["character"]
    cost = 0.0

    # 1. Референс персонажа
    ref_url, ref_path = visuals.character_ref(wd, character, world, preset)

    # 2. Кейфреймы
    keyframes: dict[int, tuple[str, str]] = {}
    workers = max(1, min(C.MAX_PARALLEL_JOBS, len(shots)))
    if C.FRAME_CHAIN:
        # Последовательно: каждый кадр получает предыдущий вторым референсом.
        # Медленнее, но герой и палитра не уплывают к концу ролика.
        prev_url = ""
        for i, sh in enumerate(shots):
            keyframes[i] = visuals.keyframe(wd, i, sh, character, ref_url,
                                            world, preset, prev_url=prev_url)
            prev_url = keyframes[i][0]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(visuals.keyframe, wd, i, s, character, ref_url,
                          world, preset): i
                for i, s in enumerate(shots)
            }
            for fut in as_completed(futs):
                i = futs[fut]
                keyframes[i] = fut.result()
    log.info("Кейфреймы готовы: %d%s", len(keyframes),
             " (цепочкой)" if C.FRAME_CHAIN else "")

    # 3. Озвучка — ДО анимации, чтобы знать точную длину каждого шота
    voice_track, durations, words = voice.build_track(wd, script)

    # 4. Анимация. Часть шотов может идти зумом из кейфрейма — см. ANIMATE_RATIO.
    animated = pick_animated(shots, C.ANIMATE_RATIO)
    if len(animated) < len(shots):
        log.info("Гибрид: через видеомодель %d из %d шотов (%s), остальные — зум",
                 len(animated), len(shots), sorted(animated))

    def _kenburns(i: int) -> tuple[str, float]:
        path = os.path.join(wd, f"shot_{i:02d}_raw.mp4")
        media.ken_burns_clip(keyframes[i][1], path, durations[i],
                             C.VIDEO_W, C.VIDEO_H, C.FPS)
        return path, 0.0

    # Оба типа шотов кидаем в один пул: джобы видеомодели — это долгий поллинг,
    # и гнать ffmpeg последовательно ДО их отправки значит просто так тянуть
    # время на каждом прогоне.
    clips: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for i in range(len(shots)):
            if i in animated:
                futs[ex.submit(visuals.animate, wd, i, keyframes[i][1],
                               shots[i], durations[i], preset)] = i
            else:
                futs[ex.submit(_kenburns, i)] = i
        for fut in as_completed(futs):
            i = futs[fut]
            path, c = fut.result()
            clips[i] = path
            cost += c

    # 5. Субтитры и сборка
    # words.json нужен, чтобы потом бесплатно пережигать субтитры (`cli.py captions`)
    with open(os.path.join(wd, "words.json"), "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    ass_path = os.path.join(wd, "captions.ass")
    captions.build_ass(words, ass_path, hook=script.get("hook", ""))

    # Текстовые выгрузки — до сборки, чтобы они были на диске даже если
    # ffmpeg упадёт на последнем шаге.
    texts = export.write_all(wd, script, durations, words)

    final = compose.compose(
        wd,
        [clips[i] for i in range(len(shots))],
        durations,
        voice_track,
        ass_path,
        out_path,
        music_path=music_path or pick_music(),
        logo_path=logo_path or (C.LOGO_PATH if C.LOGO_ENABLED else ""),
    )

    result = {
        "path": final,
        "duration": media.probe_duration(final),
        "shots": len(shots),
        "video_cost": round(cost, 3),
        "animated_shots": len(animated),
        "style_preset": preset,
        "style_extra": C.STYLE_EXTRA,
        "workdir": wd,
        "character_ref": ref_path,
        "texts": texts,
    }
    log.info("ИТОГО: %.1fс, %d шотов, видео $%.2f", result["duration"],
             result["shots"], result["video_cost"])
    return result
