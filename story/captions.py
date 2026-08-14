"""
story/captions.py — караоке-субтитры (ASS/libass) в стиле референса:
одно слово за раз, крупно, нижняя треть, белый текст с толстой чёрной обводкой.

Две неочевидные вещи:
  1. Цвет в ASS — &HAABBGGRR (alpha-blue-green-red), а НЕ RGB. Хелпер _ass()
     переставляет байты; без него «красный» отрендерится синим.
  2. Слишком короткие слова («и», «в») мигают на экране быстрее, чем глаз их
     ловит, — поэтому склеиваем их с соседним словом в одну плашку
     (CAPTION_MIN_SEC / CAPTION_MAX_WORDS). В референсе так же: «1994 году».
"""

from __future__ import annotations

import random

import config as C


def _ass(r: int, g: int, b: int, a: int = 0) -> str:
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


WHITE   = _ass(255, 255, 255)
BLACK   = _ass(0, 0, 0)
SHADOW  = _ass(0, 0, 0, 0x50)


def _word_style_params(outline: float) -> tuple[int, float, float, str]:
    """
    (BorderStyle, Outline, Shadow, BackColour) под выбранное оформление.

    BorderStyle=1 — обводка вокруг глифов, =3 — заливка прямоугольником позади
    текста; во втором случае Outline работает как внутренний отступ подложки.
    """
    if C.CAPTION_STYLE == "box":
        return 3, round(outline * 0.45, 1), 0.0, _ass(0, 0, 0, C.CAPTION_BOX_ALPHA)
    if C.CAPTION_STYLE == "glow":
        # Обводка тоньше, но добавлена мягкая тень — контур не «жирнеет»,
        # а текст всё равно отделяется от любого фона.
        return 1, round(outline * 0.72, 1), round(outline * 0.5, 1), _ass(0, 0, 0, 0x60)
    return 1, outline, C.CAPTION_SHADOW, SHADOW


def _ts(t: float) -> str:
    """Секунды → H:MM:SS.cc"""
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    """Экранирует символы, ломающие override-блоки ASS."""
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


# Пунктуация в караоке-плашке — чистый мусор: точка или запятая висят рядом с
# одним словом без всякого смысла, а из таймкодов они приходят почти в каждом
# токене. Дефис внутри слова оставляем: «спейс-икс» это одно слово.
_PUNCT = ".,!?;:…\"'«»„“”()[]{}"


def _strip_punct(text: str) -> str:
    return text.strip(_PUNCT).replace(",,", ",").strip(_PUNCT)


def _keep_case(word: str) -> bool:
    """
    Аббревиатуры и римские цифры регистр не меняют.

    Без этого «World War II» превращается в «war ii», а «BTC» в «btc» — то есть
    в нечитаемый мусор. Признак: слово целиком в верхнем регистре и короткое,
    либо содержит цифры.
    """
    core = word.strip(_PUNCT)
    if not core:
        return False
    if any(ch.isdigit() for ch in core):
        return True
    return core.isupper() and len(core) <= 4


def _case(text: str, sentence_start: bool = False) -> str:
    """
    Регистр плашки.

    sentence — единственный режим, который различает три случая: начало
    предложения, имя собственное и обычное слово. Имена определяются по
    заглавной букве В ИСХОДНОМ тексте: «Ada», «Babbage», «Bernoulli» приходят
    из таймкодов уже с большой буквы, и достаточно их не трогать. Всё
    остальное опускается, как в референсе.
    """
    if C.CAPTION_CASE == "as_is":
        return text

    out = []
    for i, w in enumerate(text.split()):
        if _keep_case(w):                      # аббревиатуры, римские цифры, числа
            out.append(w)
        elif C.CAPTION_CASE == "upper":
            out.append(w.upper())
        elif C.CAPTION_CASE == "sentence":
            if w[:1].isupper():                # имя собственное или начало фразы
                out.append(w)
            elif i == 0 and sentence_start:    # источник поленился — поднимаем сами
                out.append(w[:1].upper() + w[1:])
            else:
                out.append(w.lower())
        else:
            out.append(w.lower())
    return " ".join(out)


