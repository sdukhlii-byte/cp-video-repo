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


class TTSPaymentRequired(RuntimeError):
    """Кончился баланс/ключ не оплачен. Ретраить бессмысленно."""


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
            # 401/402/403 — терминальные: ключ, баланс или права. Ретрай их только
            # растягивает падение на минуту и прячет настоящую причину.
            if r.status_code in (401, 402, 403):
                raise TTSPaymentRequired(
                    f"ElevenLabs HTTP {r.status_code} — ключ/баланс/права. "
                    f"Если баланса нет, поставь VOICE_ENABLED=false: "
                    f"ролик соберётся с субтитрами и музыкой, без голоса."
                )
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
        except TTSPaymentRequired:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                wait = 2 ** attempt
                log.warning("TTS шот %d попытка %d/%d: %s — повтор через %dс",
                            idx, attempt, retries, str(e)[:140], wait)
                time.sleep(wait)
    raise RuntimeError(f"TTS шота {idx} не удался: {last}")


# ── РЕЖИМ БЕЗ ГОЛОСА ───────────────────────────────────────────────────────────

def mock_line(workdir: str, idx: int, text: str) -> tuple[str, float, list[dict]]:
    """
    Дорожка шота без TTS: тишина нужной длины + расчётные пословные тайминги.

    Длительность слова пропорциональна его длине (длинное слово читается дольше),
    после запятой добавляется микропауза. Это не имитация живой речи — это ровный
    читаемый ритм, которого достаточно, чтобы оценить монтаж, кадры и субтитры
    до того, как платить за озвучку.
    """
    raw_words = text.split()
    if not raw_words:
        wav = media.make_silence(os.path.join(workdir, f"voice_{idx:02d}.wav"),
                                 C.MIN_SHOT_SEC)
        return wav, C.MIN_SHOT_SEC, []

    weights = [len(w.strip(",.!?;:")) + 2 for w in raw_words]
    pauses = [0.14 if w.endswith(",") else 0.0 for w in raw_words]
    speech = len(raw_words) / max(C.WORDS_PER_SEC, 0.5)
    scale = speech / sum(weights)

    words, t = [], 0.10
    for w, weight, pause in zip(raw_words, weights, pauses):
        d = max(weight * scale, 0.20)
        words.append({"word": w.strip(",.!?;:"), "start": t, "end": t + d * 0.94})
        t += d + pause

    duration = t + 0.10
    wav = media.make_silence(os.path.join(workdir, f"voice_{idx:02d}.wav"), duration)
    log.info("Шот %d без голоса: %.2fс, %d слов (расчётный ритм)",
             idx, duration, len(words))
    return wav, duration, words


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

        if C.VOICE_ENABLED:
            wav, dur, words = synthesize_line(workdir, i, text)
        else:
            wav, dur, words = mock_line(workdir, i, text)
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

    # Держим финальный кадр, чтобы последнее слово успело прочитаться.
    if durations and C.OUTRO_HOLD_SEC > 0:
        durations[-1] += C.OUTRO_HOLD_SEC
        cursor += C.OUTRO_HOLD_SEC
        log.info("Хвост в конце: +%.1fс", C.OUTRO_HOLD_SEC)

    log.info("%s целиком: %.2fс, %d слов",
             "Озвучка" if C.VOICE_ENABLED else "Дорожка без голоса",
             cursor, len(words_global))
    return wavs, durations, words_global

# ── ЕДИНАЯ ДОРОЖКА: ВЕСЬ ТЕКСТ ОДНИМ ЗАПРОСОМ ─────────────────────────────────

def join_narration(script: dict) -> tuple[str, list[int]]:
    """
    Склеивает реплики шотов в ОДИН текст для синтеза.

    Возвращает (текст, [сколько слов в каждом шоте]). Счётчик слов нужен, чтобы
    потом разложить пословные таймкоды обратно по шотам.

    Точки в конце реплик расставляем осмысленно: реплика — это точка монтажа,
    а не конец мысли. Точку ставим только там, где она была в тексте; иначе
    склеиваем запятой, чтобы диктор не «дописывал» интонацию конца предложения
    там, где мысль продолжается.
    """
    parts, counts = [], []
    lines = [sh["narration"].strip() for sh in script["shots"]]
    for i, line in enumerate(lines):
        counts.append(len(line.split()))
        if not line:
            continue
        last = i == len(lines) - 1
        if line[-1] in ".!?…":
            parts.append(line)
        elif last:
            parts.append(line + ".")
        else:
            # следующая реплика начинается с заглавной → это новое предложение
            nxt = lines[i + 1]
            parts.append(line + ("." if nxt[:1].isupper() else ","))
    return " ".join(parts), counts


