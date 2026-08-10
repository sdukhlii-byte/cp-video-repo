#!/usr/bin/env python3
"""
run_job.py — одноразовый прогон для Railway: тема из переменной → ролик → Telegram.

Контейнер поднимается, делает ОДИН ролик и завершается. Это не сервер:
ни порта, ни домена, ни health-check. Запуск — вручную (Redeploy) или по
расписанию (Settings → Cron Schedule).

Переменные окружения:
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


def main() -> None:
    from story.script_writer import coerce, estimate_duration, write_script

    script_file = os.environ.get("SCRIPT_FILE", "").strip()
    if script_file:
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
               f"видео ${res['video_cost']:.2f}")
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
