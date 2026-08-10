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
    preset = script.get("style_preset", C.STYLE_PRESET)
    world = script.get("world", "")
    character = script["character"]
    cost = 0.0

    # 1. Референс персонажа
    ref_url, ref_path = visuals.character_ref(wd, character, world, preset)

    # 2. Кейфреймы (параллельно)
    keyframes: dict[int, tuple[str, str]] = {}
    workers = max(1, min(C.MAX_PARALLEL_JOBS, len(shots)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(visuals.keyframe, wd, i, s, character, ref_url, world, preset): i
            for i, s in enumerate(shots)
        }
        for fut in as_completed(futs):
            i = futs[fut]
            keyframes[i] = fut.result()
    log.info("Кейфреймы готовы: %d", len(keyframes))

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
        music_path=music_path or C.MUSIC_PATH,
        logo_path=logo_path or (C.LOGO_PATH if C.LOGO_ENABLED else ""),
    )

    result = {
        "path": final,
        "duration": media.probe_duration(final),
        "shots": len(shots),
        "video_cost": round(cost, 3),
        "animated_shots": len(animated),
        "workdir": wd,
        "character_ref": ref_path,
        "texts": texts,
    }
    log.info("ИТОГО: %.1fс, %d шотов, видео $%.2f", result["duration"],
             result["shots"], result["video_cost"])
    return result
