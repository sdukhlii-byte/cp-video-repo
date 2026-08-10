"""
story/compose.py — финальная сборка на ffmpeg.

  1. normalize_shot()  клип → ровно d_i секунд, VIDEO_WxVIDEO_H, fps, без звука
  2. concat_video()    склейка → body.mp4
  3. burn()            видео + голос + музыка + ASS-субтитры (+лого) → body_final
  4. endcard/final     опциональная эндкарта и финальная склейка

Инвариант синхрона: длина i-й озвучки в общей дорожке == d_i (длина i-го шота).
Без него голос, картинка и субтитры расходятся, и дрейф копится к концу ролика.
"""

from __future__ import annotations

import logging
import os

import config as C
from story.media import concat_demux, detect_crop, probe_duration, run_ff, xfade_concat

log = logging.getLogger("compose")


# ── 1. НОРМАЛИЗАЦИЯ ────────────────────────────────────────────────────────────

def normalize_shot(src: str, dst: str, duration: float) -> None:
    """Клип → ровно `duration` сек, целевой кадр (cover-crop), FPS, без аудио."""
    # Сначала срезаем поля провайдера, иначе они растянутся вместе с кадром.
    pre = ""
    if C.AUTOCROP_BARS:
        found = detect_crop(src)
        if found:
            pre = found + ","
    vf = (
        f"{pre}"
        f"scale={C.VIDEO_W}:{C.VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={C.VIDEO_W}:{C.VIDEO_H},fps={C.FPS},setsar=1,"
        f"tpad=stop_mode=clone:stop_duration=5"   # если клип короче d_i — дотянем
    )
    run_ff([
        "ffmpeg", "-y", "-i", src, "-t", f"{duration:.3f}",
        "-vf", vf, "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(C.FPS),
        "-profile:v", "high", "-preset", "veryfast", dst,
    ], label="normalize")


# ── 4. ПРОЖИГ ──────────────────────────────────────────────────────────────────

def burn(body: str, voice_wav: str, ass_path: str, total_dur: float, dst: str,
         music_path: str = "", logo_path: str = "") -> None:
    inputs = ["-i", body, "-i", voice_wav]
    idx = 2
    logo_idx = music_idx = None
    if logo_path and os.path.exists(logo_path):
        inputs += ["-i", logo_path]
        logo_idx = idx
        idx += 1
    if music_path and os.path.exists(music_path):
        inputs += ["-stream_loop", "-1", "-i", music_path]
        music_idx = idx
        idx += 1

    # Пути в filtergraph: двоеточия и кавычки надо экранировать, иначе ffmpeg
    # распарсит путь как список опций фильтра.
    ass_arg = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "")
    fonts_dir = C.FONTS_DIR.replace("\\", "/").replace(":", "\\:")

    fc = f"[0:v]subtitles='{ass_arg}':fontsdir='{fonts_dir}'[vs]"
    if logo_idx is not None:
        logo_w = int(C.VIDEO_W * C.LOGO_WIDTH_PCT)
        fc += (f";[{logo_idx}:v]scale={logo_w}:-1[logo]"
               f";[vs][logo]overlay=W-w-40:40:format=auto[vout]")
    else:
        fc += ";[vs]null[vout]"

    if music_idx is None:
        fc += ";[1:a]aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    else:
        fade_out = max(total_dur - C.MUSIC_FADE_SEC, 0.1)
        # Голос нормализуем ДО микса, а не после. Иначе loudnorm приводит к
        # -16 LUFS готовую смесь, и реальная громкость подложки начинает
        # зависеть от того, насколько плотно в ролике говорят: в разговорном
        # ролике музыки почти не слышно, в паузах она вылезает. После этой
        # перестановки MUSIC_VOLUME означает ровно уровень относительно речи.
        fc += (";[1:a]aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11,"
               "asplit=2[voc][sc]")
        fc += (f";[{music_idx}:a]aresample=44100,"
               f"loudnorm=I={C.MUSIC_LUFS}:TP=-2:LRA=11,"
               f"volume={C.MUSIC_VOLUME},"
               f"afade=t=in:st=0:d={C.MUSIC_FADE_SEC:.2f},"
               f"afade=t=out:st={fade_out:.2f}:d={C.MUSIC_FADE_SEC:.2f}[mus0]")
        if C.MUSIC_DUCKING:
            fc += (f";[mus0][sc]sidechaincompress="
                   f"threshold={C.MUSIC_DUCK_THRESHOLD}:"
                   f"ratio={C.MUSIC_DUCK_RATIO}:"
                   f"attack=20:release=350[mus]")
        else:
            fc += ";[mus0]anull[mus];[sc]anullsink"
        # normalize=0 обязателен: по умолчанию amix делит громкость на число
        # входов, из-за чего и голос, и музыка теряют 6 дБ, а заданный
        # MUSIC_VOLUME фактически оказывается вдвое меньше указанного.
        # Лимитер вместо повторного loudnorm: он только ловит пики, не трогая
        # соотношение голоса и музыки, которое мы только что выставили.
        fc += (";[voc][mus]amix=inputs=2:duration=first:dropout_transition=0:"
               "normalize=0,alimiter=limit=0.95[aout]")

    # БЕЗ -shortest: длину диктует видео; -t страхует от бесконечной музыки.
    run_ff([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total_dur:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-r", str(C.FPS),
        "-movflags", "+faststart", dst,
    ], label="burn")


