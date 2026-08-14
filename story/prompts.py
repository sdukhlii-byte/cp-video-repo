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

# Правило композиции — общее для всех пресетов, поэтому вынесено сюда.
# Ищем баланс: слишком мелкая фигура теряется на вертикальном экране, слишком
# крупная превращает каждый кадр в упор в лицо и лишает сцену контекста —
# а именно окружение и делает кадр интересным. Поэтому просим уверенную
# читаемую фигуру с видимым вокруг неё миром, а не «заполни весь кадр».
COMPOSITION = (
    "confident vertical composition using the full 9:16 frame, "
    "subject clearly readable and well placed, with the surrounding environment "
    "visible around them so the scene has context, "
    "no large dead empty space above the subject, "
    "keep the lowest fifth of the frame visually calm and low-contrast "
    "(plain clothing, floor, desk or ground) so burned-in captions stay readable"
)

STYLE_PRESETS: dict[str, dict] = {
    # Стиль референса: детализированная 16-битная пиксель-иллюстрация.
    "pixel_story": {
        "image": (
            "detailed 16-bit pixel-art illustration, retro game cutscene aesthetic, "
            "crisp pixel edges with clean anti-aliasing, rich saturated palette, "
            "strong rim lighting and volumetric glow, dense environmental detail "
            "(posters, signage, props, background crowd), "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character performs their action naturally and continuously — "
            "hands, head and posture move, weight shifts, eyes blink and look around; "
            "background life continues around them (light flicker, crowd sway, "
            "drifting smoke); camera moves slowly, no whip pans, no cuts"
        ),
        "negative": "photorealism, 3d render, blurry, smooth airbrush, text overlays",
    },
    # Глянцевый мультяшный маскот: толстая чёрная обводка как в комиксе,
    # предельная насыщенность, драматичный стадионный/студийный свет. Это НЕ
    # пиксель-арт — другой визуальный язык, ближе к вирусным спортивным мемам
    # с животными-масками поверх реальных знаменитостей.
    "toon_mascot": {
        "image": (
            "glossy cartoon mascot illustration, thick bold black ink outlines "
            "around every shape like comic book line art, cel-shaded flat colour "
            "fills with punchy highlights, extremely saturated vivid palette, "
            "dramatic rim lighting from stadium floodlights or warm interior "
            "lamps, glossy specular highlights on skin and fabric, high contrast, "
            f"{COMPOSITION}"
        ),
        "motion": (
            "big dynamic sports-poster motion: full-stride running, an arm "
            "thrust high overhead, a dribble past an opponent, hair and jersey "
            "whipping with the movement, confetti or dust kicked up by the "
            "motion, crowd and lights pulsing behind; camera holds a strong "
            "dynamic angle, no slow drift"
        ),
        "negative": "photorealism, pixel art, muted colours, thin linework, text overlays",
    },
    # Ведущая казино-нуар: героиня сидит за столом и обращается к зрителю.
    # direct_address=True снимает общий запрет «не смотреть в камеру» — без
    # этого флага промпт кадра требует героя в движении и отвёрнутым, и стиль
    # разговорного видео просто не собирается.
    "casino_noir_host": {
        "direct_address": True,
        "image": (
            "cinematic illustrated portrait of a striking, elegant woman in her "
            "thirties seated at a dark green felt table, glamorous casino-noir "
            "styling, sharp intelligent gaze directed straight at the viewer, "
            "sleek dark evening wear, tasteful jewellery, deep shadows with a "
            "warm key light on her face, moody bokeh of casino lights behind, "
            "rich blacks, gold and deep red accents, film-noir colour grade, "
            "polished magazine-quality rendering"
        ),
        "motion": (
            "she speaks directly to the viewer with natural conversational "
            "movement — subtle head tilts, expressive eyes, small confident hand "
            "gestures over the table, chips or cards shifting slightly under her "
            "fingers; background lights breathe softly; camera holds a slow "
            "almost imperceptible push-in"
        ),
        "negative": (
            "nudity, revealing clothing, sexualised posing, photorealistic "
            "likeness of a real person, pixel art, text overlays"
        ),
    },
    # Мягкая аниме-иллюстрация (lo-fi ключевой кадр).
    "anime_lofi": {
        "image": (
            "hand-painted anime key-visual illustration, soft cel shading, "
            "warm cinematic lighting, lo-fi atmosphere, detailed background art, "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character keeps performing their action with natural body movement, "
            "slow gentle camera push-in, soft ambient motion, drifting particles"
        ),
        "negative": "photorealism, 3d render, harsh contrast, text overlays",
    },
    # Пиксель + глянец: праздник, ночная жизнь, неон. Люди эффектные и
    # стильные, но кадр остаётся про атмосферу, а не про тела — иначе
    # контент-фильтр режет генерацию, и половина шотов уходит в фолбэк.
    "pixel_glam": {
        "image": (
            "detailed 16-bit pixel-art illustration with a glossy modern finish, "
            "nightlife glamour, confident stylish adults celebrating, elegant "
            "evening outfits, sparkling highlights, champagne and confetti, "
            "saturated neon palette of magenta cyan and gold, strong rim lighting, "
            "bokeh light bloom, crisp pixel edges over smooth gradient shading, "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character keeps celebrating with natural continuous movement — "
            "laughing, raising a glass, hair and clothing moving; confetti drifts, "
            "lights sweep and pulse across the room; slow cinematic push-in"
        ),
        "negative": "photorealism, nudity, revealing outfits, distorted faces, text overlays",
    },
    # Пиксель + аниме: мягкая заливка поверх пиксельной сетки.
    "pixel_anime": {
        "image": (
            "hybrid style: 16-bit pixel-art structure with hand-painted anime "
            "shading on top — crisp pixel edges on props and environment, but soft "
            "cel-shaded faces and hair, expressive anime eyes, warm cinematic "
            "rim light, detailed background art, vertical composition with the "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character continues their action with expressive anime-style "
            "movement, hair and fabric flowing, soft particles drifting, "
            "slow camera push-in"
        ),
        "negative": "photorealism, 3d render, harsh contrast, text overlays",
    },
    # Воксель: кадр СОБРАН ИЗ КУБИКОВ. Формулировка однозначная — раньше здесь
    # было «воксельные формы + настоящая глубина резкости», и модель каждый раз
    # выбирала между двумя видами по-своему.
    "voxel": {
        "image": (
            "voxel art: every object in the scene is built from visible cubic "
            "blocks, including hair, fabric and foliage, blocky stair-stepped "
            "silhouettes, chunky quantised texture, limited retro palette, "
            "soft global illumination, cinematic vertical composition, subject "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character keeps performing their action with weighty blocky "
            "movement, light shifting across the cubic surfaces, slow dolly-in"
        ),
        "negative": "smooth surfaces, photorealism, flat vector, text overlays",
    },
    # Гладкий стилизованный 3D — вид анимационного полного метра.
    # Ровно то, что получается, когда кадр проходит через видеомодель.
    "stylized_3d": {
        "image": (
            "stylised 3D animation still, feature-film CG look, smooth clean "
            "surfaces, soft subsurface skin shading, expressive stylised "
            "proportions, warm cinematic key light with soft shadows, shallow "
            "depth of field, rich but natural palette, cinematic vertical "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character keeps performing their action with smooth weighty "
            "animation, hair and clothing following the movement, soft light "
            "shifting, slow cinematic dolly-in"
        ),
        "negative": "voxel, pixel art, photorealism, flat vector, text overlays",
    },
    # По бренд-буку Coinplay: 3D-неон, фиолет и маджента, пузырьковые кластеры
    # на глубоком тёмно-фиолетовом фоне. Это не пиксель-арт — это фирменный вид
    # сайта и баннеров, перенесённый в вертикальное видео.
    "coinplay_brand": {
        "image": (
            "3D neon render style: soft-textured dimensional subjects lit by "
            "violet and magenta light, floating translucent bubble clusters "
            "wrapping the figure, deep purple background (#09001B to #4110A4) "
            "with a radial magenta glow behind the subject, glossy premium "
            "finish, duotone violet-to-magenta rim lighting, never flat colour, "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the subject keeps performing their action with weighty three-"
            "dimensional movement, translucent bubbles drifting and rotating "
            "slowly around them, neon glow pulsing, slow cinematic push-in"
        ),
        "negative": "flat colour, pixel art, photorealistic documentary, text overlays",
    },
    # Кинематографичный «нуар»-док для серьёзных историй.
    "cinematic_doc": {
        "image": (
            "cinematic illustrated still, painterly realism, moody documentary lighting, "
            "shallow depth of field, filmic color grade, "
            f"{COMPOSITION}"
        ),
        "motion": (
            "the character continues their action with believable body language, "
            "slow dolly-in with slight handheld breathing, atmospheric haze"
        ),
        "negative": "cartoon, flat vector, text overlays",
    },
}


