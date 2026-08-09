"""
config.py — Story Videos (формат «ИСТОК»): закадровый рассказ + пословные
караоке-субтитры + консистентный персонаж во всех шотах.

Обязательных ключей ДВА:
  OPENROUTER_API_KEY   — текстовая модель (сценарий), картинки (кейфреймы), Veo (видео)
  ELEVENLABS_API_KEY   — озвучка с пословными таймкодами

Всё остальное опционально и имеет дефолты. Airtable/Telegram/S3 подключаются
позже — CLI работает без них.
"""

from __future__ import annotations

import os


def _opt(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


def _f(key: str, default: float) -> float:
    try:
        return float(_opt(key, str(default)))
    except ValueError:
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(float(_opt(key, str(default))))
    except ValueError:
        return default


def _b(key: str, default: bool) -> bool:
    return _opt(key, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


ROOT = os.path.dirname(os.path.abspath(__file__))


def require(key: str) -> str:
    """Ленивая проверка ключа — вызывается только тем модулем, которому он нужен."""
    val = os.environ.get(key)
    if not val:
        raise EnvironmentError(
            f"Missing env var {key}. Скопируй .env.example → .env и заполни, "
            f"либо экспортируй переменную в шелле."
        )
    return val


# ── КАДР ───────────────────────────────────────────────────────────────────────
VIDEO_W = _i("VIDEO_W", 1080)
VIDEO_H = _i("VIDEO_H", 1920)
FPS     = _i("FPS", 30)
ASPECT  = _opt("ASPECT", "9:16")

# ── ХРОНОМЕТРАЖ ────────────────────────────────────────────────────────────────
# Целевая длина ролика и длина шота. Шотов = round(TARGET/SHOT).
# 30с / 4с = ~8 шотов. Длину шота диктует озвучка, но сценарист пишет реплики
# под SHOT_TARGET_SEC, чтобы клипы Veo не приходилось резать вхолостую.
TARGET_DURATION_SEC = _f("TARGET_DURATION_SEC", 30.0)
SHOT_TARGET_SEC     = _f("SHOT_TARGET_SEC", 4.0)
MIN_SHOT_SEC        = _f("MIN_SHOT_SEC", 1.6)
VOICE_TAIL_SEC      = _f("VOICE_TAIL_SEC", 0.22)   # воздух после реплики внутри шота
WORDS_PER_SEC       = _f("WORDS_PER_SEC", 2.3)     # темп речи для планирования сценария

# ── OPENROUTER ─────────────────────────────────────────────────────────────────
OR_BASE     = "https://openrouter.ai/api/v1"
OR_REFERER  = _opt("OR_REFERER", "https://coinplay.com")
OR_TITLE    = _opt("OR_TITLE", "Story Videos")

# Текстовая модель-сценарист.
SCRIPT_MODEL = _opt("SCRIPT_MODEL", "anthropic/claude-sonnet-4.5")

# Картиночная модель (кейфреймы + референс-лист персонажа).
# Nano Banana / Gemini Image держит мульти-референс — это то, чем достигается
# консистентность персонажа между шотами.
IMAGE_MODEL      = _opt("IMAGE_MODEL", "google/gemini-2.5-flash-image")
IMAGE_RESOLUTION = _opt("IMAGE_RESOLUTION", "")     # пусто = дефолт модели

# Видеомодель (image-to-video). ВАЖНО: слаги видеомоделей на OpenRouter меняются —
# проверь актуальный через `python3 cli.py models` и подставь сюда/в .env.
VIDEO_MODEL           = _opt("VIDEO_MODEL", "google/veo-3.1-fast")
VIDEO_RESOLUTION      = _opt("VIDEO_RESOLUTION", "720p")
VIDEO_ALLOWED_DURS    = [int(x) for x in _opt("VIDEO_ALLOWED_DURS", "4,6,8").split(",") if x.strip()]
VIDEO_GENERATE_AUDIO  = _b("VIDEO_GENERATE_AUDIO", False)   # звук берём из ElevenLabs
VIDEO_NEGATIVE        = _opt("VIDEO_NEGATIVE",
                             "text, watermark, subtitles, caption, logo, distorted face, "
                             "morphing, extra limbs, flicker, jump cut")

# Фолбэк-видеомодель, если основная отказала (контент-фильтр/рейт-лимит).
SECONDARY_VIDEO_ENABLED = _b("SECONDARY_VIDEO_ENABLED", True)
SECONDARY_VIDEO_MODEL   = _opt("SECONDARY_VIDEO_MODEL", "bytedance/seedance-2.0")

# Последний рубеж: если видео не собралось вообще — оживляем кейфрейм зумом.
KENBURNS_FALLBACK = _b("KENBURNS_FALLBACK", True)

# ── ELEVENLABS ─────────────────────────────────────────────────────────────────
ELEVEN_BASE     = "https://api.elevenlabs.io/v1"
ELEVEN_VOICE_ID = _opt("ELEVEN_VOICE_ID", "")        # обязателен для render
ELEVEN_MODEL    = _opt("ELEVEN_MODEL", "eleven_multilingual_v2")
ELEVEN_STABILITY = _f("ELEVEN_STABILITY", 0.5)
ELEVEN_SIMILARITY = _f("ELEVEN_SIMILARITY", 0.8)
ELEVEN_STYLE    = _f("ELEVEN_STYLE", 0.35)
ELEVEN_SPEED    = _f("ELEVEN_SPEED", 1.0)            # 0.7..1.2, поддерживается v2/v3

# ── СУБТИТРЫ (караоке по словам) ───────────────────────────────────────────────
CAPTION_FONT       = _opt("CAPTION_FONT", "Montserrat ExtraBold")
FONTS_DIR          = _opt("FONTS_DIR", os.path.join(ROOT, "assets", "fonts"))
CAPTION_CASE       = _opt("CAPTION_CASE", "lower")   # lower | upper | as_is
CAPTION_SIZE_RATIO = _f("CAPTION_SIZE_RATIO", 0.088) # доля высоты кадра (снято с референса)
CAPTION_MARGIN_V   = _f("CAPTION_MARGIN_V", 0.225)   # подъём над низом (доля высоты)
CAPTION_OUTLINE_RATIO = _f("CAPTION_OUTLINE_RATIO", 0.045)  # обводка = доля кегля
CAPTION_SHADOW     = _f("CAPTION_SHADOW", 0.0)
CAPTION_MIN_SEC    = _f("CAPTION_MIN_SEC", 0.30)     # короткие слова клеим к соседу
CAPTION_MAX_WORDS  = _i("CAPTION_MAX_WORDS", 2)      # максимум слов в одной плашке
CAPTION_POP        = _b("CAPTION_POP", True)         # лёгкий «пых» масштабом

# ── БРЕНДИНГ / МИКС ────────────────────────────────────────────────────────────
LOGO_PATH      = _opt("LOGO_PATH", os.path.join(ROOT, "assets", "logo.png"))
LOGO_ENABLED   = _b("LOGO_ENABLED", False)           # у референса лого нет
LOGO_WIDTH_PCT = _f("LOGO_WIDTH_PCT", 0.28)
MUSIC_PATH     = _opt("MUSIC_PATH", "")              # mp3 подложки; пусто = без музыки
MUSIC_VOLUME   = _f("MUSIC_VOLUME", 0.16)
ENDCARD_ENABLED = _b("ENDCARD_ENABLED", False)
ENDCARD_SEC     = _f("ENDCARD_SEC", 2.0)
ENDCARD_BG      = _opt("ENDCARD_BG", "0x120A2E")
XFADE_SEC       = _f("XFADE_SEC", 0.0)               # 0 = жёсткие склейки (как в референсе)

# ── ПРОЧЕЕ ─────────────────────────────────────────────────────────────────────
MAX_PARALLEL_JOBS = _i("MAX_PARALLEL_JOBS", 3)
KEEP_WORKDIR      = _b("KEEP_WORKDIR", True)
STYLE_PRESET      = _opt("STYLE_PRESET", "pixel_story")
LANG              = _opt("LANG_DEFAULT", "ru")

# S3/R2 — нужен, только если видеопровайдер откажется принимать data:-URL кадра.
S3_ENDPOINT_URL = _opt("S3_ENDPOINT_URL", "")
S3_BUCKET       = _opt("S3_BUCKET", "")
S3_ACCESS_KEY   = _opt("S3_ACCESS_KEY", "")
S3_SECRET_KEY   = _opt("S3_SECRET_KEY", "")
S3_PUBLIC_BASE  = _opt("S3_PUBLIC_BASE", "")
STORAGE_ENABLED = bool(S3_ENDPOINT_URL and S3_BUCKET and S3_ACCESS_KEY and S3_PUBLIC_BASE)


def planned_shot_count() -> int:
    return max(3, int(round(TARGET_DURATION_SEC / max(SHOT_TARGET_SEC, 1.0))))


def words_per_shot() -> int:
    return max(4, int(round(SHOT_TARGET_SEC * WORDS_PER_SEC)))
