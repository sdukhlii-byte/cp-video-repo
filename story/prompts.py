"""
story/prompts.py — вся «креативная ДНК» в одном файле: стили, системный промпт
сценариста, сборщики промптов для референса персонажа, кейфреймов и движения.

Правишь креатив — правишь только этот файл.
"""

from __future__ import annotations

import config as C


# ── СТИЛИ ──────────────────────────────────────────────────────────────────────
# Стилевой блок дословно приклеивается к КАЖДОМУ промпту картинки. Именно он,
# а не описание сцены, держит единый вид всех шотов.

STYLE_PRESETS: dict[str, dict] = {
    # Стиль референса: детализированная 16-битная пиксель-иллюстрация.
    "pixel_story": {
        "image": (
            "detailed 16-bit pixel-art illustration, retro game cutscene aesthetic, "
            "crisp pixel edges with clean anti-aliasing, rich saturated palette, "
            "strong rim lighting and volumetric glow, dense environmental detail "
            "(posters, signage, props, background crowd), cinematic vertical composition, "
            "subject framed from chest up in the lower-middle third, "
            "clear empty space across the bottom quarter of the frame for captions"
        ),
        "motion": (
            "subtle cinematic motion only: slow push-in, gentle parallax, ambient life "
            "in the background (light flicker, crowd sway, drifting smoke), "
            "character stays on-model and barely moves, no camera whip, no cuts"
        ),
        "negative": "photorealism, 3d render, blurry, smooth airbrush, text overlays",
    },
    # Мягкая аниме-иллюстрация (lo-fi ключевой кадр).
    "anime_lofi": {
        "image": (
            "hand-painted anime key-visual illustration, soft cel shading, "
            "warm cinematic lighting, lo-fi atmosphere, detailed background art, "
            "vertical composition with the subject in the lower-middle third, "
            "clean empty space across the bottom quarter for captions"
        ),
        "motion": (
            "slow gentle camera push-in, soft ambient motion, drifting particles, "
            "character stays on-model, no fast movement"
        ),
        "negative": "photorealism, 3d render, harsh contrast, text overlays",
    },
    # Кинематографичный «нуар»-док для серьёзных историй.
    "cinematic_doc": {
        "image": (
            "cinematic illustrated still, painterly realism, moody documentary lighting, "
            "shallow depth of field, filmic color grade, "
            "vertical composition with the subject in the lower-middle third, "
            "clean empty space across the bottom quarter for captions"
        ),
        "motion": (
            "slow dolly-in with slight handheld breathing, atmospheric haze, "
            "subject stays on-model, minimal movement"
        ),
        "negative": "cartoon, flat vector, text overlays",
    },
}


def style(name: str = "") -> dict:
    return STYLE_PRESETS.get(name or C.STYLE_PRESET, STYLE_PRESETS["pixel_story"])


# ── ПРАВИЛА КАДРА ──────────────────────────────────────────────────────────────
# Субтитр живёт в нижней четверти — если модель зальёт туда лицо или вывеску,
# слово станет нечитаемым. Поэтому требование чистого низа повторяем везде.

FRAME_RULES = (
    "Vertical 9:16 frame. Keep the bottom 25% of the frame visually calm "
    "(no faces, no text, no busy signage) — captions are burned there. "
    "Never render any letters, words, subtitles or watermarks in the image."
)

SAFETY_CLAUSE = (
    " All characters are adults, fully clothed, non-sexual, non-violent. "
    "No gore, no weapons pointed at anyone, no real-world logos or brand marks."
)


# ── СЦЕНАРИСТ ──────────────────────────────────────────────────────────────────

