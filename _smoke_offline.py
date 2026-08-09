#!/usr/bin/env python3
"""
_smoke_offline.py — прогон ВСЕГО конвейера без единого вызова API и без денег.

Подменяет три внешние зависимости заглушками:
  • картинки  → цветные PNG с номером шота (PIL)
  • видео     → Ken Burns из этой картинки (ffmpeg)
  • ElevenLabs→ тишина нужной длины + равномерные пословные тайминги

Проверяет то, что чаще всего и ломается: порядок шагов, инвариант длины шота,
склейку, прожиг субтитров, финальный хронометраж.

    python3 _smoke_offline.py [-o smoke.mp4]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level="INFO", format="%(levelname)s [%(name)s] %(message)s")

import config as C  # noqa: E402
from story import media, orclient, visuals, voice  # noqa: E402

PALETTE = ["#1b2430", "#2d1b3d", "#123328", "#3d2415", "#16324a",
           "#3a1626", "#1f3a1f", "#2a2a3d"]


def _stub_image(prompt: str, ref_urls=None, aspect_ratio="", label="", **kw) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw
    idx = "".join(ch for ch in label if ch.isdigit()) or "0"
    color = PALETTE[int(idx) % len(PALETTE)]
    im = Image.new("RGB", (C.VIDEO_W // 2, C.VIDEO_H // 2), color)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, im.width - 40, im.height - 40], outline="#ffffff", width=6)
    d.text((60, 60), f"STUB {label}\n{prompt[:180]}", fill="#ffffff")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _stub_video(model, prompt, frame_image_url, duration_sec, label="", **kw):
    """Возвращать байты не будем — вместо этого animate() подменён целиком."""
    raise RuntimeError("stub: видеомодель недоступна (это ожидаемо в офлайн-прогоне)")


def _stub_tts(workdir, idx, text, retries=3):
    """Тишина длиной по количеству слов + равномерные тайминги."""
    words = text.split()
    per = 1.0 / C.WORDS_PER_SEC
    dur = len(words) * per + 0.25
    wav = os.path.join(workdir, f"voice_{idx:02d}.wav")
    media.make_silence(wav, dur)
    out, t = [], 0.15
    for w in words:
        out.append({"word": w, "start": t, "end": t + per * 0.92})
        t += per
    return wav, dur, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="smoke.mp4")
    ap.add_argument("--script", default="examples/first_jackpot_ru.json")
    args = ap.parse_args()

    orclient.generate_image_bytes = _stub_image
    orclient.generate_video_bytes = _stub_video
    if os.environ.get("VOICE_ENABLED", "true").lower() not in ("0", "false", "no"):
        # голос включён → подменяем TTS заглушкой; при VOICE_ENABLED=false
        # работает штатный беззвучный режим, и подменять нечего
        voice.synthesize_line = _stub_tts
    # видеомодель недоступна → пусть отработает штатная цепочка фолбэка (Ken Burns)

    with open(args.script, encoding="utf-8") as f:
        script = json.load(f)
    from story.script_writer import coerce
    script = coerce(script)

    from story.render import render
    res = render(script, args.out, workdir_base="work_smoke")
    print(json.dumps(res, ensure_ascii=False, indent=2))

    expect = sum(1 for _ in script["shots"])
    assert res["shots"] == expect, "потерялись шоты"
    assert res["duration"] > 5, "подозрительно короткий ролик"
    print("\nOK: конвейер собрал ролик целиком (картинки/видео/голос — заглушки).")


if __name__ == "__main__":
    main()