def _split_by_counts(words: list[dict], counts: list[int]) -> list[list[dict]]:
    """Раскладывает сплошной список слов обратно по шотам."""
    out, pos = [], 0
    for n in counts:
        out.append(words[pos:pos + n])
        pos += n
    if pos < len(words) and out:
        out[-1].extend(words[pos:])          # хвост от расхождения токенизации
    return out


def _durations_from_words(per_shot: list[list[dict]], total: float) -> list[float]:
    """
    Длина шота = до середины паузы перед следующей репликой.

    Резать ровно по последнему слову нельзя: склейка попадёт на выдох, и монтаж
    зазвучит рвано. Середина паузы — естественная точка реза.
    """
    bounds, prev_end = [], 0.0
    for i, words in enumerate(per_shot):
        if not words:
            bounds.append(prev_end + C.MIN_SHOT_SEC)
            prev_end = bounds[-1]
            continue
        end = float(words[-1]["end"])
        nxt = None
        for later in per_shot[i + 1:]:
            if later:
                nxt = float(later[0]["start"])
                break
        cut = (end + nxt) / 2 if nxt is not None else total
        bounds.append(cut)
        prev_end = cut

    durations, prev = [], 0.0
    for b in bounds:
        durations.append(max(b - prev, C.MIN_SHOT_SEC))
        prev = b
    return durations


def synthesize_whole(workdir: str, script: dict) -> tuple[str, list[float], list[dict]]:
    """Один запрос на весь текст → непрерывная интонация."""
    text, counts = join_narration(script)
    log.info("Синтез одним запросом: %d знаков, %d слов",
             len(text), sum(counts))
    wav, duration, words = synthesize_line(workdir, 0, text)
    os.replace(wav, os.path.join(workdir, "voice_all_raw.wav"))
    wav = os.path.join(workdir, "voice_all_raw.wav")

    per_shot = _split_by_counts(words, counts)
    durations = _durations_from_words(per_shot, duration)

    words_global = []
    for i, chunk in enumerate(per_shot):
        for w in chunk:
            words_global.append({"word": w["word"], "start": float(w["start"]),
                                 "end": float(w["end"]), "shot": i})
    _mark_accents(words_global, script)
    return wav, durations, words_global


def _mark_accents(words: list[dict], script: dict) -> None:
    """
    Помечает ключевое слово каждого шота флагом accent — субтитры покрасят его.

    Сверяем по очищенной форме: в таймкодах слово приходит с пунктуацией,
    а в сценарии — без, и прямое сравнение промахивалось бы почти всегда.
    """
    def norm(w: str) -> str:
        return w.strip(".,!?;:—–\"'«»").lower()

    for i, shot in enumerate(script["shots"]):
        key = norm(shot.get("key_word", ""))
        if not key:
            continue
        for w in words:
            if w.get("shot") == i and norm(w["word"]) == key:
                w["accent"] = True
                break


# ── СВОЯ ГОТОВАЯ ОЗВУЧКА ──────────────────────────────────────────────────────

