"""
story/visuals.py — визуальный слой.

  1) character_ref()  → референс-лист персонажа (ОДИН раз на ролик)
  2) keyframe()       → кейфрейм шота с этим референсом (персонаж on-model)
  3) animate()        → image-to-video клип из кейфрейма, БЕЗ звука
                        (звук — закадровый ElevenLabs, см. voice.py)

Цепочка отказов сделана так, чтобы один заблокированный кадр не убивал ролик:
кейфрейм → повтор с «чистой» оговоркой; видео → вторичная модель → Ken Burns.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os

import config as C
from story import media, orclient
from story.prompts import (
    SAFETY_CLAUSE, build_character_ref_prompt, build_keyframe_prompt, build_motion_prompt,
)

log = logging.getLogger("visuals")


def _save(data: bytes, path: str) -> str:
    with open(path, "wb") as f:
        f.write(data)
    return path


def _data_uri(path: str) -> str:
    mt = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mt};base64," + base64.b64encode(f.read()).decode()


def _frame_url(path: str) -> str:
    """
    URL кейфрейма для видеомодели. Публичный http(s) надёжнее всего — если
    настроен S3/R2, заливаем туда; иначе data:-URL (принимают не все провайдеры,
    и это первое, что стоит проверить, если i2v валится на кадре).
    """
    if C.STORAGE_ENABLED:
        try:
            from story import storage
            return storage.upload(path, f"keyframes/{os.path.basename(path)}")
        except Exception as e:  # noqa: BLE001
            log.warning("Загрузка кейфрейма в S3 не удалась (%s) — беру data:URI", str(e)[:120])
    return _data_uri(path)


# ── 1. РЕФЕРЕНС ПЕРСОНАЖА ──────────────────────────────────────────────────────

def character_ref(workdir: str, character: dict, world: str = "",
                  preset: str = "") -> tuple[str, str]:
    """Возвращает (ref_url_для_кейфреймов, локальный_путь)."""
    prompt = build_character_ref_prompt(character, world, preset)
    path = os.path.join(workdir, "character_ref.png")
    data = orclient.generate_image_bytes(prompt, aspect_ratio=C.ASPECT, label="charref")
    _save(data, path)
    log.info("Референс персонажа: %s", path)
    return _data_uri(path), path


# ── 2. КЕЙФРЕЙМ ШОТА ───────────────────────────────────────────────────────────

def keyframe(workdir: str, idx: int, shot: dict, character: dict,
             ref_url: str, world: str = "", preset: str = "") -> tuple[str, str]:
    base = build_keyframe_prompt(shot, character, world, preset,
                                 brand=C.BRAND_NAME, brand_mode=C.BRAND_PLACEMENT,
                                 tagline=C.BRAND_TAGLINE)
    path = os.path.join(workdir, f"keyframe_{idx:02d}.png")

    attempts = [
        ("primary", base, [ref_url]),
        ("safe", base + SAFETY_CLAUSE, [ref_url]),
        ("no-ref", base + SAFETY_CLAUSE, []),   # без референса, лишь бы шот отрисовался
    ]
    last: Exception | None = None
    for label, prompt, refs in attempts:
        try:
            data = orclient.generate_image_bytes(
                prompt, ref_urls=refs or None, aspect_ratio=C.ASPECT, label=f"kf{idx}")
            _save(data, path)
            if label == "no-ref":
                log.warning("Кейфрейм %d собран БЕЗ референса — персонаж может «поплыть»", idx)
            else:
                log.info("Кейфрейм %d готов (%s): %s", idx, label, path)
            return _data_uri(path), path
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("Кейфрейм %d попытка '%s' не удалась: %s", idx, label, str(e)[:140])
    raise RuntimeError(f"Кейфрейм {idx} не собрался: {last}")


# ── 3. АНИМАЦИЯ ШОТА ───────────────────────────────────────────────────────────

def _quantize(target_sec: float) -> int:
    """
    Ближайшая поддерживаемая длина клипа СВЕРХУ (лишнее срежем под голос).

    Если реплика длиннее самого длинного доступного клипа, взять больше неоткуда —
    и compose добьёт хвост замороженным кадром. Это видно зрителю, поэтому
    предупреждаем громко: лечится укорочением шота (SHOT_TARGET_SEC), а не здесь.
    """
    allowed = sorted(C.VIDEO_ALLOWED_DURS)
    for d in allowed:
        if d >= target_sec - 0.25:
            return d
    log.warning("Шот %.1fс длиннее потолка видеомодели (%dс) — %.1fс хвоста "
                "будут замороженным кадром. Уменьши SHOT_TARGET_SEC.",
                target_sec, allowed[-1], target_sec - allowed[-1])
    return allowed[-1]


def animate(workdir: str, idx: int, keyframe_path: str, shot: dict,
            target_sec: float, preset: str = "") -> tuple[str, float]:
    """
    Клип шота (без звука). Возвращает (путь, стоимость).
    target_sec — длина озвучки шота; клип генерим с запасом и режем в compose.
    """
    raw = os.path.join(workdir, f"shot_{idx:02d}_raw.mp4")
    prompt = build_motion_prompt(shot, preset)
    dur = _quantize(target_sec)
    frame_url = _frame_url(keyframe_path)

    # Основная модель (Veo).
    try:
        data, cost = orclient.generate_video_bytes(
            model=C.VIDEO_MODEL, prompt=prompt, frame_image_url=frame_url,
            duration_sec=dur, generate_audio=C.VIDEO_GENERATE_AUDIO,
            negative_prompt=C.VIDEO_NEGATIVE, label=f"veo{idx}")
        _save(data, raw)
        log.info("Шот %d: %s, %dс, $%.3f", idx, C.VIDEO_MODEL, dur, cost)
        return raw, cost
    except Exception as e:  # noqa: BLE001
        log.warning("Шот %d на %s не вышел (%s)", idx, C.VIDEO_MODEL, str(e)[:160])

    # Вторичная модель — обычно мягче по контент-фильтру.
    if C.SECONDARY_VIDEO_ENABLED:
        try:
            data, cost = orclient.generate_video_bytes(
                model=C.SECONDARY_VIDEO_MODEL, prompt=prompt, frame_image_url=frame_url,
                duration_sec=dur, generate_audio=False,
                negative_prompt=C.VIDEO_NEGATIVE, label=f"sec{idx}")
            _save(data, raw)
            log.info("Шот %d: фолбэк %s, $%.3f", idx, C.SECONDARY_VIDEO_MODEL, cost)
            return raw, cost
        except Exception as e:  # noqa: BLE001
            log.warning("Шот %d: фолбэк-модель тоже не вышла (%s)", idx, str(e)[:160])

    # Последний рубеж: оживляем сам кейфрейм.
    if not C.KENBURNS_FALLBACK:
        raise RuntimeError(f"Шот {idx}: видео не собралось")
    log.warning("Шот %d: Ken Burns из кейфрейма", idx)
    media.ken_burns_clip(keyframe_path, raw, max(target_sec, C.MIN_SHOT_SEC),
                         C.VIDEO_W, C.VIDEO_H, C.FPS)
    return raw, 0.0
