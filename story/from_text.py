"""
story/from_text.py — сценарий из ГОТОВОГО текста озвучки.

Когда текст написан человеком, менять его нельзя: интонация, порядок фактов и
ударения — это и есть авторская работа. Поэтому здесь LLM не пишет ни слова
нарратива. Он получает уже разбитый на шоты текст и придумывает только картинку
к каждому: место, действие героя, ракурс, поверхность под бренд.

Разбивка на шоты делается кодом, а не моделью: модель на длинном тексте
регулярно теряет предложения или перефразирует их, а здесь важна дословность.
"""

from __future__ import annotations

import os
import logging
import re

import config as C
from story import orclient
from story.prompts import (DIRECT_ADDRESS_OVERRIDE, HYBRID_INTRO_OVERRIDE,
                           is_direct_address)
from story.script_writer import _extract_json, clean_narration, coerce

log = logging.getLogger("fromtext")


# ── РАЗБИВКА ТЕКСТА НА ШОТЫ ────────────────────────────────────────────────────

# Границы, по которым резать можно, в порядке предпочтения: конец предложения
# лучше запятой, запятая лучше разрыва посреди словосочетания.
_STRONG = re.compile(r"(?<=[.!?…])\s+")
_WEAK = re.compile(r"(?<=[,;:—–])\s+")


def split_into_shots(text: str, words_per_shot: int = 0,
                     tolerance: float = 1.6) -> list[str]:
    """
    Режет сплошной текст на реплики примерно по words_per_shot слов,
    стараясь не разрывать предложения.

    Логика простая: идём по предложениям и копим их в шот, пока помещаемся в
    бюджет. Предложение, которое само по себе длиннее бюджета, дорезаем по
    запятым, а если и это не помогло — по словам (последнее средство).
    """
    words_per_shot = words_per_shot or C.words_per_shot()
    hard = int(words_per_shot * tolerance)

    def by_words(chunk: str) -> list[str]:
        w = chunk.split()
        return [" ".join(w[i:i + words_per_shot])
                for i in range(0, len(w), words_per_shot)]

    pieces: list[str] = []
    for sentence in _STRONG.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence.split()) <= hard:
            pieces.append(sentence)
            continue
        # Слишком длинное предложение — режем по запятым
        buf = ""
        for part in _WEAK.split(sentence):
            cand = f"{buf} {part}".strip()
            if buf and len(cand.split()) > hard:
                pieces.append(buf)
                buf = part
            else:
                buf = cand
        if buf:
            pieces.extend([buf] if len(buf.split()) <= hard else by_words(buf))

    # Склеиваем короткие соседние куски, чтобы шоты не были по два слова
    shots: list[str] = []
    for piece in pieces:
        if shots and len(shots[-1].split()) + len(piece.split()) <= words_per_shot:
            shots[-1] = f"{shots[-1]} {piece}"
        else:
            shots.append(piece)

    return [clean_narration(s) for s in shots if s.strip()]


# ── ВИЗУАЛЬНЫЙ СЛОЙ ПОД ГОТОВЫЙ ТЕКСТ ─────────────────────────────────────────