def align_external(workdir: str, script: dict,
                   audio_path: str) -> tuple[str, list[float], list[dict]]:
    """
    Берёт готовый аудиофайл и снимает с него пословные таймкоды через
    forced alignment ElevenLabs, сверяя со сценарным текстом.

    Так работает вариант «озвучил сам или прогнал через студию — приклейте
    субтитры»: тайминги снимаются с ЖИВОЙ речи, поэтому и субтитры, и нарезка
    шотов ложатся ровно под неё.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"VOICE_FILE не найден: {audio_path}")

    text, counts = join_narration(script)
    wav = os.path.join(workdir, "voice_all_raw.wav")
    media.run_ff(["ffmpeg", "-y", "-i", audio_path, "-ar", "44100", "-ac", "2", wav],
                 label="voice_in")
    duration = media.probe_duration(wav)

    url = f"{C.ELEVEN_BASE}/forced-alignment"
    headers = {"xi-api-key": C.require("ELEVENLABS_API_KEY")}
    with open(wav, "rb") as f:
        r = requests.post(url, headers=headers, data={"text": text},
                          files={"file": (os.path.basename(wav), f, "audio/wav")},
                          timeout=300)
    if r.status_code in (401, 402, 403):
        raise TTSPaymentRequired(
            f"Forced alignment: HTTP {r.status_code} — ключ, баланс или права.")
    if not r.ok:
        raise RuntimeError(
            f"Forced alignment HTTP {r.status_code}: {r.text[:300]}. "
            f"Если эндпоинт недоступен на твоём плане, оставь VOICE_FILE пустым "
            f"и синтезируй через VOICE_MODE=whole."
        )
    data = r.json()

    words = data.get("words") or []
    if words:
        parsed = [{"word": w.get("text") or w.get("word", ""),
                   "start": float(w.get("start", 0.0)),
                   "end": float(w.get("end", 0.0))} for w in words]
        parsed = [w for w in parsed if w["word"].strip()]
    else:
        parsed = _words_from_alignment(data.get("characters") and data or {})
    if not parsed:
        raise RuntimeError("Forced alignment не вернул слов")

    log.info("Своя озвучка: %.2fс, выровнено %d слов", duration, len(parsed))
    per_shot = _split_by_counts(parsed, counts)
    durations = _durations_from_words(per_shot, duration)
    words_global = []
    for i, chunk in enumerate(per_shot):
        for w in chunk:
            words_global.append({"word": w["word"], "start": w["start"],
                                 "end": w["end"], "shot": i})
    _mark_accents(words_global, script)
    return wav, durations, words_global


# ── СБОРКА ЗВУКОВОЙ ДОРОЖКИ ───────────────────────────────────────────────────

def build_track(workdir: str, script: dict) -> tuple[str, list[float], list[dict]]:
    """
    Единая точка входа: отдаёт готовую дорожку, длины шотов и пословные тайминги.

    Режимы, в порядке приоритета:
      VOICE_FILE     — своя запись, тайминги снимаются с неё
      VOICE_ENABLED=false — тишина, тайминги считаются из текста
      VOICE_MODE=whole    — весь текст одним запросом (интонация непрерывная)
      VOICE_MODE=per_shot — по шоту за запрос (звучит рвано, только для отладки)
    """
    if C.VOICE_FILE:
        track, durations, words = align_external(workdir, script, C.VOICE_FILE)
    elif C.VOICE_ENABLED and C.VOICE_MODE == "whole":
        track, durations, words = synthesize_whole(workdir, script)
    else:
        # synthesize_script сам добавляет OUTRO_HOLD_SEC к последнему шоту
        wavs, durations, words = synthesize_script(workdir, script)
        raw = os.path.join(workdir, "voice_concat.wav")
        _concat_padded(wavs, durations, raw, workdir)
        return _pad_to(raw, sum(durations), workdir), durations, words

    # Для whole/file хвост добавляем здесь: держим финальный кадр, чтобы
    # последнее слово успело прочитаться.
    if durations and C.OUTRO_HOLD_SEC > 0:
        durations[-1] += C.OUTRO_HOLD_SEC
    return _pad_to(track, sum(durations), workdir), durations, words


def _concat_padded(wavs: list[str], durations: list[float], dst: str,
                   workdir: str) -> str:
    """Пошотовые wav, каждый добит тишиной до своей длины → одна дорожка."""
    padded = []
    for i, (w, d) in enumerate(zip(wavs, durations)):
        p = os.path.join(workdir, f"_vpad_{i:02d}.wav")
        media.run_ff(["ffmpeg", "-y", "-i", w, "-af", "apad", "-t", f"{d:.3f}",
                      "-ar", "44100", "-ac", "2", p], label="voice_pad")
        padded.append(p)
    return media.concat_demux(padded, dst, workdir, reencode=False, label="voice")


def _pad_to(src: str, seconds: float, workdir: str) -> str:
    """Добивает дорожку тишиной до нужной длины (хвост под финальный кадр)."""
    dst = os.path.join(workdir, "voice_all.wav")
    media.run_ff(["ffmpeg", "-y", "-i", src, "-af", "apad",
                  "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2", dst],
                 label="voice_tail")
    return dst
