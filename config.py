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
TARGET_DURATION_SEC = _f("TARGET_DURATION_SEC", 36.0)
SHOT_TARGET_SEC     = _f("SHOT_TARGET_SEC", 2.5)
MIN_SHOT_SEC        = _f("MIN_SHOT_SEC", 1.6)
VOICE_TAIL_SEC      = _f("VOICE_TAIL_SEC", 0.22)   # воздух после реплики внутри шота
# Хвост ПОСЛЕ последней реплики: без него ролик обрывается ровно на последнем
# слове, зритель не успевает его дочитать, и концовка ощущается как обрыв связи.
# Это не то же самое, что TARGET_DURATION_SEC: там длина ролика делится на шоты,
# здесь просто держится финальный кадр.
OUTRO_HOLD_SEC      = _f("OUTRO_HOLD_SEC", 1.2)
# Замерено на живых прогонах ElevenLabs multilingual_v2, русский: 15 слов за
# 8.7с ≈ 1.7 слова/сек. Завышенное значение — источник цепочки поломок: реплики
# выходят длиннее шота, шот перерастает потолок клипа видеомодели, и хвост
# добивается замороженным кадром.
WORDS_PER_SEC       = _f("WORDS_PER_SEC", 1.7)

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

# Цепочка кадров: каждый следующий кейфрейм получает референсом не только лист
# персонажа, но и ПРЕДЫДУЩИЙ кадр. Одного листа мало — модель воспроизводит
# лицо примерно, и за десять шотов герой заметно уплывает. Предыдущий кадр
# передаёт ещё и свет, палитру и фактуру, поэтому ролик выглядит снятым одной
# камерой, а не собранным из десяти разных картинок.
# Цена: кейфреймы считаются последовательно, а не параллельно — прогон дольше.
FRAME_CHAIN = _b("FRAME_CHAIN", True)

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

# ГИБРИДНЫЙ РЕЖИМ — главный рычаг цены.
# Видео это ~95% чека ролика, картинки и озвучка — копейки. ANIMATE_RATIO задаёт,
# какая доля шотов идёт через видеомодель; остальные оживляются медленным зумом
# из кейфрейма (Ken Burns) бесплатно.
#
# На шоте в 4 секунды с крупным словом поверх разница между слабым движением
# модели и аккуратным зумом почти не читается — поэтому 0.5 экономит половину
# бюджета, почти не трогая ощущение от ролика. 1.0 = всё через модель.
ANIMATE_RATIO = _f("ANIMATE_RATIO", 1.0)

# ── ОЗВУЧКА ────────────────────────────────────────────────────────────────────
# VOICE_ENABLED=false → ролик собирается БЕЗ голоса: только субтитры и музыка.
# Тайминги слов тогда считаются из длины текста (ровный ритм вместо живого),
# всё остальное в конвейере не меняется — потом включаешь голос и пересобираешь.
VOICE_ENABLED   = _b("VOICE_ENABLED", True)

# КАК синтезировать речь. Это решает судьбу интонации:
#   whole    — ВЕСЬ текст одним запросом, границы шотов берутся из пословных
#              таймкодов. Интонация непрерывная, как у живого рассказчика.
#   per_shot — каждый шот отдельным запросом. ElevenLabs на каждом вызове
#              ставит финальную интонацию и паузу, поэтому речь звучит как
#              набор оборванных фраз. Оставлено только для отладки.
VOICE_MODE      = _opt("VOICE_MODE", "whole")

# Своя готовая озвучка: путь к mp3/wav. Тогда TTS не вызывается, а тайминги
# слов снимаются с этого файла через forced alignment ElevenLabs — субтитры
# и нарезка шотов подстраиваются под ЖИВУЮ речь.
VOICE_FILE      = _opt("VOICE_FILE", "")