VISUALS_SYSTEM = """You are a storyboard artist for short vertical narrated videos.

You are given the narration ALREADY WRITTEN and ALREADY SPLIT into shots.
You must NOT change, rewrite, shorten, translate or reorder a single word of it.
Your only job is to invent the picture for each shot.

Return STRICT JSON only, no markdown fences:

{
  "title": "short internal title",
  "character": {
    "name": "name or role",
    "design": "ENGLISH visual bible of the recurring subject: age, build, face, "
              "hair, signature clothing. If the narration has no single human "
              "subject, describe the recurring FOCAL OBJECT instead (a dish, a "
              "machine, a product) with the same level of concrete detail."
  },
  "world": "ENGLISH one-line description of the overall world / era range",
  "shots": [
    {
      "visual": "ENGLISH description of the PLACE: location, era, time of day, "
                "what fills the background. Never describe the subject's face or "
                "clothes, and never describe their pose here.",
      "action": "ENGLISH: what is physically happening in this shot, as a "
                "continuous verb phrase. Never 'standing' or 'posing'.",
      "framing": "ENGLISH camera framing, DIFFERENT from the previous shot. Vary "
                 "the shot size across the video — mix close and medium shots so "
                 "it does not feel monotonous. The subject should be clearly "
                 "readable, but the environment must stay visible around them: "
                 "avoid only extreme close-ups, and avoid distant wide "
                 "establishing views where the subject gets lost. Pick from: "
                 "close-up on the face; close-up on the hands at work; "
                 "over-the-shoulder from behind; low angle looking up; "
                 "medium shot from the waist up; full-body shot with the "
                 "environment around them; three-quarter side view.",
      "beat": "setup | build | turn | payoff",
      "brand_surface": "ENGLISH: one PHYSICAL object in this scene that could "
                       "carry a brand name — a barrel, a banner, a crate, a cap, "
                       "a cup, a jersey. NEVER a screen or a user interface. "
                       "Empty string if nothing fits.",
      "brand_surface_upper": "ENGLISH: a flat elevated surface high in the UPPER "
                       "part of this scene for a short sign — a hanging banner, a "
                       "wall sign board, a light box, a panel above a doorway, a "
                       "flag over the street. Empty string if nothing fits."
    }
  ]
}

RULES:
1. Exactly one shot object per narration line, in the same order. Same count.
2. Each shot must illustrate ITS OWN narration line literally — if the line says
   "he moved to Moscow", show the move, not a generic city.
3. Every consecutive shot must be a visibly different place, angle or moment.
   Repetition is what makes a video look machine-made.
4. No real living people by name, no third-party logos, nothing sexual or violent.
"""


def build_visuals(narration_lines: list[str], language: str = "",
                  hook: str = "", extra: str = "", model: str = "",
                  retries: int = 2) -> dict:
    numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(narration_lines))
    user = (
        f"Narration language: {language or C.LANG}.\n"
        f"Number of shots: {len(narration_lines)}.\n"
        + (f"Extra art direction: {extra}\n" if extra else "")
        + f"\nNarration lines (do not change them):\n{numbered}\n\n"
        f"Return the JSON object only."
    )

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            system = VISUALS_SYSTEM
            if C.INTRO_HOST_SHOTS > 0:
                # Гибрид: ведущая открывает ролик, дальше история.
                system += HYBRID_INTRO_OVERRIDE.replace("<INTRO>",
                                                        str(C.INTRO_HOST_SHOTS))
            elif is_direct_address():
                # Разговорный стиль отменяет требование менять локацию каждый
                # шот — иначе ведущая за столом «переезжает» между кадрами.
                system += DIRECT_ADDRESS_OVERRIDE
            raw = orclient.chat(system, user, model=model, temperature=0.9)
            data = _extract_json(raw)
            shots = data.get("shots") or []
            if len(shots) != len(narration_lines):
                raise ValueError(
                    f"модель вернула {len(shots)} шотов вместо {len(narration_lines)}")
            # Нарратив подставляем СВОЙ — что бы модель ни прислала в своих полях.
            for shot, line in zip(shots, narration_lines):
                shot["narration"] = line
            data["shots"] = shots
            data.setdefault("language", language or C.LANG)
            data["hook"] = clean_narration(hook or data.get("hook", ""))
            return coerce(data, shots=len(narration_lines), words=10**6)
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("Раскадровка, попытка %d/%d: %s", attempt, retries, str(e)[:200])
    raise RuntimeError(f"Не удалось построить раскадровку под текст: {last}")


def script_from_text(text: str, language: str = "", hook: str = "",
                     extra: str = "", words_per_shot: int = 0,
                     model: str = "") -> dict:
    lines = split_into_shots(text, words_per_shot)
    total_words = sum(len(l.split()) for l in lines)
    est = total_words / max(C.WORDS_PER_SEC, 0.5) + len(lines) * C.VOICE_TAIL_SEC
    log.info("Текст разбит: %d шотов, %d слов, ~%.0fс звучания",
             len(lines), total_words, est)
    return build_visuals(lines, language=language, hook=hook, extra=extra, model=model)