# ── 5. ЭНДКАРТА ────────────────────────────────────────────────────────────────

def make_endcard(dst: str, logo_path: str, seconds: float = 0.0) -> None:
    seconds = seconds or C.ENDCARD_SEC
    logo_w = int(C.VIDEO_W * 0.55)
    bg = f"color=c={C.ENDCARD_BG}:s={C.VIDEO_W}x{C.VIDEO_H}:r={C.FPS}:d={seconds}"
    run_ff([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", bg,
        "-i", logo_path,
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={seconds}",
        "-filter_complex",
        f"[0:v]format=yuv420p[bg];[1:v]scale={logo_w}:-1[logo];"
        f"[bg][logo]overlay=(W-w)/2:(H-h)/2[vout]",
        "-map", "[vout]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "160k", "-r", str(C.FPS), "-t", f"{seconds}",
        "-movflags", "+faststart", dst,
    ], label="endcard")


# ── ОРКЕСТРАТОР ────────────────────────────────────────────────────────────────

def compose(workdir: str, clips: list[str], durations: list[float],
            voice_track: str, ass_path: str, out_path: str,
            music_path: str = "", logo_path: str = "") -> str:
    use_xfade = bool(C.XFADE_SEC) and len(clips) > 1

    # Кроссфейд СЪЕДАЕТ время: склейка n клипов даёт sum(d) - (n-1)*xfade.
    # Голос при этом остаётся полной длины, и после первой же склейки картинка
    # начинает убегать вперёд, а к концу ролика расходится на секунды.
    # Лечится компенсацией: каждый шот, кроме последнего, удлиняем ровно на
    # длину перехода — тогда после наложения сумма снова равна sum(d),
    # и начало каждого шота попадает туда же, где его ждут субтитры.
    norm = []
    for i, (clip, d) in enumerate(zip(clips, durations)):
        dst = os.path.join(workdir, f"norm_{i:02d}.mp4")
        pad = C.XFADE_SEC if (use_xfade and i < len(clips) - 1) else 0.0
        normalize_shot(clip, dst, d + pad)
        norm.append(dst)

    body = os.path.join(workdir, "body.mp4")
    if use_xfade:
        xfade_concat(norm, body, C.XFADE_SEC, C.FPS, label="body_xfade")
    else:
        concat_demux(norm, body, workdir, reencode=False, label="body")

    total = probe_duration(body)
    body_final = os.path.join(workdir, "body_final.mp4")
    burn(body, voice_track, ass_path, total, body_final,
         music_path=music_path, logo_path=logo_path)

    if C.ENDCARD_ENABLED and logo_path and os.path.exists(logo_path):
        endcard = os.path.join(workdir, "endcard.mp4")
        make_endcard(endcard, logo_path)
        concat_demux([body_final, endcard], out_path, workdir,
                     reencode=True, label="final", fps=C.FPS)
    else:
        os.replace(body_final, out_path)

    log.info("Готово: %s (%.2fс)", out_path, probe_duration(out_path))
    return out_path
