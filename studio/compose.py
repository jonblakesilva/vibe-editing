"""Screen + camera layouts for recordings with separate tracks (e.g. Tella exports).

Builds two "layout masters" from one or more takes, both with identical timing and the
camera's audio, so the normal cut/finish pipeline can render them like any recording:

- landscape (1920x1080): a full-frame 16:9 window of the screen (panned by keyframes) with a
  rounded camera bubble bottom-right,
  switching to full-screen camera during `cam_ranges` (intro, outro).
- vertical (1080x1920): the screen on top, the camera below, with a thin brand-colored seam
  where captions sit; full-height camera during `cam_ranges`.

The original files are only read. Masters are written to the project's work folder.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from . import media

FPS = "30000/1001"
LAND = (1920, 1080)
VERT = (1080, 1920)


def _mask(path: Path, w: int, h: int, radius: int) -> Path:
    if not path.exists():
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
        img.save(path)
    return path


def _between(ranges: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in ranges) or "0"


def _keyframes(keys: list[tuple[float, float]] | None, default: float = 0.5) -> str:
    """Piecewise-linear expression of t from (time, value) keyframes; value 0 = left edge of the
    screen recording, 1 = right edge, 0.5 = centred."""
    keys = sorted(keys or [(0.0, default)])
    expr = f"{keys[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        ramp = f"{v0:.4f}+({v1 - v0:.4f})*(t-{t0:.3f})/{max(t1 - t0, 0.001):.3f}"
        expr = f"if(lt(t,{t1:.3f}),{ramp},{expr})"
    return f"if(lt(t,{keys[0][0]:.3f}),{keys[0][1]:.4f},{expr})"


def find_takes(folder: Path) -> list[tuple[Path, Path]]:
    """(camera, screen) pairs from a Tella raw export: one sub-folder per clip, in order."""
    takes = []
    for d in sorted([p for p in folder.iterdir() if p.is_dir()], key=lambda p: [int(x) if x.isdigit() else x
                                                                                   for x in p.name.split()]):
        cam, scr = d / "Camera.mp4", d / "Screen.mp4"
        if cam.exists() and scr.exists():
            takes.append((cam, scr))
    return takes


def build_masters(takes: list[tuple[Path, Path]], out_dir: Path, *, cam_ranges: list[tuple[float, float]],
                  bg: str = "#0F1E4A", accent: str = "#F97316", face_x: float = 0.47,
                  screen_crop_bottom: float = 0.045, vertical_screen_width: float = 0.47,
                  screen_x: list[tuple[float, float]] | None = None,
                  limit: float | None = None, progress: Callable[[float], None] | None = None,
                  cancel: threading.Event | None = None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    land, vert = out_dir / "layout_landscape.mp4", out_dir / "layout_vertical.mp4"
    durs = [min(media.probe(c).duration, media.probe(s).duration) for c, s in takes]
    if limit:  # quick layout test: only the first `limit` seconds of each take
        durs = [min(d, limit) for d in durs]
    total = sum(durs)
    bgc = bg.replace("#", "0x")
    acc = accent.replace("#", "0x")
    bub = 300
    bmask = _mask(out_dir / "bubble_mask.png", bub, bub, 36)
    args, f = [], []
    for c, s in takes:
        args += ["-i", str(c), "-i", str(s)]
    m = len(takes) * 2
    args += ["-loop", "1", "-i", str(bmask)]
    for i, d in enumerate(durs):
        f.append(f"[{2 * i}:v]trim=0:{d:.3f},setpts=PTS-STARTPTS,fps={FPS},scale=1920:1080,setsar=1[c{i}]")
        f.append(f"[{2 * i + 1}:v]trim=0:{d:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                 f"crop=iw:ih*{1 - screen_crop_bottom:.3f}:0:0,setsar=1[s{i}]")
        f.append(f"[{2 * i}:a]aresample=48000,apad,atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
    n = len(takes)
    f.append("".join(f"[c{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[C][A0]")
    f.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[S]")
    f.append("[A0]pan=stereo|c0=c0|c1=c0[A]")
    f.append("[C]split=4[C1][C2][C3][C4]")
    f.append("[S]split=2[S1][S2]")
    cam_on = _between(cam_ranges)
    # landscape: a full-frame 16:9 window of the screen (panning with `screen_x` keyframes so the
    # part being shown stays in view), rounded camera bubble bottom-right, full camera in cam_ranges
    f.append(f"[S1]crop=w=ih*16/9:h=ih:x='(iw-ow)*({_keyframes(screen_x)})':y=0,"
             f"scale=1920:1080:flags=lanczos,setsar=1[L1]")
    side = 760
    cx = int(max(0, min(1920 - side, face_x * 1920 - side / 2)))
    f.append(f"[C2]crop={side}:{side}:{cx}:{1080 - side - 40},scale={bub}:{bub}[Cb]")
    f.append(f"[{m}:v]format=gray,scale={bub}:{bub}[bm]")
    f.append("[Cb][bm]alphamerge[Cbm]")
    f.append(f"[L1][Cbm]overlay=x={LAND[0] - 32 - bub}:y={LAND[1] - 32 - bub}:shortest=1[L2]")
    f.append(f"[L2][C1]overlay=enable='{cam_on}'[L]")
    # vertical: screen on top (centre of the page), camera below, accent seam at mid-height
    seam = VERT[1] // 2
    f.append(f"color=c={bgc}:s=1080x1920:r={FPS}:d={total:.3f}[VB]")
    f.append(f"[S2]crop=iw*{vertical_screen_width:.3f}:ih:(iw-iw*{vertical_screen_width:.3f})/2:0,"
             f"scale=1080:-2:flags=lanczos[S2s]")
    f.append(f"[VB][S2s]overlay=x=0:y={seam}-h:shortest=1[V1]")
    ch = VERT[1] - seam
    cw = int(round(1080 / ch * 1080 / 2) * 2)  # crop width in the 1920x1080 camera for a 1080 x ch box
    cxx = int(max(0, min(1920 - cw, face_x * 1920 - cw / 2)))
    f.append(f"[C4]crop={cw}:1080:{cxx}:0,scale=1080:{ch}[Cv]")
    f.append(f"[V1][Cv]overlay=x=0:y={seam}[V2]")
    f.append(f"[V2]drawbox=x=0:y={seam - 3}:w=1080:h=6:color={acc}:t=fill[V3]")
    fw = int(round(1080 * 1080 / 1920 / 2) * 2)
    fx = int(max(0, min(1920 - fw, face_x * 1920 - fw / 2)))
    # full camera, zoomed out like the brand's "medium" vertical framing: a 4:5 shot of the speaker
    # over a blurred, darkened copy of the same frame (no black bars, face not filling the screen)
    zw = 864
    zx = int(max(0, min(1920 - zw, face_x * 1920 - zw / 2)))
    f.append("[C3]split=2[C3f][C3b]")
    f.append(f"[C3b]crop={fw}:1080:{fx}:0,scale=270:480,boxblur=10:3,scale=1080:1920,"
             f"eq=brightness=-0.12:saturation=0.85[Cfb]")
    f.append(f"[C3f]crop={zw}:1080:{zx}:0,scale=1080:1350:flags=lanczos[Cff]")
    f.append(f"[Cfb][Cff]overlay=x=0:y={int((1920 - 1350) * 0.4)}[Cf]")
    f.append(f"[V3][Cf]overlay=enable='{cam_on}'[V]")
    f.append("[A]asplit=2[AL][AV]")
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "60",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    land_tmp, vert_tmp = land.with_suffix(".part.mp4"), vert.with_suffix(".part.mp4")
    args += ["-filter_complex", ";".join(f), "-map", "[L]", "-map", "[AL]", *enc, "-t", f"{total:.3f}", str(land_tmp),
             "-map", "[V]", "-map", "[AV]", *enc, "-t", f"{total:.3f}", str(vert_tmp)]
    media.run_ffmpeg(args, duration=total, on_progress=progress, cancel=cancel)
    land_tmp.replace(land)
    vert_tmp.replace(vert)
    return land, vert
