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

import config as C


def _ass(r: int, g: int, b: int, a: int = 0) -> str:
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


WHITE   = _ass(255, 255, 255)
BLACK   = _ass(0, 0, 0)
SHADOW  = _ass(0, 0, 0, 0x50)


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


def _case(text: str) -> str:
    if C.CAPTION_CASE == "upper":
        return text.upper()
    if C.CAPTION_CASE == "lower":
        return text.lower()
    return text


def group_words(words: list[dict], min_sec: float = 0.0,
                max_words: int = 0) -> list[dict]:
    """
    Склеивает слишком короткие слова в одну плашку.
    Группа не пересекает границу шота — иначе слово повисло бы над чужим кадром.
    """
    min_sec = min_sec or C.CAPTION_MIN_SEC
    max_words = max_words or C.CAPTION_MAX_WORDS
    groups: list[dict] = []
    for w in words:
        dur = float(w["end"]) - float(w["start"])
        if (groups
                and groups[-1].get("shot") == w.get("shot")
                and (groups[-1]["end"] - groups[-1]["start"]) < min_sec
                and groups[-1]["n"] < max_words):
            g = groups[-1]
            g["text"] = f"{g['text']} {w['word']}"
            g["end"] = float(w["end"])
            g["n"] += 1
            continue
        if (groups
                and groups[-1].get("shot") == w.get("shot")
                and dur < min_sec
                and groups[-1]["n"] < max_words
                and (float(w["start"]) - groups[-1]["end"]) < 0.12):
            g = groups[-1]
            g["text"] = f"{g['text']} {w['word']}"
            g["end"] = float(w["end"])
            g["n"] += 1
            continue
        groups.append({
            "text": w["word"],
            "start": float(w["start"]),
            "end": float(w["end"]),
            "shot": w.get("shot"),
            "n": 1,
        })
    return groups


# Доля кегля на один символ у Montserrat ExtraBold. Замерено рендером:
# заглавные шире строчных, поэтому коэффициенты разные. Нужно, чтобы прикинуть
# ширину строки ДО рендера и решить, переносить её или уменьшать кегль.
_CHAR_W_UPPER = 0.60
_CHAR_W_LOWER = 0.50


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


def _promo_color() -> str:
    try:
        r, g, b = (int(x) for x in C.PROMO_COLOR.split(",")[:3])
    except Exception:  # noqa: BLE001
        r, g, b = 255, 255, 255
    return _ass(r, g, b)


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
    margin_v = int(video_h * C.CAPTION_MARGIN_V)
    # Обводку держим пропорционально кеглю: иначе при смене размера шрифта
    # текст либо тонет в чёрном, либо теряет читаемость на пёстром кадре.
    outline  = round(fs * C.CAPTION_OUTLINE_RATIO, 1)
    promo_fs = int(video_h * C.PROMO_SIZE_RATIO)
    promo_outline = round(promo_fs * C.CAPTION_OUTLINE_RATIO, 1)
    shadow   = C.CAPTION_SHADOW
    font     = C.CAPTION_FONT

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},{fs},{WHITE},{WHITE},{BLACK},{SHADOW},-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,60,60,{margin_v},1
Style: Hook,{font},{hook_fs},{WHITE},{WHITE},{BLACK},{SHADOW},-1,0,0,0,100,100,0,0,1,{outline},{shadow},8,60,60,{int(video_h*0.17)},1
Style: Promo,{font},{promo_fs},{_promo_color()},{_promo_color()},{BLACK},{SHADOW},-1,0,0,0,100,100,0,0,1,{promo_outline},{shadow},8,50,50,{int(video_h*C.PROMO_MARGIN_V)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []

    # Промо-плашка. Рисуется наложением, а не генерацией, поэтому промокод и
    # домен всегда написаны верно — в отличие от текста, который рисует модель.
    promo = promo or C.PROMO_TEXT
    if promo:
        # Последнее слово кончается раньше ролика на OUTRO_HOLD_SEC — без этого
        # слагаемого плашка гасла за секунду до конца, на самом видном кадре.
        total = (max((float(w["end"]) for w in words), default=5.0)
                 + C.OUTRO_HOLD_SEC + 0.6)
        until = total if C.PROMO_FULL_VIDEO else min(C.PROMO_UNTIL_SEC, total)
        text, pfs = _fit_text(_esc(promo.upper()), video_w, 50, promo_fs, max_lines=3)
        size = f"\\fs{pfs}" if pfs != promo_fs else ""
        lines.append(f"Dialogue: 0,{_ts(0.0)},{_ts(until)},Promo,,0,0,0,,"
                     f"{{\\fad(200,200){size}}}{text}")

    if hook and not promo:
        # Хук и промо оба живут сверху — вместе они наложились бы друг на друга.
        # Промо приоритетнее: оно несёт оффер и висит весь ролик.
        htext, hfs = _fit_text(_esc(_case(hook)), video_w, 60, hook_fs, max_lines=2)
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

        pop = ("{\\fad(30,30)\\t(0,80,\\fscx100\\fscy100)\\fscx86\\fscy86}"
               if C.CAPTION_POP else "{\\fad(30,30)}")
        wtext, wfs = _fit_text(_esc(_case(g["text"])), video_w, 60, fs, max_lines=1)
        wsize = f"{{\\fs{wfs}}}" if wfs != fs else ""
        lines.append(
            f"Dialogue: 1,{_ts(start)},{_ts(end)},Word,,0,0,0,,{pop}{wsize}{wtext}"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    return out_path