def is_direct_address(preset: str = "") -> bool:
    """
    Стиль разговорного видео: герой сидит и обращается к зрителю.

    Общие правила промпта требуют героя в движении и запрещают смотреть в
    камеру — для сюжетного ролика это верно, но «ведущая за столом» так не
    собирается вообще. Флаг объявляется в самом пресете, чтобы переключение
    стиля не требовало помнить про отдельную переменную.
    """
    st = STYLE_PRESETS.get(preset or C.STYLE_PRESET, {})
    return bool(st.get("direct_address"))


def style(name: str = "") -> dict:
    """
    Активный стиль: пресет плюс переопределения из окружения.

    STYLE_IMAGE / STYLE_MOTION / STYLE_NEGATIVE позволяют задать свой стиль
    целиком из переменных, не трогая код и не пересобирая образ — иначе любая
    проба нового вида требовала бы правки файла и деплоя.
    """
    base = STYLE_PRESETS.get(name or C.STYLE_PRESET, STYLE_PRESETS["pixel_story"])
    merged = dict(base)
    if C.STYLE_IMAGE:
        merged["image"] = C.STYLE_IMAGE
    if C.STYLE_MOTION:
        merged["motion"] = C.STYLE_MOTION
    if C.STYLE_NEGATIVE:
        merged["negative"] = C.STYLE_NEGATIVE
    if C.STYLE_EXTRA:
        merged["image"] = f"{merged['image']}, {C.STYLE_EXTRA}"
    return merged


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

