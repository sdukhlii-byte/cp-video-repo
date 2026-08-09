"""
story/orclient.py — единственный клиент OpenRouter: текст, картинки, видео.

Три поверхности:
  • POST /chat/completions — сценарист (текст)
  • POST /images           — кейфреймы и референс-лист персонажа (синхронно, b64)
  • POST /videos           — image-to-video (async: submit → poll → download)

API видео молодое и меняется — все несовместимости локализованы в
generate_video_bytes(). Список доступных слагов: `python3 cli.py models`.
"""

from __future__ import annotations

import base64
import logging
import time

import requests

import config as C

log = logging.getLogger("or")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {C.require('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": C.OR_REFERER,
        "X-Title": C.OR_TITLE,
    }


class ORLocked(RuntimeError):
    """Нет средств / ключ заблокирован — ретраить бессмысленно."""


class ORBlocked(RuntimeError):
    """Отклонено контент-фильтром. Ретрай тем же промптом не поможет."""


def _raise_for_response(r: requests.Response, what: str) -> None:
    if r.ok:
        return
    body = r.text[:400]
    low = body.lower()
    if r.status_code == 402 or any(s in low for s in ("insufficient", "exhausted", "is locked")):
        raise ORLocked(f"OpenRouter {what} HTTP {r.status_code}: {body}")
    if any(s in low for s in ("prohibited", "blocked", "safety", "content policy", "flagged")):
        raise ORBlocked(f"OpenRouter {what} HTTP {r.status_code}: {body}")
    raise RuntimeError(f"OpenRouter {what} HTTP {r.status_code}: {body}")


# ── ТЕКСТ ──────────────────────────────────────────────────────────────────────

def chat(system: str, user: str, model: str = "", temperature: float = 0.8,
         max_tokens: int = 4000, retries: int = 3) -> str:
    model = model or C.SCRIPT_MODEL
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(f"{C.OR_BASE}/chat/completions", headers=_headers(),
                              json=payload, timeout=180)
            _raise_for_response(r, f"chat[{model}]")
            js = r.json()
            return js["choices"][0]["message"]["content"]
        except ORLocked:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last  # недостижимо


# ── КАРТИНКИ ───────────────────────────────────────────────────────────────────

def generate_image_bytes(prompt: str, ref_urls: list[str] | None = None,
                         aspect_ratio: str = "", label: str = "",
                         timeout: float = 180.0, retries: int = 3) -> bytes:
    """
    Одна картинка → сырые байты PNG.
    ref_urls — референсы (http(s) или data:) для сохранения персонажа on-model.
    """
    payload: dict = {
        "model": C.IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": aspect_ratio or C.ASPECT,
        "output_format": "png",
    }
    if C.IMAGE_RESOLUTION:
        payload["resolution"] = C.IMAGE_RESOLUTION
    if ref_urls:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": u}} for u in ref_urls if u
        ]

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(f"{C.OR_BASE}/images", headers=_headers(),
                              json=payload, timeout=timeout)
            _raise_for_response(r, f"image[{label}]")
            js = r.json()
            data = js.get("data") or []
            if not data or not data[0].get("b64_json"):
                raise RuntimeError(f"image[{label}]: нет b64_json в {str(js)[:300]}")
            log.info("image[%s] ok (cost=%s)", label, (js.get("usage") or {}).get("cost"))
            return base64.b64decode(data[0]["b64_json"])
        except (ORLocked, ORBlocked):
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                log.warning("image[%s] transient (%s), retry %d/%d",
                            label, str(e)[:90], attempt, retries)
                time.sleep(2 ** attempt)
                continue
            raise
    raise last


# ── ВИДЕО (image-to-video) ─────────────────────────────────────────────────────

def _seconds(val) -> int:
    s = str(val).strip().lower().rstrip("s").strip()
    try:
        return int(round(float(s)))
    except ValueError:
        return 4


