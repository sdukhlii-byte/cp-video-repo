"""
story/render.py — оркестратор: сценарий → готовый mp4.

Порядок шагов не случаен:
  1. Референс персонажа        — одна картинка, от неё зависит вся консистентность
  2. Кейфреймы шотов           — параллельно, каждый с этим референсом
  3. ОЗВУЧКА                   — до анимации! длина озвучки d_i задаёт длину шота,
                                 а значит и длину клипа, который надо заказать
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
from story import captions, compose, export, visuals, voice

log = logging.getLogger("render")


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
    voice_wavs, durations, words = voice.synthesize_script(wd, script)

    # 4. Анимация (параллельно)
    clips: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(visuals.animate, wd, i, keyframes[i][1], shots[i],
                      durations[i], preset): i
            for i in range(len(shots))
        }
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
        voice_wavs,
        ass_path,
        out_path,
        music_path=music_path or C.MUSIC_PATH,
        logo_path=logo_path or (C.LOGO_PATH if C.LOGO_ENABLED else ""),
    )

    from story.media import probe_duration
    result = {
        "path": final,
        "duration": probe_duration(final),
        "shots": len(shots),
        "video_cost": round(cost, 3),
        "workdir": wd,
        "character_ref": ref_path,
        "texts": texts,
    }
    log.info("ИТОГО: %.1fс, %d шотов, видео $%.2f", result["duration"],
             result["shots"], result["video_cost"])
    return result
