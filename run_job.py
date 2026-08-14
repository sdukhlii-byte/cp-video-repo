#!/usr/bin/env python3
"""
run_job.py — одноразовый прогон для Railway: тема из переменной → ролик → Telegram.

Контейнер поднимается, делает ОДИН ролик и завершается. Это не сервер:
ни порта, ни домена, ни health-check. Запуск — вручную (Redeploy) или по
расписанию (Settings → Cron Schedule).

Переменные окружения:
  NARRATION_TEXT  текст озвучки ПРЯМО В ПЕРЕМЕННОЙ — вставил в Railway и всё.
               Текст не переписывается, LLM придумывает только картинку.
  NARRATION_FILE  то же самое, но текст лежит файлом в репозитории. Текст не переписывается,
               LLM придумывает только картинку к каждой реплике.
  SCRIPT_FILE  путь к утверждённому сценарию (JSON) — тогда TOPIC игнорируется
               и LLM не вызывается вообще. Это способ получить ПРЕДСКАЗУЕМЫЙ
               ролик: правишь JSON руками, коммитишь, рендеришь сколько нужно.
  TOPIC        тема ролика, если сценарий генерируется на лету
  TOPICS       несколько тем через «|», берётся случайная — для крона,
               чтобы не постить одно и то же
  DRY_RUN      1 = только сценарий, без картинок/видео/денег (проверка ключей)
  плюс всё из .env.example
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("job")

import config as C  # noqa: E402
from story import deliver  # noqa: E402


def pick_topic() -> str:
    topics = os.environ.get("TOPICS", "").strip()
    if topics:
        options = [t.strip() for t in topics.split("|") if t.strip()]
        if options:
            return random.choice(options)
    topic = os.environ.get("TOPIC", "").strip()
    if not topic:
        raise SystemExit("Не задана переменная TOPIC (или TOPICS через «|»)")
    return topic


def _build_from_text(from_text, raw: str) -> dict:
    """
    Сценарий из своего текста. При SPLIT_BY_TIMING режем по реальному звучанию —
    тогда длина шота не зависит от того, насколько быстро говорит голос.
    """
    kw = dict(language=C.LANG, hook=os.environ.get("HOOK", ""),
              extra=os.environ.get("EXTRA_DIRECTION", ""))
    if C.SPLIT_BY_TIMING and C.VOICE_ENABLED and not C.VOICE_FILE:
        try:
            return from_text.script_from_text_timed(raw, "work/presynth", **kw)
        except Exception as e:  # noqa: BLE001
            log.warning("Нарезка по звучанию не удалась (%s) — считаю по словам",
                        str(e)[:160])
    return from_text.script_from_text(raw, **kw)


def main() -> None:
    from story.script_writer import coerce, estimate_duration, write_script

    narration_text = C.NARRATION_TEXT.strip()
    narration_file = os.environ.get("NARRATION_FILE", "").strip()
    script_file = os.environ.get("SCRIPT_FILE", "").strip()

    if narration_text:
        # Railway хранит перевод строки как есть, но при вставке из редактора
        # он иногда приезжает экранированным — разворачиваем оба варианта.
        raw = narration_text.replace("\\n", "\n")
        raw = "\n".join(l for l in raw.splitlines()
                         if not l.strip().startswith("#"))
        from story import from_text
        script = _build_from_text(from_text, raw)
        topic = "текст из NARRATION_TEXT"
        log.info("Сценарий из переменной NARRATION_TEXT (%d знаков)", len(raw))
    elif narration_file:
        # Свой текст: авторская интонация и порядок фактов сохраняются дословно.
        if not os.path.exists(narration_file):
            raise SystemExit(f"NARRATION_FILE={narration_file} не найден")
        from story import from_text
        with open(narration_file, encoding="utf-8") as f:
            raw = "\n".join(l for l in f.read().splitlines()
                             if not l.strip().startswith("#"))
        script = _build_from_text(from_text, raw)
        topic = f"текст {os.path.basename(narration_file)}"
        log.info("Сценарий из текста: %s", narration_file)
    elif script_file:
        # Готовый сценарий: ни одного вызова LLM, результат воспроизводим.
        # Нужен, когда текст уже проверен глазами и его нельзя переписывать.
        if not os.path.exists(script_file):
            raise SystemExit(f"SCRIPT_FILE={script_file} не найден")
        with open(script_file, encoding="utf-8") as f:
            script = coerce(json.load(f))
        topic = f"файл {os.path.basename(script_file)}"
        log.info("Сценарий из файла: %s", script_file)
    else:
        topic = pick_topic()
        log.info("Тема: %s", topic)
        script = write_script(topic=topic, language=C.LANG,
                              vertical=os.environ.get("VERTICAL", ""),
                              extra=os.environ.get("EXTRA_DIRECTION", ""))
    log.info("Сценарий: %r, %d шотов, ~%.1fс",
             script["title"], len(script["shots"]), estimate_duration(script))

    if os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes"):
        # Дешёвая проверка: ключи, сценарист, доставка — без картинок и видео.
        print(json.dumps(script, ensure_ascii=False, indent=2))
        deliver.send_message(f"DRY_RUN ок: {script['title']}\n{topic}")
        log.info("DRY_RUN — генерация медиа пропущена")
        return

    out = os.path.join("/tmp", f"{script['title'][:40] or 'story'}.mp4")
    from story.render import render
    res = render(script, out)

    caption = (f"{script['title']}\n{topic}\n"
               f"{res['duration']:.0f}с · {res['shots']} шотов · "
               f"видео ${res['video_cost']:.2f}\n"
               f"стиль: {res.get('style_preset')}"
               + (f" + {res['style_extra']}" if res.get("style_extra") else ""))
    deliver.send_video(res["path"], caption)
    # Текст отдельным файлом — чтобы можно было озвучить своим голосом или
    # другим TTS, не выковыривая реплики из логов.
    for key in ("narration_txt", "narration_srt", "captions_srt"):
        deliver.send_document((res.get("texts") or {}).get(key, ""))
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.error("Прогон упал: %s", e, exc_info=True)
        # Ошибку видно в Telegram, а не только в логах Railway — иначе крон
        # будет молча падать по ночам.
        deliver.send_message(f"❌ Прогон упал\n{type(e).__name__}: {e}\n\n"
                             f"{traceback.format_exc()[-1200:]}")
        sys.exit(1)
