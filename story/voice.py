"""
story/voice.py — закадровый голос через ElevenLabs с ПОСЛОВНЫМИ таймкодами.

Эндпоинт /with-timestamps отдаёт аудио + посимвольные тайминги; из них мы
собираем слова. Эти тайминги — единственный источник правды для караоке-субтитров,
поэтому их нельзя ломать: любое изменение темпа после синтеза их бы обесценило.

Длина озвучки шота d_i задаёт длину шота — это инвариант синхрона
голос ↔ видео ↔ субтитры во всём пайплайне.
"""

from __future__ import annotations

import base64
import logging
import os
import time

import requests

import config as C
from story import media

log = logging.getLogger("voice")


def _words_from_alignment(alignment: dict) -> list[dict]:
    """Посимвольные тайминги → пословные (границы по пробелам)."""
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    words: list[dict] = []
    cur, w_start, w_end = "", None, None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur and w_start is not None:
                words.append({"word": cur, "start": w_start, "end": w_end})
            cur, w_start, w_end = "", None, None
        else:
            if not cur:
                w_start = st
            cur += ch
            w_end = en
    if cur and w_start is not None:
        words.append({"word": cur, "start": w_start, "end": w_end})
    return words


def synthesize_line(workdir: str, idx: int, text: str,
                    retries: int = 3) -> tuple[str, float, list[dict]]:
    """
    Озвучивает одну реплику шота.
    Возвращает (wav_path, duration, words[]) — тайминги относительно НАЧАЛА шота.
    """
    voice_id = C.ELEVEN_VOICE_ID or C.require("ELEVEN_VOICE_ID")
    url = f"{C.ELEVEN_BASE}/text-to-speech/{voice_id}/with-timestamps"
    headers = {"xi-api-key": C.require("ELEVENLABS_API_KEY"), "Content-Type": "application/json"}
    settings = {
        "stability": C.ELEVEN_STABILITY,
        "similarity_boost": C.ELEVEN_SIMILARITY,
        "style": C.ELEVEN_STYLE,
    }
    if abs(C.ELEVEN_SPEED - 1.0) > 0.01:
        settings["speed"] = C.ELEVEN_SPEED
    payload = {"text": text, "model_id": C.ELEVEN_MODEL, "voice_settings": settings}

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=90)
            r.raise_for_status()
            data = r.json()
            audio_b64 = data.get("audio_base64") or data.get("audio")
            if not audio_b64:
                raise RuntimeError(f"Нет аудио в ответе ElevenLabs: {str(data)[:200]}")

            mp3 = os.path.join(workdir, f"voice_{idx:02d}.mp3")
            with open(mp3, "wb") as f:
                f.write(base64.b64decode(audio_b64))

            # alignment (не normalized) — чтобы слова субтитров совпадали с текстом
            # сценария: «1994» останется «1994», а не развернётся в пропись.
            alignment = data.get("alignment") or data.get("normalized_alignment") or {}
            words = _words_from_alignment(alignment)

            wav = os.path.join(workdir, f"voice_{idx:02d}.wav")
            media.run_ff(["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "2", wav],
                         label="voice_wav")
            duration = media.probe_duration(wav)
            if words and words[-1]["end"] > duration:
                duration = words[-1]["end"]
            log.info("Озвучка шота %d: %.2fс, %d слов", idx, duration, len(words))
            return wav, duration, words
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                wait = 2 ** attempt
                log.warning("TTS шот %d попытка %d/%d: %s — повтор через %dс",
                            idx, attempt, retries, str(e)[:140], wait)
                time.sleep(wait)
    raise RuntimeError(f"TTS шота {idx} не удался: {last}")


def synthesize_script(workdir: str, script: dict) -> tuple[list[str], list[float], list[dict]]:
    """
    Озвучивает все шоты подряд.

    Возвращает:
      wavs           — пошотовые wav
      shot_durations — d_i = длина озвучки + хвост (это и есть длина шота)
      words_global   — [{word,start,end,shot}] в ГЛОБАЛЬНОМ таймлайне ролика
    """
    wavs: list[str] = []
    durations: list[float] = []
    words_global: list[dict] = []
    cursor = 0.0

    for i, shot in enumerate(script["shots"]):
        text = shot["narration"].strip()
        if not text:
            wav = os.path.join(workdir, f"voice_{i:02d}.wav")
            media.make_silence(wav, C.MIN_SHOT_SEC)
            wavs.append(wav)
            durations.append(C.MIN_SHOT_SEC)
            cursor += C.MIN_SHOT_SEC
            continue

        wav, dur, words = synthesize_line(workdir, i, text)
        d_i = max(dur + C.VOICE_TAIL_SEC, C.MIN_SHOT_SEC)
        for w in words:
            if w.get("start") is None or w.get("end") is None:
                continue
            words_global.append({
                "word": w["word"],
                "start": cursor + float(w["start"]),
                "end": cursor + float(w["end"]),
                "shot": i,
            })
        wavs.append(wav)
        durations.append(d_i)
        cursor += d_i

    log.info("Озвучка целиком: %.2fс, %d слов", cursor, len(words_global))
    return wavs, durations, words_global