## THE FIRST 1.5 SECONDS DECIDE EVERYTHING
Most viewers leave before the second shot. Shot 1 is not an introduction, it is
the whole pitch. It must satisfy all three at once:
  - the IMAGE is the single most arresting frame in the story — the strangest,
    most specific, most "wait, what is that" moment, even if chronologically it
    belongs later;
  - the LINE states a fact that contradicts what the viewer assumes;
  - nothing is explained yet. Explanation is what shot 2 is for.
Never open on a wide establishing shot, a calm landscape, or a person standing
in a room. Open on a face, on hands doing something, or on the object itself.

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
                "a continuous verb phrase. Match the amplitude to the beat: "
                "quiet beats get fine motor detail ('hunching over a keyboard, "
                "typing fast'), but turn/payoff/celebration beats need BIG "
                "full-body movement ('sprinting at full stride', 'thrusting a "
                "fist overhead', 'spinning past an opponent') — small gestures "
                "read as flat and lifeless on a triumphant beat. Never "
                "'standing', 'posing' or 'looking at the camera'.",
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
      "beat": "hook | origin | detail | turn | bridge | payoff | cta",
      "key_word": "ONE TO THREE consecutive words copied EXACTLY from this "
                  "shot's narration — either the fact (a year, a number, a "
                  "name, a place) or, if there is no fact, the single most "
                  "emotionally loaded phrase in the line, the part a viewer "
                  "would repeat out loud. Must be a verbatim substring of the "
                  "narration, not a paraphrase. Empty string only if truly "
                  "nothing stands out.",
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
   The final shot's VISUAL must echo the first shot's visual — same place, same
   object or same gesture, changed by the story. A viewer who reaches the end
   lands back where they started, which is what makes short video loop instead
   of ending. Looping replays are counted as views.
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


