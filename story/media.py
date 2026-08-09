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