# Готовый текст озвучки прямо в переменной — самый быстрый способ задать речь
# самому, без коммита файла в репозиторий. Текст не переписывается ни на слово:
# LLM получает его уже разбитым на шоты и придумывает только картинку.
# Приоритет: NARRATION_TEXT → NARRATION_FILE → SCRIPT_FILE → TOPIC.
NARRATION_TEXT  = _opt("NARRATION_TEXT", "")

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
HOOK_SIZE_RATIO    = _f("HOOK_SIZE_RATIO", 0.050)    # хук сверху — заметно мельче слова
CAPTION_MARGIN_V   = _f("CAPTION_MARGIN_V", 0.225)   # подъём над низом (доля высоты)
CAPTION_OUTLINE_RATIO = _f("CAPTION_OUTLINE_RATIO", 0.045)  # обводка = доля кегля
CAPTION_SHADOW     = _f("CAPTION_SHADOW", 0.0)
CAPTION_MIN_SEC    = _f("CAPTION_MIN_SEC", 0.30)     # короткие слова клеим к соседу
CAPTION_MAX_WORDS  = _i("CAPTION_MAX_WORDS", 2)      # максимум слов в одной плашке
CAPTION_POP        = _b("CAPTION_POP", True)         # лёгкий «пых» масштабом

# Акцент на ключевом слове шота (год, число, имя). Глаз цепляется за смену
# цвета сильнее, чем за смену слова, поэтому подсветка фактов удерживает
# внимание там, где зритель обычно отваливается — в середине ролика.
CAPTION_ACCENT       = _b("CAPTION_ACCENT", True)
CAPTION_ACCENT_COLOR = _opt("CAPTION_ACCENT_COLOR", "255,214,64")   # тёплый жёлтый

# ── БРЕНД В КАДРЕ ──────────────────────────────────────────────────────────────
# Два независимых слоя, и это принципиально:
#
#   1) НАТИВНЫЙ ПЛЕЙСМЕНТ — имя бренда рисует картиночная модель прямо в сцене
#      (вывеска, бочка, банка, борт, афиша). Выглядит органично, НО модели врут
#      в буквах: часть кадров придёт с опечаткой. Это надо принимать и отбирать.
#
#   2) ПРОМО-ПЛАШКА — текст накладывается ffmpeg'ом поверх готового видео.
#      Опечаток не бывает никогда. Сюда идёт всё, что обязано быть точным:
#      промокод, оффер, домен.
#
# Правило: то, что должно быть буквально точным — в плашку. То, что создаёт
# ощущение присутствия бренда в мире — в плейсмент.
BRAND_NAME       = _opt("BRAND_NAME", "")            # пусто = без плейсмента
BRAND_PLACEMENT  = _opt("BRAND_PLACEMENT", "native") # native | hero | off
BRAND_SHOT_RATIO = _f("BRAND_SHOT_RATIO", 0.6)       # доля шотов с брендом

# Слоган на вывеске В ВЕРХНЕЙ части кадра — сообщение, а не просто имя.
# ЖЁСТКОЕ ограничение жанра: чем длиннее строка, тем больше опечаток рисует
# модель. Одно слово выходит почти всегда, три коротких — часто, фраза из пяти
# русских слов — почти никогда. Латиница и цифры держатся заметно лучше
# кириллицы, потому что их в обучающих данных вывесок на порядок больше.
# Поэтому: до трёх слов, лучше латиницей, всё критичное — в PROMO_TEXT.
BRAND_TAGLINE       = _opt("BRAND_TAGLINE", "")      # напр. "MIN DEP 1 USDT"
BRAND_TAGLINE_RATIO = _f("BRAND_TAGLINE_RATIO", 0.35)  # доля шотов со слоганом

# Промо-плашка сверху (наложение ffmpeg, не генерация) — главный носитель
# сообщения. Опечаток здесь не бывает никогда, поэтому именно сюда идёт всё,
# что обязано быть буквально точным.
PROMO_TEXT       = _opt("PROMO_TEXT", "")            # пусто = плашки нет