def estimate(text: str, words_per_shot: int = 0) -> dict:
    """Оценка без единого вызова API — сколько выйдет шотов, секунд и денег."""
    lines = split_into_shots(text, words_per_shot)
    total_words = sum(len(l.split()) for l in lines)
    seconds = total_words / max(C.WORDS_PER_SEC, 0.5) + len(lines) * C.VOICE_TAIL_SEC
    seconds += C.OUTRO_HOLD_SEC
    animated = len(lines) if C.ANIMATE_RATIO >= 1.0 else max(
        0, round(len(lines) * C.ANIMATE_RATIO))
    clip = min(d for d in C.VIDEO_ALLOWED_DURS
               if d >= C.SHOT_TARGET_SEC) if C.VIDEO_ALLOWED_DURS else 4
    # Грубая оценка расхода. Цена картинки замерена по логам живых прогонов
    # ($0.0393 за кейфрейм), цена видео — порядок величины для fast-тарифа Veo.
    # Это ориентир, чтобы увидеть масштаб ДО трат, а не счёт.
    img_cost = (len(lines) + 1) * 0.04
    vid_cost = animated * clip * 0.15
    return {
        "shots": len(lines),
        "cost_images": round(img_cost, 2),
        "cost_video": round(vid_cost, 2),
        "cost_total": round(img_cost + vid_cost + 0.07, 2),
        "words": total_words,
        "seconds": round(seconds, 1),
        "animated_shots": animated,
        "video_seconds": animated * clip,
        "lines": lines,
    }


# ── НАРЕЗКА ПО РЕАЛЬНОМУ ЗВУЧАНИЮ ─────────────────────────────────────────────

def split_by_timings(words: list[dict], target_sec: float = 0.0) -> list[list[dict]]:
    """
    Режет пословные таймкоды на шоты по РЕАЛЬНОЙ длительности, а не по числу слов.

    Это снимает необходимость угадывать темп речи: сколько бы слов ни успевал
    произнести голос, шот всё равно получится нужной длины. Границу стараемся
    ставить на конце предложения, затем на запятой, и только в крайнем случае
    рвём посреди фразы.
    """
    target = target_sec or C.SHOT_TARGET_SEC
    shots: list[list[dict]] = []
    cur: list[dict] = []

    for w in words:
        cur.append(w)
        span = float(cur[-1]["end"]) - float(cur[0]["start"])
        if span < target * 0.75:
            continue

        raw = str(w["word"]).rstrip('"\')»')
        sentence_end = raw.endswith((".", "!", "?", "…"))
        clause_end = raw.endswith((",", ";", ":", "—", "–"))
        # За целевой длиной режем на первой же возможной границе, а сильно
        # раньше — только на конце предложения.
        if sentence_end or (span >= target and clause_end) or span >= target * 1.5:
            shots.append(cur)
            cur = []

    if cur:
        # Хвост короче половины цели приклеиваем к предыдущему шоту, иначе
        # последний кадр мелькнёт и пропадёт.
        if shots and (float(cur[-1]["end"]) - float(cur[0]["start"])) < target * 0.5:
            shots[-1].extend(cur)
        else:
            shots.append(cur)
    return shots


def script_from_text_timed(text: str, workdir: str, language: str = "",
                           hook: str = "", extra: str = "",
                           model: str = "") -> dict:
    """
    Сценарий из готового текста с нарезкой по реальному звучанию.

    Порядок обратный обычному: сначала синтезируем ВЕСЬ текст одним запросом,
    получаем пословные таймкоды, и только потом решаем, где границы шотов.
    Готовая дорожка кладётся в сценарий и переиспользуется на рендере — второй
    раз за озвучку не платим.
    """
    from story import voice

    os.makedirs(workdir, exist_ok=True)
    # Чистим ДО синтеза: иначе разметка и кавычки попадают и в озвучку, и в
    # таймкоды, а оттуда в субтитры — так на экране оказалось «good story.**».
    spoken = clean_narration(text)
    if not spoken.strip():
        raise ValueError("После очистки текст оказался пустым")
    wav, duration, words = voice.synthesize_line(workdir, 0, spoken)
    if not words:
        raise RuntimeError("TTS не вернул пословные таймкоды — нарезка по времени невозможна")

    groups = split_by_timings(words)
    lines = [" ".join(str(w["word"]) for w in g).strip() for g in groups]
    lines = [clean_narration(l) for l in lines if l.strip()]
    log.info("Текст нарезан по звучанию: %d шотов, %.0fс, реальный темп %.2f слова/сек",
             len(lines), duration, len(words) / max(duration, 0.1))

    script = build_visuals(lines, language=language, hook=hook, extra=extra, model=model)
    # Дорожка уже синтезирована — отдаём её рендеру, чтобы не платить дважды.
    script["_pre_synth"] = {
        "wav": os.path.abspath(wav),
        "groups": [[{"word": str(w["word"]),
                     "start": float(w["start"]),
                     "end": float(w["end"])} for w in g] for g in groups],
        "duration": duration,
    }
    return script
