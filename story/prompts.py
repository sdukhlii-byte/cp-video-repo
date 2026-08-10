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
            "the character performs their action naturally and continuously — "
            "hands, head and posture move, weight shifts, eyes blink and look around; "
            "background life continues around them (light flicker, crowd sway, "
            "drifting smoke); camera moves slowly, no whip pans, no cuts"
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
            "the character keeps performing their action with natural body movement, "
            "slow gentle camera push-in, soft ambient motion, drifting particles"
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
            "the character continues their action with believable body language, "
            "slow dolly-in with slight handheld breathing, atmospheric haze"
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
def frame_rules_with_brand(brand: str, tagline: str = "") -> str:
    allowed = f"the word '{brand}'"
    if tagline:
        allowed = f"the word '{brand}' and the sign text '{tagline}'"
    return (
        "Vertical 9:16 frame. Keep the bottom 25% of the frame visually calm "
        "(no faces, no text, no busy signage) — captions are burned there. "
        f"The ONLY text anywhere in the image is {allowed}. "
        "No other letters, words, slogans, captions or watermarks — leave every "
        "other sign, poster and label completely blank."
    )


SAFETY_CLAUSE = (
    " All characters are adults, fully clothed, non-sexual, non-violent. "
    "No gore, no weapons pointed at anyone, no third-party logos or brand marks."
)


# ── НАТИВНЫЙ ПЛЕЙСМЕНТ ─────────────────────────────────────────────────────────

def build_tagline_clause(tagline: str, surface: str) -> str:
    """
    Короткая вывеска с сообщением бренда в ВЕРХНЕЙ части кадра.

    Верх выбран не случайно: субтитры живут внизу, герой — в середине, и только
    верхняя треть свободна. Плюс вывески в реальном мире висят именно там, так
    что кадр не выглядит подстроенным под рекламу.

    Текст просим набрать заглавными и просторно: модели заметно устойчивее
    рисуют разрядку и капс, чем плотный строчный набор.
    """
    if not tagline:
        return ""
    surface = (surface or "a sign board high on the wall").strip()
    return (
        f" Signage: {surface} hangs in the upper third of the frame and reads "
        f"exactly '{tagline}' — in clean bold capital letters with generous "
        f"spacing, perfectly spelled, sharp and fully legible, lit so it stands "
        f"out from the wall. It reads as permanent signage that belongs to this "
        f"place, not a poster added later. Every character must be correct; "
        f"render no other words anywhere in the frame."
    )


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

## THE GENRE
An off-screen narrator tells ONE story about ONE subject. It is not an essay and
not an ad — it is a chain of concrete facts, each one earning the next second of
attention. The viewer should feel they are learning something specific they can
repeat to a friend.

## NARRATIVE SPINE — follow this shape
1. HOOK: name the thing the viewer already knows, then open the gap.
   "Everyone has eaten this. But do you know where it came from?"
2. COUNTER-INTUITIVE ORIGIN: what it actually was at the start, and it should
   surprise. The bigger the gap from today, the better.
3. THE STRANGE DETAIL: one concrete, slightly absurd specific from that era —
   the part people quote to each other afterwards.
4. THE TURN: a named person, a year and a place where everything changed.
   Names and dates are the backbone of this genre. Never write "one man once" —
   write who, when, where.
5. THE BRIDGE TO TODAY: the second transformation, again with a place and a date.
6. PAYOFF: one line that closes the loop opened by the hook.
7. Optional last line: a curiosity CTA that sends the viewer to search something
   specific ("type X into search and see what it looks like now").

## SENTENCE RULES — this is what separates it from generic AI narration
- Every sentence carries a FACT: a number, a name, a place, a date, an action.
  A sentence that carries only mood is dead weight — cut it.
- Concrete nouns over adjectives. "He added vinegar to the rice" beats
  "he revolutionised the culinary world".
- No filler openers: no "imagine", "it is worth noting", "few people know that",
  "in the world of". Start on the fact.
- No hype words: no "incredible", "shocking", "insane", "genius", "legendary".
  The facts must do the work.
- Vary sentence length. Two long, one short. The short ones land.
- Speak the numbers the way a narrator says them out loud, in words, except for
  years, which stay as digits.

Return STRICT JSON only. No markdown fences, no commentary. Schema:

{
  "title": "short internal title",
  "language": "<target language code>",
  "hook": "3-6 word on-screen hook shown at the very start (target language)",
  "character": {
    "name": "name or role",
    "design": "ENGLISH visual bible of the recurring subject: age, build, face, "
              "hair, signature clothing, distinguishing marks. Concrete and "
              "repeatable — this exact description is reused for every shot. "
              "If the story has no single human subject, describe the recurring "
              "FOCAL OBJECT (a dish, a machine, a product) at the same level of "
              "concrete detail."
  },
  "world": "ENGLISH one-line description of the overall world/era range",
  "shots": [
    {
      "narration": "one line in the TARGET LANGUAGE, ~<WORDS> words",
      "visual": "ENGLISH description of the PLACE only: location, era, time of "
                "day, what fills the background. Do NOT describe the subject's "
                "face or clothes, and do NOT describe their pose here.",
      "action": "ENGLISH: what the subject is physically DOING in this shot, as "
                "a continuous verb phrase — 'hunching over a keyboard, typing "
                "fast', 'packing fish between layers of rice'. Never "
                "'standing', 'posing' or 'looking at the camera'.",
      "framing": "ENGLISH camera framing, DIFFERENT from the previous shot: "
                 "extreme close-up on the face; close-up on the hands; "
                 "over-the-shoulder; from behind; low angle looking up; high "
                 "angle looking down; wide shot with the subject small; "
                 "three-quarter medium shot.",
      "beat": "hook | origin | detail | turn | bridge | payoff | cta",
      "brand_surface": "ENGLISH: one concrete PHYSICAL object already present in "
                       "THIS scene that could plausibly carry a brand name — a "
                       "barrel, a neon sign, a jersey, a poster, a crate, a "
                       "banner, a cap, a coffee cup, a wooden box. NEVER a "
                       "screen, monitor, phone, website or app interface. Just "
                       "the object, no brand name. Empty string if nothing fits.",
      "brand_surface_upper": "ENGLISH: a flat elevated surface high in the UPPER "
                       "part of this scene that a short sign could live on — a "
                       "hanging banner, a wall-mounted sign board, an illuminated "
                       "light box, a painted wall panel above a doorway, a "
                       "stadium ribbon board, a flag over the street. It must "
                       "belong to this place and era. Empty string if nothing fits."
    }
  ],
  "cta": "leave empty — if you want a CTA, make it the last shot's narration"
}

HARD RULES:
1. Exactly <SHOTS> shots.
2. Each narration line ~<WORDS> words. Together they must read as ONE continuous
   spoken paragraph — the lines are cut points for the edit, not separate captions.
   Reading them end to end must sound like one person telling one story.
3. Narration is spoken text: no emojis, no hashtags, no quotes, no parentheses,
   no ALL-CAPS words.
4. At least three shots must contain a hard fact: a year, a name or a number.
   A story without specifics is the failure mode of this genre.
5. Every shot's visual must be a DIFFERENT place, era or moment.
6. Shot 1 opens the curiosity loop. The final shot closes it.
7. No real living people by name, no third-party brand logos, nothing sexual or
   violent.
8. brand_surface must belong to that scene and era, and must be physical, never
   a screen or interface — image models render fake UI text as garbled noise.
9. 'framing' must change from shot to shot. A repeated medium front-facing shot
   is the fastest way to make a video look machine-made.
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
        f"The face and outfit must be crisp and readable — this sheet is an "
        f"IDENTITY reference only: it fixes the face, hair, build and clothing, "
        f"and says nothing about pose, framing or camera angle."
        f"{SAFETY_CLAUSE}"
    )


def build_keyframe_prompt(shot: dict, character: dict, world: str = "",
                          preset: str = "", brand: str = "",
                          brand_mode: str = "native", tagline: str = "") -> str:
    """Кейфрейм шота. Персонаж приходит референс-картинкой, здесь — только сцена."""
    st = style(preset)
    name = str(character.get("name", "the character")).strip()
    visual = str(shot.get("visual", "")).strip()

    # Бренд ставим только в те шоты, которые помечены на этапе нормализации
    # сценария, и только если у сцены есть подходящая поверхность.
    use_brand = bool(brand) and bool(shot.get("brand"))
    use_tagline = bool(tagline) and bool(shot.get("tagline"))
    rules = (frame_rules_with_brand(brand, tagline if use_tagline else "")
             if (use_brand or use_tagline) else FRAME_RULES)
    brand_clause = (build_brand_clause(brand, shot.get("brand_surface", ""), brand_mode)
                    if use_brand else "")
    tagline_clause = (build_tagline_clause(tagline, shot.get("brand_surface_upper", ""))
                      if use_tagline else "")

    action = str(shot.get("action") or "").strip()
    framing = str(shot.get("framing") or "").strip()

    return (
        f"Single cinematic vertical frame. The SAME character as in the reference "
        f"image ('{name}') — copy ONLY the face, hair, build and clothing. "
        f"Do NOT copy the reference pose: the reference shows a neutral standing "
        f"figure, this frame must show a different body position entirely. "
        f"The character is mid-action, caught in the middle of doing something, "
        f"never standing still facing the camera with arms at their sides. "
        + (f"Action: {action}. " if action else "")
        + (f"Camera: {framing}. " if framing else "")
        + f"Scene: {visual}. "
        f"{('World: ' + world + '. ') if world else ''}"
        f"Art style: {st['image']}. "
        f"{rules}"
        f"{brand_clause}"
        f"{tagline_clause}"
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
    action = str(shot.get("action", "")).strip()
    return (
        f"{visual}. "
        # Действие героя ставим ПЕРЕД окружением: если начать с декораций,
        # модель оживляет фон и оставляет персонажа стоять манекеном.
        + (f"The character is actively {action}, and keeps doing it throughout "
           f"the shot with natural continuous body movement. " if action else "")
        + f"{motion + '. ' if motion else ''}"
        f"{st['motion']}. "
        f"The scene is a real place, not an illustration or a screen: "
        f"animate the world itself. Hold the composition — the subject stays "
        f"in frame the whole time. No cuts, no new text appearing."
        + (
            " Any lettering already visible in the frame must stay perfectly "
            "still, sharp and unchanged — do not warp, redraw, animate or "
            "re-letter it as the shot moves."
            if (shot.get("brand") or shot.get("tagline")) else
            " No text, no subtitles, no watermark."
        )
    )