DIRECT_ADDRESS_OVERRIDE = """

## OVERRIDE — THIS VIDEO IS A PIECE TO CAMERA
The subject is a single host seated at a table, speaking directly to the viewer
for the whole video. This replaces the rules about varied locations and big
physical action:
- Every shot stays at the same table. Do not invent new locations.
- 'action' is a conversational beat, not a physical feat: leaning in, tilting
  the head, raising an eyebrow, sliding a chip across the felt, folding hands,
  a knowing half-smile. Never 'standing', 'running' or 'posing'.
- 'framing' varies the camera instead of the place: close-up on the face;
  medium shot from across the table; slight low angle; over-the-shoulder from
  behind her; close-up on her hands on the felt; three-quarter side view.
- 'visual' describes the same room changing subtly — lighting shifts, the
  crowd behind her, smoke, the spread of chips — not a different world.
- 'brand_surface' should be something on or near the table: a chip stack, a
  card shoe, a coaster, a table sign, a bottle label.
"""


def fill_script_system(shots: int, words: int, direct_address: bool = False) -> str:
    base = SCRIPT_SYSTEM.replace("<SHOTS>", str(shots)).replace("<WORDS>", str(words))
    # Стиль «ведущая за столом» отменяет требование менять локацию каждый шот и
    # играть крупным действием: без этой поправки сценарист гонит героиню по
    # разным местам, и разговорное видео разваливается.
    return base + DIRECT_ADDRESS_OVERRIDE if direct_address else base


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
    direct_address = is_direct_address(preset)

    return (
        "Single cinematic vertical frame. "
        # Ракурс ставим ПЕРВЫМ и с нажимом: если он идёт в середине промпта
        # среди описаний стиля и сцены, модель тяготеет к безопасному среднему
        # плану и фигура выходит мелкой.
        + (f"SHOT SIZE — {framing}. The subject is clearly readable and well "
           f"placed in the frame, not lost in a distant wide view. "
           if framing else "")
        + f"The SAME character as in the reference "
        f"image ('{name}') — copy ONLY the face, hair, build and clothing. "
        + (
            # Разговорный стиль: героиня сидит и обращается к зрителю. Общий
            # запрет «не смотреть в камеру» здесь пришлось бы нарушать, поэтому
            # для таких пресетов даём противоположную инструкцию.
            "She is seated at the table, facing the viewer and speaking directly "
            "to camera, engaged and mid-sentence, with a natural relaxed posture "
            "and expressive eye contact. "
            if direct_address else
            "Do NOT copy the reference pose: the reference shows a neutral standing "
            "figure, this frame must show a different body position entirely. "
            "The character is mid-action, caught in the middle of doing something, "
            "never standing still facing the camera with arms at their sides. "
        )
        + (f"Action: {action}. " if action else "")
        + f"Scene: {visual}. "
        f"{('World: ' + world + '. ') if world else ''}"
        f"Art style: {st['image']}. "
        f"{rules}"
        f"{brand_clause}"
        f"{tagline_clause}"
        f"{SAFETY_CLAUSE}"
    )


def _style_anchor(st: dict) -> str:
    """
    Короткая выжимка стиля для промпта движения.

    Без неё image-to-video модель получает только описание сцены и «дорисовывает»
    кадр в свой дефолтный гладкий рендер: воксельная фактура сглаживается,
    пиксельная сетка исчезает, и шоты, прошедшие через видеомодель, начинают
    выглядеть иначе, чем шоты, оставшиеся зумом из кейфрейма. В одном ролике
    получаются два разных визуальных языка.
    """
    head = st["image"].split(",")[:4]
    return ", ".join(part.strip() for part in head)


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
        f"in frame the whole time. No cuts, no new text appearing. "
        # Стиль повторяем и требуем сохранить: иначе видеомодель приводит кадр
        # к своему рендеру по умолчанию, и стилизация исходника теряется.
        f"CRITICAL — preserve the exact art style of the source frame: "
        f"{_style_anchor(st)}. Keep the same texture, the same level of detail "
        f"and the same colour palette as the first frame. Do not smooth, "
        f"re-render, upgrade or realistically re-interpret the image."
        + (
            " Any lettering already visible in the frame must stay perfectly "
            "still, sharp and unchanged — do not warp, redraw, animate or "
            "re-letter it as the shot moves."
            if (shot.get("brand") or shot.get("tagline")) else
            " No text, no subtitles, no watermark."
        )
    )