# Пул фраз через «;» — на каждый ролик берётся случайная. Ротация нужна, чтобы
# лента одного аккаунта не выглядела одним и тем же баннером на всех роликах.
# Внутри фразы «|» по-прежнему означает принудительный перенос строки.
PROMO_TEXTS      = _opt("PROMO_TEXTS", "")
PROMO_MAX_LINES  = _i("PROMO_MAX_LINES", 3)
PROMO_SIZE_RATIO = _f("PROMO_SIZE_RATIO", 0.058)
PROMO_MARGIN_V   = _f("PROMO_MARGIN_V", 0.055)       # отступ сверху
PROMO_COLOR      = _opt("PROMO_COLOR", "255,255,255")
PROMO_FULL_VIDEO = _b("PROMO_FULL_VIDEO", True)      # висит весь ролик
PROMO_UNTIL_SEC  = _f("PROMO_UNTIL_SEC", 4.0)        # если не весь ролик

# ── БРЕНДИНГ / МИКС ────────────────────────────────────────────────────────────
LOGO_PATH      = _opt("LOGO_PATH", os.path.join(ROOT, "assets", "logo.png"))
LOGO_ENABLED   = _b("LOGO_ENABLED", False)           # у референса лого нет
LOGO_WIDTH_PCT = _f("LOGO_WIDTH_PCT", 0.28)
MUSIC_PATH     = _opt("MUSIC_PATH", "")              # mp3 подложки; пусто = без музыки
MUSIC_DIR      = _opt("MUSIC_DIR", "")               # папка с треками, берётся случайный
# Целевая громкость подложки в LUFS. Речь нормализуется к -16, поэтому -28
# ставит подложку примерно на 10 дБ ниже речи — отчётливо слышно, но не мешает.
# Замерено: -20 дает 6 дБ (громко), -28 дает 14 дБ (на грани слышимости).
#
# Почему не множитель: MUSIC_VOLUME умножал громкость ИСХОДНОГО файла, а треки
# приходят с разной записанной громкостью. Тихий mp3 оставался неслышным при
# любом коэффициенте, громкий забивал речь. Нормализация делает результат
# одинаковым независимо от того, что положили в папку.
MUSIC_LUFS     = _f("MUSIC_LUFS", -24.0)
MUSIC_VOLUME   = _f("MUSIC_VOLUME", 1.0)             # тонкая подстройка поверх

# Приглушение музыки под речь (ducking). Компрессор с боковой цепью давит
# подложку ровно тогда, когда звучит голос, и отпускает в паузах. Без него
# приходится выбирать: либо музыка глушит речь, либо её почти не слышно —
# фиксированная громкость не может быть правильной одновременно и там, и там.
MUSIC_DUCKING  = _b("MUSIC_DUCKING", True)
# Замерено на тестовом сигнале: ratio=3 при threshold=0.08 даёт ~8 дБ
# приглушения. Это тот диапазон, где музыка уходит на второй план, но не
# исчезает: при ratio=8 проседание доходит до 18 дБ и подложка просто пропадает
# под каждой фразой, что слышно как дыры в фонограмме.
MUSIC_DUCK_RATIO     = _f("MUSIC_DUCK_RATIO", 3.0)
MUSIC_DUCK_THRESHOLD = _f("MUSIC_DUCK_THRESHOLD", 0.08)
MUSIC_FADE_SEC = _f("MUSIC_FADE_SEC", 1.2)           # плавный вход и выход
ENDCARD_ENABLED = _b("ENDCARD_ENABLED", False)
ENDCARD_SEC     = _f("ENDCARD_SEC", 2.0)
ENDCARD_BG      = _opt("ENDCARD_BG", "0x120A2E")
# Срезать однотонные поля, если провайдер отдал кадр не в той пропорции.
AUTOCROP_BARS   = _b("AUTOCROP_BARS", True)
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