_SENT_END = ".!?…"


def group_words(words: list[dict], min_sec: float = 0.0,
                max_words: int = 0) -> list[dict]:
    """
    Склеивает слишком короткие слова в одну плашку.
    Группа не пересекает границу шота — иначе слово повисло бы над чужим кадром.
    """
    min_sec = min_sec or C.CAPTION_MIN_SEC
    max_words = max_words or C.CAPTION_MAX_WORDS
    groups: list[dict] = []
    # Признак начала предложения снимаем с ИСХОДНОГО токена: пунктуация из
    # плашек вырезается, и после этого понять, где кончилась фраза, уже нельзя.
    new_sentence = True
    for w in words:
        dur = float(w["end"]) - float(w["start"])
        raw = str(w["word"])
        starts_sentence = new_sentence
        new_sentence = raw.rstrip('")\'»').endswith(tuple(_SENT_END))
        if (groups
                and groups[-1].get("shot") == w.get("shot")
                and (groups[-1]["end"] - groups[-1]["start"]) < min_sec
                and groups[-1]["n"] < max_words):
            g = groups[-1]
            g["text"] = f"{g['text']} {_strip_punct(w['word'])}".strip()
            g["end"] = float(w["end"])
            g["accent"] = g.get("accent") or bool(w.get("accent"))
            g["n"] += 1
            continue
        if (groups
                and groups[-1].get("shot") == w.get("shot")
                and dur < min_sec
                and groups[-1]["n"] < max_words
                and (float(w["start"]) - groups[-1]["end"]) < 0.12):
            g = groups[-1]
            g["text"] = f"{g['text']} {_strip_punct(w['word'])}".strip()
            g["end"] = float(w["end"])
            g["accent"] = g.get("accent") or bool(w.get("accent"))
            g["n"] += 1
            continue
        groups.append({
            "text": _strip_punct(w["word"]),
            "start": float(w["start"]),
            "end": float(w["end"]),
            "shot": w.get("shot"),
            "accent": bool(w.get("accent")),
            "sentence_start": starts_sentence,
            "n": 1,
        })
    return [g for g in groups if g["text"].strip()]


# Доля кегля на один символ у Montserrat ExtraBold. Замерено рендером на
# кириллице и латинице: заглавные ~0.46, строчные ~0.41. Небольшой запас сверху
# оставлен на пунктуацию и широкие буквы вроде Ш и Ж.
# Коэффициенты нужны, чтобы прикинуть ширину строки ДО рендера и решить,
# переносить её или уменьшать кегль. Завышать их нельзя: текст выйдет мельче,
# чем мог бы, и плашка перестанет читаться с телефона.
_CHAR_W_UPPER = 0.48
_CHAR_W_LOWER = 0.43