def generate_video_bytes(model: str, prompt: str, frame_image_url: str,
                         duration_sec, resolution: str = "", aspect_ratio: str = "",
                         generate_audio: bool = False, negative_prompt: str = "",
                         label: str = "", timeout: float = 900.0,
                         poll_interval: float = 10.0) -> tuple[bytes, float]:
    """
    Сабмит → поллинг → скачивание. Возвращает (mp4_bytes, cost).
    frame_image_url — первый кадр; http(s)-URL надёжнее data:.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "duration": _seconds(duration_sec),
        "resolution": resolution or C.VIDEO_RESOLUTION,
        "aspect_ratio": aspect_ratio or C.ASPECT,
        "generate_audio": bool(generate_audio),
        "frame_images": [{
            "type": "image_url",
            "image_url": {"url": frame_image_url},
            "frame_type": "first_frame",
        }],
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    # Submit (рейт-лимит → короткий бэкофф на ТОЙ ЖЕ модели: лучше подождать,
    # чем уходить на фолбэк и терять единый визуальный стиль).
    job_id, sub = None, {}
    for attempt in range(3):
        r = requests.post(f"{C.OR_BASE}/videos", headers=_headers(), json=payload, timeout=60)
        if r.status_code != 429:
            _raise_for_response(r, f"video-submit[{label}]")
            sub = r.json()
            if sub.get("error"):
                raise RuntimeError(f"video-submit[{label}]: {str(sub['error'])[:300]}")
            job_id = sub.get("id")
            if job_id:
                break
        if attempt < 2:
            wait = 5 * (attempt + 1)
            log.warning("video-submit[%s] HTTP %s — retry %d/3 через %ds",
                        label, r.status_code, attempt + 1, wait)
            time.sleep(wait)
    if not job_id:
        raise RuntimeError(f"video-submit[{label}] без job id: {str(sub)[:200]}")

    polling_url = sub.get("polling_url") or f"{C.OR_BASE}/videos/{job_id}"
    log.info("video[%s] job=%s", label, job_id)

    deadline = time.monotonic() + timeout
    content_url, cost, poll_fails = None, 0.0, 0
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(f"video[{label}] timeout {timeout:.0f}s (job={job_id})")
        time.sleep(poll_interval)
        p = requests.get(polling_url, headers=_headers(), timeout=60)
        if not p.ok:
            if p.status_code in (404, 410):
                raise RuntimeError(f"video[{label}] poll {p.status_code} — джоба пропала")
            poll_fails += 1
            log.warning("video[%s] poll HTTP %s (%d/5)", label, p.status_code, poll_fails)
            if poll_fails >= 5:
                raise RuntimeError(f"video[{label}] poll падает подряд (HTTP {p.status_code})")
            continue
        poll_fails = 0
        js = p.json()
        status = js.get("status")
        if status == "completed":
            urls = js.get("unsigned_urls") or []
            if not urls:
                raise RuntimeError(f"video[{label}] completed, но нет unsigned_urls")
            content_url = urls[0]
            cost = float((js.get("usage") or {}).get("cost") or 0.0)
            log.info("video[%s] completed (cost=$%.3f)", label, cost)
            break
        if status in ("failed", "cancelled", "expired"):
            raise RuntimeError(f"video[{label}] {status}: {js.get('error')}")

    dl = requests.get(content_url, headers=_headers(), timeout=300)
    if not dl.ok:
        dl = requests.get(content_url, timeout=300)   # часть URL уже подписана
    dl.raise_for_status()
    return dl.content, cost


# ── СПРАВОЧНИК МОДЕЛЕЙ ─────────────────────────────────────────────────────────

def list_models(filter_str: str = "") -> list[dict]:
    """Каталог моделей OpenRouter (для подбора актуального слага видеомодели)."""
    r = requests.get(f"{C.OR_BASE}/models", headers=_headers(), timeout=60)
    r.raise_for_status()
    items = r.json().get("data", [])
    if filter_str:
        f = filter_str.lower()
        items = [m for m in items if f in str(m.get("id", "")).lower()
                 or f in str(m.get("name", "")).lower()
                 or f in str((m.get("architecture") or {}).get("output_modalities", "")).lower()]
    return items
