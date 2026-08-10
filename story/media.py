"""
story/media.py — обёртки над ffmpeg/ffprobe. Ничего про сюжет здесь нет,
только медиа-кирпичи, которыми пользуются voice/compose/visuals.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

log = logging.getLogger("media")


def run_ff(args: list[str], label: str = "") -> None:
    """Запускает ffmpeg; при ошибке бросает RuntimeError с хвостом stderr."""
    log.debug("ffmpeg[%s]: %s ...", label, " ".join(args[:10]))
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg[{label}] rc={proc.returncode}:\n{proc.stderr[-1800:]}")


def probe_duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}:\n{proc.stderr[-400:]}")
    return float(json.loads(proc.stdout)["format"]["duration"])


def has_audio(path: str) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _uniform_band(px, w: int, h: int, axis: str, tol: int = 8) -> int:
    """Сколько подряд идущих строк (или столбцов) от края залиты одним цветом."""
    def line(i):
        if axis == "top":
            return [px[x, i] for x in range(0, w, max(w // 40, 1))]
        if axis == "bottom":
            return [px[x, h - 1 - i] for x in range(0, w, max(w // 40, 1))]
        if axis == "left":
            return [px[i, y] for y in range(0, h, max(h // 40, 1))]
        return [px[w - 1 - i, y] for y in range(0, h, max(h // 40, 1))]

    first = line(0)
    base = first[0]
    if max(max(abs(c[k] - base[k]) for k in range(3)) for c in first) > tol:
        return 0                      # у самого края уже не однотонно

    limit = (h if axis in ("top", "bottom") else w) // 2
    n = 0
    for i in range(limit):
        cur = line(i)
        if max(max(abs(c[k] - base[k]) for k in range(3)) for c in cur) > tol:
            break
        n += 1
    return n


def detect_crop(path: str, at_sec: float = 1.0) -> str | None:
    """
    Ищет однотонные поля по краям кадра и возвращает строку для фильтра crop,
    либо None если полей нет.

    Зачем: провайдеры видео и картинок иногда отдают кадр не в запрошенной
    пропорции, добивая недостающее сплошной заливкой. Наш scale+crop растянул бы
    такой кадр ЦЕЛИКОМ, вместе с полем, и заливка осталась бы в готовом ролике.

    Штатный cropdetect из ffmpeg здесь бесполезен: он ищет только ТЁМНЫЕ поля,
    а заливка бывает серой. Поэтому смотрим пиксели сами, на уменьшенном кадре.
    """
    try:
        from PIL import Image
    except ImportError:
        log.warning("Pillow не установлен — поля по краям не срезаются")
        return None

    tmp = path + ".probe.png"
    try:
        run_ff(["ffmpeg", "-y", "-ss", f"{at_sec}", "-i", path, "-frames:v", "1",
                "-vf", "scale=160:-2", tmp], label="cropprobe")
    except RuntimeError:
        try:
            run_ff(["ffmpeg", "-y", "-i", path, "-frames:v", "1",
                    "-vf", "scale=160:-2", tmp], label="cropprobe0")
        except RuntimeError:
            return None

    try:
        im = Image.open(tmp).convert("RGB")
        w, h = im.size
        px = im.load()
        top = _uniform_band(px, w, h, "top")
        bottom = _uniform_band(px, w, h, "bottom")
        left = _uniform_band(px, w, h, "left")
        right = _uniform_band(px, w, h, "right")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    fy, fx = (top + bottom) / h, (left + right) / w
    # Меньше 10% — это рамка композиции, виньетка или шум сжатия. Настоящее поле
    # провайдера всегда крупное: оно берётся из несовпадения пропорций
    # (кадр 4:5 в рамке 9:16 даёт ~22%), а не из нескольких пикселей.
    # Больше 45% — детектор поймал тёмную сцену целиком, и обрезка испортила бы
    # кадр сильнее, чем само поле.
    if max(fy, fx) < 0.10 or max(fy, fx) > 0.45:
        return None

    # Заливка провайдера всегда нейтральная: чёрная, серая или белая. Ровное
    # синее небо или красная стена в кадре — это композиция, а не поле, и резать
    # их нельзя. Отсекаем по насыщенности угла.
    corner = px[1, 1] if top or left else px[w - 2, h - 2]
    if max(corner[:3]) - min(corner[:3]) > 26:
        log.debug("Однотонная область есть, но она цветная — не поле, не режу")
        return None

    src = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        sw, sh = (int(v) for v in src.split("x")[:2])
    except ValueError:
        return None

    scale_x, scale_y = sw / w, sh / h
    x = int(left * scale_x) // 2 * 2
    y = int(top * scale_y) // 2 * 2
    cw = max(int((w - left - right) * scale_x) // 2 * 2, 16)
    ch = max(int((h - top - bottom) * scale_y) // 2 * 2, 16)
    log.info("Поля в %s: срезаю %.0f%% по вертикали, %.0f%% по горизонтали",
             os.path.basename(path), fy * 100, fx * 100)
    return f"crop={cw}:{ch}:{x}:{y}"


def make_silence(dst: str, duration: float, sr: int = 44100) -> str:
    run_ff([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=stereo",
        "-t", f"{max(duration, 0.01):.3f}", "-ar", str(sr), "-ac", "2", dst,
    ], label="silence")
    return dst


def concat_demux(paths: list[str], dst: str, workdir: str, reencode: bool = False,
                 label: str = "concat", fps: int | None = None) -> str:
    """Склейка однотипных файлов через concat-демуксер."""
    listfile = os.path.join(workdir, f"_concat_{label}.txt")
    with open(listfile, "w") as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    args = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile]
    if reencode:
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
        if fps:
            args += ["-r", str(fps)]
    else:
        args += ["-c", "copy"]
    args += [dst]
    run_ff(args, label=label)
    return dst


def ken_burns_clip(image_path: str, dst: str, duration: float,
                   width: int, height: int, fps: int, zoom: float = 1.14) -> str:
    """
    Живой клип из статичной картинки (медленный зум-ин). Фолбэк, когда
    image-to-video не отдал результат. Без звука.
    """
    frames = max(int(round(duration * fps)), 1)
    zinc = (zoom - 1.0) / max(frames - 1, 1)
    vf = (
        f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
        f"crop={width*2}:{height*2},"
        f"zoompan=z='min(zoom+{zinc:.6f},{zoom})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
    )
    run_ff([
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-t", f"{duration:.3f}", "-vf", vf, "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-profile:v", "high", "-preset", "veryfast", dst,
    ], label="kenburns")
    return dst


def xfade_concat(paths: list[str], dst: str, transition: float, fps: int,
                 label: str = "xfade") -> str:
    """Склейка видео (без звука) с кроссфейдами. Требует реэнкод."""
    n = len(paths)
    if n == 1:
        run_ff(["ffmpeg", "-y", "-i", paths[0], "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-r", str(fps), dst], label=label)
        return dst
    durs = [probe_duration(p) for p in paths]
    args = ["ffmpeg", "-y"]
    for p in paths:
        args += ["-i", p]
    chain, prev, acc = [], "[0:v]", durs[0]
    for k in range(1, n):
        off = max(0.0, acc - transition)
        out = f"[vx{k}]" if k < n - 1 else "[vout]"
        chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={transition}:offset={off:.3f}{out}")
        prev, acc = out, acc + durs[k] - transition
    args += ["-filter_complex", ";".join(chain), "-map", "[vout]", "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), dst]
    run_ff(args, label=label)
    return dst