def _wrap(text: str, max_chars: int) -> list[str]:
    """Разбивает по словам на строки не длиннее max_chars."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [text]


def _fit_text(text: str, video_w: int, margin: int, fs: int,
              max_lines: int = 2, min_fs: int = 0) -> tuple[str, int]:
    """
    Вписывает текст в ширину кадра: сначала переносами, потом уменьшением кегля.

    Без этого длинный хук просто уезжал за границы кадра и обрезался с обеих
    сторон — libass не переносит строки сам, если в заголовке WrapStyle=2,
    а даже с переносом слишком крупный кегль не влезает.
    """
    min_fs = min_fs or int(fs * 0.55)
    usable = max(video_w - 2 * margin, 100)
    explicit = [p.strip() for p in text.split("|")] if "|" in text else None

    while True:
        char_w = _CHAR_W_UPPER if text == text.upper() else _CHAR_W_LOWER
        max_chars = max(int(usable / (fs * char_w)), 4)
        lines = explicit if explicit else _wrap(text, max_chars)
        too_wide = any(len(l) > max_chars for l in lines)
        if (len(lines) <= max_lines and not too_wide) or fs <= min_fs:
            return "\\N".join(lines), fs
        fs = int(fs * 0.92)


def pick_promo() -> str:
    """
    Фраза для верхней плашки: явный PROMO_TEXT, иначе случайная из пула
    PROMO_TEXTS. Пул разделяется «;», внутри фразы «|» — перенос строки.
    """
    if C.PROMO_TEXT.strip():
        return C.PROMO_TEXT.strip()
    pool = [p.strip() for p in C.PROMO_TEXTS.split(";") if p.strip()]
    return random.choice(pool) if pool else ""


def _accent_color() -> str:
    try:
        r, g, b = (int(x) for x in C.CAPTION_ACCENT_COLOR.split(",")[:3])
    except Exception:  # noqa: BLE001
        r, g, b = 255, 214, 64
    return _ass(r, g, b)


def _promo_color() -> str:
    try:
        r, g, b = (int(x) for x in C.PROMO_COLOR.split(",")[:3])
    except Exception:  # noqa: BLE001
        r, g, b = 255, 255, 255
    # В ASS альфа инвертирована: 0x00 — непрозрачно, 0xFF — полностью прозрачно.
    # Полупрозрачная подпись меньше похожа на вставленный рекламный баннер.
    alpha = int(round((1.0 - max(0.0, min(1.0, C.PROMO_OPACITY))) * 255))
    return _ass(r, g, b, alpha)


def build_ass(words: list[dict], out_path: str, video_w: int = 0, video_h: int = 0,
              hook: str = "", hook_until: float = 2.0, promo: str = "") -> str:
    """
    words: [{word, start, end, shot?}] в глобальных секундах ролика.
    Возвращает путь к .ass.
    """
    video_w = video_w or C.VIDEO_W
    video_h = video_h or C.VIDEO_H

    fs       = int(video_h * C.CAPTION_SIZE_RATIO)
    hook_fs  = int(video_h * C.HOOK_SIZE_RATIO)
    # Alignment в ASS: 2 — низ по центру (отступ MarginV снизу),
    # 5 — вертикально по центру кадра, и тогда MarginV не используется.
    if C.CAPTION_POSITION == "center":
        w_align, margin_v = 5, 0
    else:
        w_align, margin_v = 2, int(video_h * C.CAPTION_MARGIN_V)
    # Обводку держим пропорционально кеглю: иначе при смене размера шрифта
    # текст либо тонет в чёрном, либо теряет читаемость на пёстром кадре.
    outline  = round(fs * C.CAPTION_OUTLINE_RATIO, 1)

    # Геометрия промо-плашки зависит от режима подачи. Крупный баннер поверх
    # кадра площадки читают как рекламную вставку, поэтому native/corner делают
    # надпись мельче, полупрозрачной и уводят её вниз, где она выглядит подписью
    # к ролику, а не наложенным объявлением.
    if C.PROMO_STYLE == "banner":
        promo_fs = int(video_h * C.PROMO_SIZE_RATIO)
        promo_align = 8                                   # верх по центру
        promo_margin = int(video_h * C.PROMO_MARGIN_V)
    elif C.PROMO_STYLE == "corner":
        promo_fs = int(video_h * C.PROMO_SIZE_RATIO * 0.48)
        promo_align = 7                                   # верхний левый угол
        promo_margin = int(video_h * 0.035)
    else:                                                  # native
        promo_fs = int(video_h * C.PROMO_SIZE_RATIO * 0.60)
        promo_align = 2                                   # низ по центру
        # Ниже субтитров: они сидят на CAPTION_MARGIN_V, и подпись не должна
        # налезать на них — иначе два слоя текста сливаются в кашу.
        promo_margin = int(video_h * 0.030)

    promo_outline = round(promo_fs * C.CAPTION_OUTLINE_RATIO, 1)
    shadow   = C.CAPTION_SHADOW
    font     = C.CAPTION_FONT

    w_border, w_outline, w_shadow, w_back = _word_style_params(outline)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},{fs},{WHITE},{WHITE},{BLACK},{w_back},-1,0,0,0,100,100,0,0,{w_border},{w_outline},{w_shadow},{w_align},60,60,{margin_v},1
Style: Hook,{font},{hook_fs},{WHITE},{WHITE},{BLACK},{SHADOW},-1,0,0,0,100,100,0,0,1,{outline},{shadow},8,60,60,{int(video_h*0.17)},1
Style: Promo,{font},{promo_fs},{_promo_color()},{_promo_color()},{BLACK},{SHADOW},-1,0,0,0,100,100,0,0,1,{promo_outline},{shadow},{promo_align},50,50,{promo_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []

    # Промо-плашка. Рисуется наложением, а не генерацией, поэтому промокод и
    # домен всегда написаны верно — в отличие от текста, который рисует модель.
    promo = promo or pick_promo()
    if promo:
        # Последнее слово кончается раньше ролика на OUTRO_HOLD_SEC — без этого
        # слагаемого плашка гасла за секунду до конца, на самом видном кадре.
        total = (max((float(w["end"]) for w in words), default=5.0)
                 + C.OUTRO_HOLD_SEC + 0.6)
        until = total if C.PROMO_FULL_VIDEO else min(C.PROMO_UNTIL_SEC, total)
        text, pfs = _fit_text(_esc(promo.upper()), video_w, 40, promo_fs,
                              max_lines=C.PROMO_MAX_LINES)
        size = f"\\fs{pfs}" if pfs != promo_fs else ""
        lines.append(f"Dialogue: 0,{_ts(0.0)},{_ts(until)},Promo,,0,0,0,,"
                     f"{{\\fad(200,200){size}}}{text}")

    if hook and not promo:
        # Хук и промо оба живут сверху — вместе они наложились бы друг на друга.
        # Промо приоритетнее: оно несёт оффер и висит весь ролик.
        htext, hfs = _fit_text(_esc(_case(hook, True)), video_w, 60, hook_fs, max_lines=2)
        hsize = f"\\fs{hfs}" if hfs != hook_fs else ""
        lines.append(
            f"Dialogue: 0,{_ts(0.05)},{_ts(hook_until)},Hook,,0,0,0,,"
            f"{{\\fad(120,120){hsize}}}{htext}"
        )

    groups = group_words(words)
    n = len(groups)
    for i, g in enumerate(groups):
        start = g["start"]
        # Тянем плашку до начала следующей — иначе между словами моргает пустота.
        if i + 1 < n:
            nxt = groups[i + 1]["start"]
            end = nxt if nxt > start else g["end"] + 0.12
            # но не даём слову залезть в следующий шот больше чем на кадр
            if groups[i + 1].get("shot") != g.get("shot"):
                end = min(end, g["end"] + 0.20)
        else:
            end = g["end"] + 0.20
        if end <= start:
            end = start + 0.12

        # Появление: слово выскакивает из 88% в 104% и оседает в 100%.
        # Лёгкий перелёт читается как «щелчок» и заметен боковым зрением —
        # именно он держит взгляд на плашке при быстрой смене слов.
        pop = ("{\\fad(25,25)\\fscx88\\fscy88"
               "\\t(0,70,\\fscx104\\fscy104)\\t(70,130,\\fscx100\\fscy100)}"
               if C.CAPTION_POP else "{\\fad(25,25)}")
        wtext, wfs = _fit_text(_esc(_case(g["text"], g.get("sentence_start", False))),
                               video_w, 60, fs, max_lines=1)
        wsize = f"\\fs{wfs}" if wfs != fs else ""
        # Ключевое слово шота красим: смена цвета цепляет глаз сильнее, чем
        # очередная смена слова, и держит внимание в середине ролика.
        wcol = (f"\\c{_accent_color()}"
                if (C.CAPTION_ACCENT and g.get("accent")) else "")
        override = f"{{{wsize}{wcol}}}" if (wsize or wcol) else ""
        lines.append(
            f"Dialogue: 1,{_ts(start)},{_ts(end)},Word,,0,0,0,,{pop}{override}{wtext}"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    return out_path
