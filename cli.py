#!/usr/bin/env python3
"""
cli.py — единственная точка входа. Airtable/Telegram не нужны.

Подкоманды:
  doctor      Проверка окружения: ffmpeg, шрифты, ключи, рендер тестовых субтитров.
              Работает БЕЗ ключей — с этого стоит начинать.
  models      Каталог моделей OpenRouter (подобрать актуальный слаг видеомодели).
  script      Сценарий по теме → JSON (только текстовая модель, дёшево).
  fromtext    Свой текст озвучки → сценарий. Текст не переписывается ни на слово,
              LLM придумывает только картинку к каждой реплике.
  prompts     Печатает ВСЕ промпты по готовому сценарию. Офлайн, без API.
  render      Сценарий (JSON) → mp4. Здесь тратятся деньги.
  make        script + render одной командой.
  captions    Пересобрать субтитры/пережечь по уже отрендеренной рабочей папке.

Примеры:
  python3 cli.py doctor
  python3 cli.py models --filter veo
  python3 cli.py script --topic "история первого крипто-миллионера" --lang ru -o s.json
  python3 cli.py prompts s.json
  python3 cli.py fromtext narration.txt --estimate      # разбивка и цена, без API
  python3 cli.py fromtext narration.txt -o s.json
  python3 cli.py render s.json -o out.mp4
  python3 cli.py make --topic "как появился первый онлайн-казино-джекпот" -o out.mp4
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402


# ── УТИЛИТЫ ────────────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    from story.script_writer import coerce
    return coerce(data)


def _dump(script: dict, path: str = "") -> None:
    text = json.dumps(script, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"→ {path}")
    else:
        print(text)


# ── doctor ─────────────────────────────────────────────────────────────────────

def cmd_doctor(args) -> None:
    import shutil
    import subprocess

    ok = True
    print("── Окружение ──")
    for tool in ("ffmpeg", "ffprobe"):
        p = shutil.which(tool)
        print(f"  {tool:9} {'OK ' + p if p else 'НЕТ — установи ffmpeg'}")
        ok &= bool(p)

    libass = False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True).stdout
        libass = "subtitles" in out
    except Exception:  # noqa: BLE001
        pass
    print(f"  subtitles {'OK (libass)' if libass else 'НЕТ — ffmpeg собран без libass, субтитры не прожгутся'}")
    ok &= libass

    print("\n── Шрифты ──")
    fonts = []
    if os.path.isdir(C.FONTS_DIR):
        fonts = [f for f in os.listdir(C.FONTS_DIR) if f.lower().endswith((".ttf", ".otf"))]
    print(f"  {C.FONTS_DIR}: {', '.join(fonts) if fonts else 'ПУСТО'}")
    print(f"  CAPTION_FONT = {C.CAPTION_FONT!r}")

    print("\n── Ключи ──")
    for k in ("OPENROUTER_API_KEY", "ELEVENLABS_API_KEY", "ELEVEN_VOICE_ID"):
        v = os.environ.get(k) or (C.ELEVEN_VOICE_ID if k == "ELEVEN_VOICE_ID" else "")
        print(f"  {k:20} {'задан' if v else 'НЕ ЗАДАН'}")
    tg = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    print(f"  TELEGRAM (доставка)  {'задан' if tg else 'НЕ ЗАДАН — на Railway ролик будет некуда деть'}")

    # Частая ошибка: в переменную кладут слаг fal (fal-ai/...), а весь клиент
    # ходит в OpenRouter. Запрос вернёт 404, и фолбэк тихо не сработает.
    if C.BRAND_NAME or C.BRAND_TAGLINE:
        print("\n── Бренд в кадре ──")
        print(f"  имя      {C.BRAND_NAME or '—'} (в {C.BRAND_SHOT_RATIO:.0%} шотов)")
        tl = C.BRAND_TAGLINE
        note = ""
        if tl and len(tl) > 18:
            note = f"  ← {len(tl)} знаков,высокий риск опечатки"
        print(f"  слоган   {tl or '—'} (в {C.BRAND_TAGLINE_RATIO:.0%} шотов){note}")
        print(f"  промо    {C.PROMO_TEXT or '—'} (наложение, опечаток не бывает)")

    from story.render import pick_music
    track = pick_music()
    print(f"\n── Музыка ──\n  {track or 'НЕТ — ролик будет без подложки'}")
    if track:
        print(f"  целевая громкость {C.MUSIC_LUFS} LUFS "
              f"(~{abs(C.MUSIC_LUFS + 16):.0f} дБ ниже речи), "
              f"дакинг {'вкл' if C.MUSIC_DUCKING else 'выкл'}")

    print("\n── Слаги моделей ──")
    for name, val in (("VIDEO_MODEL", C.VIDEO_MODEL),
                      ("SECONDARY_VIDEO_MODEL", C.SECONDARY_VIDEO_MODEL),
                      ("IMAGE_MODEL", C.IMAGE_MODEL)):
        bad = val.startswith("fal-ai/") or val.count("/") > 1
        flag = "  ← похоже на слаг fal, а нужен OpenRouter (vendor/model)" if bad else ""
        print(f"  {name:22} {val}{flag}")
        ok &= not bad
    print("  сверить актуальные: python3 cli.py models --filter veo")

    print("\n── План ролика ──")
    print(f"  {C.TARGET_DURATION_SEC:.0f}с / {C.SHOT_TARGET_SEC:.1f}с на шот "
          f"= {C.planned_shot_count()} шотов, ~{C.words_per_shot()} слов на шот")
    print(f"  кадр {C.VIDEO_W}x{C.VIDEO_H} @{C.FPS}fps, стиль {C.STYLE_PRESET}")
    if C.VOICE_FILE:
        mode = f"свой файл {os.path.basename(C.VOICE_FILE)} (forced alignment)"
    elif not C.VOICE_ENABLED:
        mode = "ВЫКЛЮЧЕНА (субтитры + музыка)"
    elif C.VOICE_MODE == "whole":
        mode = "ElevenLabs, весь текст одним запросом"
    else:
        mode = "ElevenLabs, по шоту за запрос — речь будет рваной"
    print(f"  озвучка: {mode}")
    if C.NARRATION_TEXT:
        src = f"NARRATION_TEXT ({len(C.NARRATION_TEXT)} знаков)"
    elif os.environ.get("NARRATION_FILE"):
        src = f"файл {os.environ['NARRATION_FILE']}"
    elif os.environ.get("SCRIPT_FILE"):
        src = f"сценарий {os.environ['SCRIPT_FILE']}"
    else:
        src = "генерируется LLM из TOPIC"
    print(f"  текст:   {src}")
    print(f"  видеомодель {C.VIDEO_MODEL} (фолбэк {C.SECONDARY_VIDEO_MODEL})")

    if args.render_test and ok:
        print("\n── Тестовый рендер субтитров (без API) ──")
        _caption_smoke(args.out or "doctor_captions.mp4")

    print("\nГотов." if ok else "\nЕсть проблемы — см. выше.")


def _caption_smoke(out_path: str) -> None:
    """Прожигает тестовые русские субтитры на цветной фон — проверка шрифта/libass."""
    import tempfile

    from story import captions
    from story.media import run_ff

    demo = "он начинал в 1994 году в подвале с одним микрофоном"
    words, t = [], 0.0
    for w in demo.split():
        d = 0.28 + 0.035 * len(w)
        words.append({"word": w, "start": t, "end": t + d, "shot": 0})
        t += d

    wd = tempfile.mkdtemp(prefix="capsmoke_")
    ass = captions.build_ass(words, os.path.join(wd, "c.ass"), hook="проверка шрифта")
    ass_arg = ass.replace(":", "\\:")
    fonts = C.FONTS_DIR.replace(":", "\\:")
    run_ff([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=0x1B2430:s={C.VIDEO_W}x{C.VIDEO_H}:r={C.FPS}:d={t + 0.5:.2f}",
        "-vf", f"subtitles='{ass_arg}':fontsdir='{fonts}'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", out_path,
    ], label="capsmoke")
    print(f"  → {out_path}  (открой и проверь, что кириллица не квадратами)")


# ── models ─────────────────────────────────────────────────────────────────────

def cmd_models(args) -> None:
    from story import orclient
    items = orclient.list_models(args.filter)
    if not items:
        print("Ничего не найдено. Попробуй другой --filter (veo / seedance / kling / image).")
        return
    for m in items[:args.limit]:
        arch = m.get("architecture") or {}
        out = ",".join(arch.get("output_modalities") or [])
        pr = m.get("pricing") or {}
        price = pr.get("video") or pr.get("image") or pr.get("prompt") or "?"
        print(f"{m.get('id'):48} out={out:12} price={price}")
    print("\nПодставь нужный слаг в VIDEO_MODEL (.env).")


# ── script ─────────────────────────────────────────────────────────────────────

def cmd_script(args) -> None:
    from story.script_writer import estimate_duration, write_script
    script = write_script(
        topic=args.topic, language=args.lang, shots=args.shots,
        words=args.words, extra=args.extra, vertical=args.vertical, model=args.model,
    )
    if args.style:
        script["style_preset"] = args.style
    print(f"\n~{estimate_duration(script):.1f}с по тексту, {len(script['shots'])} шотов\n",
          file=sys.stderr)
    _dump(script, args.out)


# ── fromtext ───────────────────────────────────────────────────────────────────

def cmd_fromtext(args) -> None:
    from story import from_text

    if args.textfile == "-":
        raw = C.NARRATION_TEXT or sys.stdin.read()
    else:
        with open(args.textfile, encoding="utf-8") as f:
            raw = f.read()
    raw = raw.replace("\\n", "\n")
    # Строки, начинающиеся с #, — комментарии: удобно держать в файле пометки
    raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("#"))

    if args.estimate:
        est = from_text.estimate(raw, args.words)
        print(f"Шотов:        {est['shots']}")
        print(f"Слов:         {est['words']}")
        print(f"Длина ролика: ~{est['seconds']}с")
        print(f"Через модель: {est['animated_shots']} шотов "
              f"= {est['video_seconds']}с видео (ANIMATE_RATIO={C.ANIMATE_RATIO})")
        print(f"Примерно:     ~${est['cost_total']} "
              f"(картинки ${est['cost_images']} + видео ${est['cost_video']})")
        if est["shots"] > 16:
            print(f"\n! {est['shots']} шотов — это дорого. Увеличь --words "
                  f"или SHOT_TARGET_SEC, чтобы реплики были длиннее, "
                  f"либо сократи текст.")
        print("\nРазбивка по шотам:")
        for i, line in enumerate(est["lines"], 1):
            print(f"{i:3}. ({len(line.split())} сл.) {line}")
        return

    script = from_text.script_from_text(
        raw, language=args.lang, hook=args.hook, extra=args.extra,
        words_per_shot=args.words, model=args.model)
    if args.style:
        script["style_preset"] = args.style
    _dump(script, args.out)


# ── prompts ────────────────────────────────────────────────────────────────────

def cmd_prompts(args) -> None:
    from story.prompts import (
        build_character_ref_prompt, build_keyframe_prompt, build_motion_prompt,
    )
    from story.script_writer import estimate_duration

    s = _load(args.script)
    preset = s.get("style_preset", C.STYLE_PRESET)
    print(f"=== {s['title']} | {s['language']} | стиль {preset} ===")
    print(f"хук: {s['hook']!r}")
    print(f"оценка длины: {estimate_duration(s):.1f}с, шотов {len(s['shots'])}\n")
    print("── РЕФЕРЕНС ПЕРСОНАЖА ──")
    print(build_character_ref_prompt(s["character"], s.get("world", ""), preset), "\n")
    for i, shot in enumerate(s["shots"]):
        print(f"── ШОТ {i} [{shot.get('beat', '')}] ─────────────────────────")
        print(f"озвучка ({len(shot['narration'].split())} слов): {shot['narration']}")
        print(f"KEYFRAME: {build_keyframe_prompt(shot, s['character'], s.get('world', ''), preset)}")
        print(f"MOTION:   {build_motion_prompt(shot, preset)}\n")


# ── render ─────────────────────────────────────────────────────────────────────

def cmd_render(args) -> None:
    from story.render import render
    if args.voice:
        os.environ["VOICE_FILE"] = args.voice
        C.VOICE_FILE = args.voice
    s = _load(args.script)
    if args.style:
        s["style_preset"] = args.style
    res = render(s, args.out, workdir_base=args.workdir,
                 music_path=args.music, logo_path=args.logo)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_make(args) -> None:
    from story.render import render
    from story.script_writer import write_script
    if args.voice:
        os.environ["VOICE_FILE"] = args.voice
        C.VOICE_FILE = args.voice
    s = write_script(topic=args.topic, language=args.lang, shots=args.shots,
                     words=args.words, extra=args.extra, vertical=args.vertical,
                     model=args.model)
    if args.style:
        s["style_preset"] = args.style
    if args.script_out:
        _dump(s, args.script_out)
    res = render(s, args.out, workdir_base=args.workdir,
                 music_path=args.music, logo_path=args.logo)
    print(json.dumps(res, ensure_ascii=False, indent=2))


# ── captions (пережиг без повторной генерации) ─────────────────────────────────

def cmd_captions(args) -> None:
    """
    Пересобирает субтитры и пережигает финал из УЖЕ существующей рабочей папки.
    Даёт бесплатно крутить размер/позицию/шрифт, не трогая картинки и видео.
    """
    from story import captions as cap
    from story.compose import burn
    from story.media import probe_duration

    wd = args.workdir
    body = os.path.join(wd, "body.mp4")
    voice_wav = os.path.join(wd, "voice_all.wav")
    words_path = os.path.join(wd, "words.json")
    for p in (body, voice_wav, words_path):
        if not os.path.exists(p):
            raise SystemExit(f"Нет {p} — папка не от полного рендера?")
    with open(words_path, encoding="utf-8") as f:
        words = json.load(f)
    with open(os.path.join(wd, "script.json"), encoding="utf-8") as f:
        script = json.load(f)

    ass = cap.build_ass(words, os.path.join(wd, "captions.ass"), hook=script.get("hook", ""))
    burn(body, voice_wav, ass, probe_duration(body), args.out,
         music_path=args.music or C.MUSIC_PATH,
         logo_path=args.logo or (C.LOGO_PATH if C.LOGO_ENABLED else ""))
    print(f"→ {args.out}")


# ── ПАРСЕР ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Story Videos CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="проверка окружения")
    p.add_argument("--render-test", action="store_true", help="прожечь тестовые субтитры")
    p.add_argument("-o", "--out", default="")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("models", help="каталог моделей OpenRouter")
    p.add_argument("--filter", default="", help="подстрока: veo / seedance / image")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_models)

    def _script_args(p):
        p.add_argument("--topic", required=True)
        p.add_argument("--lang", default=C.LANG)
        p.add_argument("--shots", type=int, default=0)
        p.add_argument("--words", type=int, default=0)
        p.add_argument("--extra", default="")
        p.add_argument("--vertical", default="")
        p.add_argument("--model", default="")
        p.add_argument("--style", default="", help="pixel_story | anime_lofi | cinematic_doc")

    p = sub.add_parser("script", help="сценарий → JSON")
    _script_args(p)
    p.add_argument("-o", "--out", default="")
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("fromtext", help="свой текст озвучки → сценарий")
    p.add_argument("textfile",
                   help="txt с текстом озвучки, либо «-» для stdin/NARRATION_TEXT")
    p.add_argument("-o", "--out", default="")
    p.add_argument("--estimate", action="store_true",
                   help="только разбивка и оценка, без вызовов API")
    p.add_argument("--lang", default=C.LANG)
    p.add_argument("--hook", default="", help="текст хука на экране")
    p.add_argument("--extra", default="", help="арт-дирекшн для картинок")
    p.add_argument("--words", type=int, default=0, help="слов на шот")
    p.add_argument("--model", default="")
    p.add_argument("--style", default="")
    p.set_defaults(func=cmd_fromtext)

    p = sub.add_parser("prompts", help="печать всех промптов (офлайн)")
    p.add_argument("script")
    p.set_defaults(func=cmd_prompts)

    def _render_args(p):
        p.add_argument("-o", "--out", default="out.mp4")
        p.add_argument("--workdir", default="work")
        p.add_argument("--music", default="")
        p.add_argument("--logo", default="")
        p.add_argument("--voice", default="",
                       help="свой готовый mp3/wav озвучки; тайминги снимутся с него")

    p = sub.add_parser("render", help="сценарий → mp4")
    p.add_argument("script")
    _render_args(p)
    p.add_argument("--style", default="")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("make", help="сценарий + рендер одной командой")
    _script_args(p)
    _render_args(p)
    p.add_argument("--script-out", default="")
    p.set_defaults(func=cmd_make)

    p = sub.add_parser("captions", help="пережечь субтитры по готовой рабочей папке")
    p.add_argument("workdir")
    p.add_argument("-o", "--out", default="out_recap.mp4")
    p.add_argument("--music", default="")
    p.add_argument("--logo", default="")
    p.set_defaults(func=cmd_captions)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
