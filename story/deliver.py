"""
story/deliver.py — доставка готового ролика в Telegram.

Нужна там, где локальной папки нет: на Railway контейнер эфемерный, и без
отправки файл просто исчезнет вместе с деплоем.

Telegram режет sendVideo на 50 МБ. Ролик 30 сек в 720p весит 3–8 МБ, так что
лимит достижим только при большой длине или 1080p — на этот случай есть явная
проверка с понятной ошибкой вместо таймаута.
"""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("deliver")

TG_LIMIT_MB = 50


def send_video(path: str, caption: str = "", retries: int = 3) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        log.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — доставка пропущена")
        return

    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > TG_LIMIT_MB:
        raise RuntimeError(
            f"Ролик {size_mb:.1f} МБ > лимита Telegram {TG_LIMIT_MB} МБ. "
            f"Понизь VIDEO_RESOLUTION или TARGET_DURATION_SEC."
        )

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendVideo",
                    data={"chat_id": chat, "caption": caption[:1024],
                          "supports_streaming": "true"},
                    files={"video": (os.path.basename(path), f, "video/mp4")},
                    timeout=(10, 300),
                )
            r.raise_for_status()
            log.info("Отправлено в Telegram (%.1f МБ)", size_mb)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("Telegram попытка %d/%d: %s", attempt, retries, str(e)[:160])
            if attempt < retries:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Не удалось отправить в Telegram: {last}")


def send_document(path: str, caption: str = "") -> None:
    """Отправляет файл документом (текст сценария, srt) — не сжимая."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat) or not os.path.exists(path):
        return
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat, "caption": caption[:1024]},
                files={"document": (os.path.basename(path), f, "text/plain")},
                timeout=(10, 120),
            )
        r.raise_for_status()
        log.info("Отправлен файл %s", os.path.basename(path))
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить %s: %s", os.path.basename(path), str(e)[:140])


def send_message(text: str) -> None:
    """Короткое текстовое уведомление (например, об ошибке прогона)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text[:4000]}, timeout=30)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить сообщение: %s", str(e)[:120])
