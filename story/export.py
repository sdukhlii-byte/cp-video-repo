"""
story/export.py — текстовые выгрузки рядом с роликом.

Нужны, когда озвучка делается не пайплайном: своим голосом, другим TTS,
диктором. Пишутся ВСЕГДА, независимо от VOICE_ENABLED, потому что стоят ноль
и избавляют от выковыривания текста из JSON-сценария руками.

  narration.txt   текст для чтения: по строке на шот + сколько секунд под неё
  narration.srt   те же строки, но с таймкодами шотов — можно бросить в любой
                  редактор и попадать в монтаж, не считая ничего вручную
  captions.srt    пословные субтитры (ровно то, что прожжено в ролик) — на
                  случай, если субтитры захочется переделать в CapCut
"""

from __future__ import annotations

import logging
import os

from story import captions as cap

log = logging.getLogger("export")


def _srt_ts(t: float) -> str:
    """Секунды → 00:00:00,000 (у SRT запятая, а не точка — иначе не парсится)."""
    t = max(t, 0.0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def narration_txt(script: dict, durations: list[float], path: str) -> str:
    """Текст для озвучки: строка на шот + бюджет времени под неё."""
    lines = [
        f"# {script.get('title', 'story')}",
        f"# язык: {script.get('language', '')}, шотов: {len(script['shots'])}, "
        f"всего: {sum(durations):.1f}с",
        "",
        "# Читать по строке на шот. В скобках — сколько секунд отведено под шот",
        "# в текущем монтаже: уложишься в это время — ничего пересобирать не надо.",
        "",
    ]
    if script.get("hook"):
        lines += [f"[хук на экране: {script['hook']}]", ""]

    cursor = 0.0
    for i, (shot, d) in enumerate(zip(script["shots"], durations)):
        lines.append(f"{i + 1}. ({cursor:5.1f}s → {cursor + d:5.1f}s, {d:.1f}s)  "
                     f"{shot['narration']}")
        cursor += d

    if script.get("cta"):
        lines += ["", f"[CTA: {script['cta']}]"]

    lines += ["", "", "# Сплошным текстом (для вставки в TTS одним куском):", ""]
    lines.append(" ".join(sh["narration"] for sh in script["shots"]))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def narration_srt(script: dict, durations: list[float], path: str) -> str:
    """Пошотовые реплики с таймкодами — чтобы попадать в готовый монтаж."""
    blocks, cursor = [], 0.0
    for i, (shot, d) in enumerate(zip(script["shots"], durations)):
        blocks.append(f"{i + 1}\n{_srt_ts(cursor)} --> {_srt_ts(cursor + d)}\n"
                      f"{shot['narration']}\n")
        cursor += d
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return path


def captions_srt(words: list[dict], path: str) -> str:
    """Пословные субтитры — те же группы слов, что прожжены в видео."""
    groups = cap.group_words(words)
    blocks = []
    for i, g in enumerate(groups):
        end = groups[i + 1]["start"] if i + 1 < len(groups) else g["end"] + 0.2
        if end <= g["start"]:
            end = g["start"] + 0.12
        blocks.append(f"{i + 1}\n{_srt_ts(g['start'])} --> {_srt_ts(end)}\n"
                      f"{g['text']}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return path


def write_all(workdir: str, script: dict, durations: list[float],
              words: list[dict]) -> dict[str, str]:
    out = {
        "narration_txt": narration_txt(script, durations,
                                       os.path.join(workdir, "narration.txt")),
        "narration_srt": narration_srt(script, durations,
                                       os.path.join(workdir, "narration.srt")),
        "captions_srt": captions_srt(words, os.path.join(workdir, "captions.srt")),
    }
    log.info("Текстовые выгрузки: %s", ", ".join(os.path.basename(p) for p in out.values()))
    return out
