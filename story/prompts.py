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

# Когда бренд в кадре, запрет «никаких букв» снимается — но ТОЛЬКО для одного
# слова. Иначе модель дорисовывает случайный текст на всех поверхностях, и кадр
# превращается в кашу из нечитаемых надписей.
def frame_rules_with_brand(brand: str) -> str:
    return (
        "Vertical 9:16 frame. Keep the bottom 25% of the frame visually calm "
        "(no faces, no text, no busy signage) — captions are burned there. "
        f"The ONLY text anywhere in the image is the single word '{brand}'. "
        "No other letters, words, slogans, captions or watermarks — leave every "
        "other sign, poster and label completely blank."
    )


SAFETY_CLAUSE = (
    " All characters are adults, fully clothed, non-sexual, non-violent. "
    "No gore, no weapons pointed at anyone, no third-party logos or brand marks."
)


# ── НАТИВНЫЙ ПЛЕЙСМЕНТ ─────────────────────────────────────────────────────────

def build_brand_clause(brand: str, surface: str, mode: str = "native") -> str:
    """
    Инструкция по размещению имени бренда на предмете внутри сцены.

    `surface` — конкретный предмет из сценария («a rusty barrel», «a neon sign
    above the bar»). Без него модель лепит название в воздух или на всю стену.

    Режимы:
      native — предмет живёт в кадре как часть мира, читается, но не доминирует
      hero   — предмет в фокусе, крупно, это главный объект кадра
    """
    if not brand:
        return ""
    surface = (surface or "a sign in the background").strip()
    if mode == "hero":
        return (
            f" Brand placement: {surface} is the visual centre of the frame, "
            f"large and in sharp focus, with the word '{brand}' printed on it in "
            f"clean bold letters, perfectly spelled, fully legible, unobstructed. "
            f"The lettering follows the surface (curved on curved objects, "
            f"weathered on old ones) so it reads as part of the object, not a sticker."
        )
    return (
        f" Brand placement: {surface} carries the word '{brand}' in clean bold "
        f"letters, perfectly spelled and legible, integrated into the scene's "
        f"lighting and materials as if it has always been there. The lettering is "
        f"large enough to read at a glance on a phone screen — it spans most of "
        f"that object's visible width. It sits in the middle or upper part of the "
        f"frame, noticeable but not blocking the character or the action. "
        f"Do not render any user interface, website or app layout anywhere in the frame."
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
      "beat": "setup | build | turn | payoff",
      "brand_surface": "ENGLISH: one concrete PHYSICAL object already present in "
                       "THIS scene that could plausibly carry a brand name — a "
                       "barrel, a neon sign, a jersey, a poster, a crate, a banner, "
                       "a cap, a coffee cup, a server rack. NEVER a screen, monitor, "
                       "phone, website or app interface. Just the object, no brand "
                       "name. Empty string if nothing fits."
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
6. No real living people by name, no third-party brand logos, nothing sexual or violent.
7. brand_surface must be an object that BELONGS in that scene and era — a 90s
   market stall gets a cardboard box, a night club gets a neon sign. Never invent
   an out-of-place billboard just to fit a brand.
8. brand_surface must be a PHYSICAL surface, never a screen or a user interface.
   Image models render fake UI text as garbled noise, so a brand name placed on a
   monitor comes out misspelled and unreadable. Prefer large flat physical
   surfaces facing the camera — they hold lettering far more reliably.
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
                          preset: str = "", brand: str = "",
                          brand_mode: str = "native") -> str:
    """Кейфрейм шота. Персонаж приходит референс-картинкой, здесь — только сцена."""
    st = style(preset)
    name = str(character.get("name", "the character")).strip()
    visual = str(shot.get("visual", "")).strip()

    # Бренд ставим только в те шоты, которые помечены на этапе нормализации
    # сценария, и только если у сцены есть подходящая поверхность.
    use_brand = bool(brand) and bool(shot.get("brand"))
    rules = frame_rules_with_brand(brand) if use_brand else FRAME_RULES
    brand_clause = (build_brand_clause(brand, shot.get("brand_surface", ""), brand_mode)
                    if use_brand else "")

    return (
        f"Single cinematic vertical frame. The SAME character as in the reference "
        f"image ('{name}') — keep the face, hair and body type exactly on-model. "
        f"Scene: {visual}. "
        f"{('World: ' + world + '. ') if world else ''}"
        f"Art style: {st['image']}. "
        f"{rules}"
        f"{brand_clause}"
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
        f"in frame the whole time. No cuts, no new text appearing."
        + (
            " Any lettering already visible in the frame must stay perfectly "
            "still, sharp and unchanged — do not warp, redraw, animate or "
            "re-letter it as the shot moves."
            if shot.get("brand") else
            " No text, no subtitles, no watermark."
        )
    )