SCRIPT_SYSTEM = """You write short vertical narrated story videos (TikTok/Reels, 9:16).

FORMAT (this is a strict genre, follow it):
- A single off-screen narrator tells one story, in the target language.
- ONE recurring main character appears in every shot, in different scenes and eras.
- Each shot is a still-frame-like scene that gets subtle motion.
- The pace is fast: one short narration line per shot, no filler words.

Return STRICT JSON only. No markdown fences, no commentary. Schema:

{
  "title": "short internal title",
  "language": "<target language code>",
  "hook": "3-6 word on-screen hook shown at the very start (target language)",
  "character": {
    "name": "name",
    "design": "ENGLISH visual bible of the character: age, build, face, hair, "
              "signature clothing, distinguishing marks. Concrete and repeatable — "
              "this exact description is reused for every shot."
  },
  "world": "ENGLISH one-line description of the overall world/era range",
  "shots": [
    {
      "narration": "one line in the TARGET LANGUAGE, ~<WORDS> words",
      "visual": "ENGLISH description of the scene: location, era, time of day, "
                "what the character is doing, what fills the background. "
                "Do NOT re-describe the character's face/clothes — that comes from the bible.",
      "motion": "ENGLISH one short line: what subtly moves and how the camera drifts",
      "beat": "setup | build | turn | payoff"
    }
  ],
  "cta": "optional final line in the target language, or empty string"
}

HARD RULES:
1. Exactly <SHOTS> shots.
2. Each narration line ~<WORDS> words. Never longer — the shot length is fixed.
   Together they must read as ONE continuous sentence-stream, not separate captions.
3. Narration is spoken text: no emojis, no hashtags, no quotes, no parentheses,
   no ALL-CAPS words. Write numbers as digits only when they are years.
4. Every shot's visual must be a DIFFERENT place or era — visual variety carries
   the video. Same character, new world each shot.
5. Shot 1 must be the strongest image and open a curiosity loop.
   The final shot resolves it.
6. No real living people by name, no real brand logos, nothing sexual or violent.
"""


def build_script_user_prompt(topic: str, language: str, shots: int, words: int,
                             extra: str = "", vertical: str = "") -> str:
    parts = [
        f"Target language for narration: {language}.",
        f"Number of shots: {shots}. Words per narration line: about {words}.",
        f"Total spoken length target: about {C.TARGET_DURATION_SEC:.0f} seconds.",
        f"Topic / story brief: {topic}",
    ]
    if vertical:
        parts.append(f"Brand vertical context (keep it subtle, never salesy): {vertical}")
    if extra:
        parts.append(f"Extra direction: {extra}")
    parts.append("Return the JSON object only.")
    return "\n".join(parts)


def fill_script_system(shots: int, words: int) -> str:
    return SCRIPT_SYSTEM.replace("<SHOTS>", str(shots)).replace("<WORDS>", str(words))


# ── ПРОМПТЫ КАРТИНОК ───────────────────────────────────────────────────────────

def build_character_ref_prompt(character: dict, world: str = "", preset: str = "") -> str:
    """
    Референс-лист персонажа. Это самый важный промпт во всём пайплайне:
    именно его результат уходит референсом в каждый кейфрейм и держит лицо
    одинаковым во всех шотах.
    """
    st = style(preset)
    name = str(character.get("name", "the character")).strip()
    design = str(character.get("design", "")).strip()
    return (
        f"Character reference sheet for '{name}': one single full-body character "
        f"standing centered on a plain neutral studio background, "
        f"neutral expression, front-facing, even lighting, no props, no text. "
        f"Character: {design}. "
        f"{('World context: ' + world + '. ') if world else ''}"
        f"Art style: {st['image']}. "
        f"The face and outfit must be crisp and readable — this sheet is reused "
        f"as the identity reference for every following shot."
        f"{SAFETY_CLAUSE}"
    )


def build_keyframe_prompt(shot: dict, character: dict, world: str = "",
                          preset: str = "") -> str:
    """Кейфрейм шота. Персонаж приходит референс-картинкой, здесь — только сцена."""
    st = style(preset)
    name = str(character.get("name", "the character")).strip()
    visual = str(shot.get("visual", "")).strip()
    return (
        f"Single cinematic vertical frame. The SAME character as in the reference "
        f"image ('{name}') — keep the face, hair and body type exactly on-model. "
        f"Scene: {visual}. "
        f"{('World: ' + world + '. ') if world else ''}"
        f"Art style: {st['image']}. "
        f"{FRAME_RULES}"
        f"{SAFETY_CLAUSE}"
    )


def build_motion_prompt(shot: dict, preset: str = "") -> str:
    """
    Промт движения для image-to-video.

    Главные грабли жанра: если написать «камера едет по кадру/иллюстрации»,
    модель снимет видео ПРО картинку. Пишем действие внутри мира.
    """
    st = style(preset)
    motion = str(shot.get("motion", "")).strip()
    visual = str(shot.get("visual", "")).strip()
    return (
        f"{visual}. "
        f"{motion + '. ' if motion else ''}"
        f"{st['motion']}. "
        f"The scene is a real place, not an illustration or a screen: "
        f"animate the world itself. Hold the composition — the subject stays "
        f"in frame the whole time. No text, no subtitles, no watermark, no cuts."
    )
