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

import subprocess
import threading
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw

from . import media

FPS = "30000/1001"
LAND = (1920, 1080)
VERT = (1080, 1920)

# Vertical screen panel: how much of the screen's width the un-zoomed crop shows
# (the "when content allows" baseline from the owner's note) and how far the
# content-aware pan/zoom is allowed to zoom in past that baseline.
SCREEN_FOCUS_MAX_WIDTH = 0.45
SCREEN_FOCUS_MIN_WIDTH = 0.20


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


# ---------------------------------------------------------------- smart screen focus
#
# The vertical screen panel used to be a fixed centre crop (`vertical_screen_width` of the
# screen, dead centre), so content off to a side (a keyword list, a chart's values) was cut
# off or too small to read. These functions find where the meaningful content actually is
# (frame differencing for cursor/content activity, plus edge/text density) and build smooth,
# held pan/zoom keyframes for it; `focus_box_series` then turns those into the pixel-space
# crop keyframes `build_masters` feeds through the existing `_keyframes()` expression builder.

def _energy_span(energy: "np.ndarray", spread: float = 1.4) -> tuple[int, int]:
    """Smallest-ish window (mean +/- `spread` std) containing most of a 1-D energy profile's
    weight - a concentrated hot spot (a keyword list on the left) gives a narrow span near its
    position; a profile with no clear hot spot gives a wide, centred span."""
    n = len(energy)
    total = float(energy.sum())
    if total <= 1e-6:
        return 0, n - 1
    idx = np.arange(n)
    mean = float((idx * energy).sum() / total)
    var = float(((idx - mean) ** 2 * energy).sum() / total)
    std = max(var ** 0.5, 1.0)
    lo = max(0, int(round(mean - spread * std)))
    hi = min(n - 1, int(round(mean + spread * std)))
    return lo, hi


def frame_hotspot(gray: "np.ndarray", prev_gray: "np.ndarray | None" = None, *, ignore_top: float = 0.08) -> dict:
    """Normalized {cx, cy, spread} of the most active/content-dense region of one grayscale
    frame, ignoring the top `ignore_top` fraction (browser chrome). Combines motion (frame
    difference from the previous sample, weighted higher) with edge/text density, so cursor
    activity and static-but-detailed content (a chart, a keyword table) both score. `spread`
    is the hot region's width as a fraction of the frame - narrow for a concentrated feature,
    wide (near 1.0) when activity is spread across the whole frame."""
    h, w = gray.shape[:2]
    top = int(round(h * ignore_top))
    region = gray[top:, :].astype(np.float32)
    gx = np.abs(np.diff(region, axis=1, prepend=region[:, :1]))
    gy = np.abs(np.diff(region, axis=0, prepend=region[:1, :]))
    score = gx + gy
    if prev_gray is not None:
        diff = np.abs(region - prev_gray[top:, :].astype(np.float32))
        score = score + diff * 2.0
    col = score.sum(axis=0)
    row = score.sum(axis=1)
    if col.sum() <= 1e-6:
        return {"cx": 0.5, "cy": 0.5 + ignore_top / 2, "spread": 1.0}
    x0, x1 = _energy_span(col)
    y0, y1 = _energy_span(row)
    cx = (x0 + x1) / 2 / w
    cy = (top + (y0 + y1) / 2) / h
    spread = max((x1 - x0) / w, 0.05)
    return {"cx": float(cx), "cy": float(cy), "spread": float(spread)}


def _zoom_for_spread(spread: float, *, max_width: float = SCREEN_FOCUS_MAX_WIDTH,
                     min_width: float = SCREEN_FOCUS_MIN_WIDTH) -> float:
    """A concentrated hot spot (small `spread`) gets a tighter crop (higher zoom), clamped so
    the crop width never exceeds `max_width` of the screen (the "when content allows" baseline)
    or goes narrower than `min_width` (so text never zooms past legible into pixelated)."""
    desired = min(max_width, max(min_width, spread * 1.6))
    return round(max_width / desired, 4)


def auto_screen_focus_keyframes(screen_path: str | Path, duration: float, *, sample_every: float = 0.75,
                                ignore_top: float = 0.08, width: int = 480) -> list[dict]:
    """Samples `screen_path` every `sample_every` seconds and returns raw per-sample focus
    detections [{t, cx, cy, zoom}] (t in this take's own time) from frame_hotspot. Feed into
    smooth_focus_path for the final held, eased keyframes. Returns [] if the file can't be
    read (build_masters then falls back to the fixed centre crop for this take)."""
    try:
        info = media.probe(screen_path)
    except Exception:
        return []
    if not info.has_video or duration <= 0 or not info.width or not info.height:
        return []
    h = max(2, int(round(width * info.height / info.width / 2) * 2))
    frame_bytes = width * h * 3
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(screen_path),
            "-t", f"{duration:.3f}", "-vf", f"fps={1 / sample_every:.4f},scale={width}:{h}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    except OSError:
        return []
    out, i, prev_gray = [], 0, None
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)  # type: ignore[union-attr]
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, width, 3)
            gray = frame.mean(axis=2)
            spot = frame_hotspot(gray, prev_gray, ignore_top=ignore_top)
            out.append({"t": round(i * sample_every, 3), "cx": spot["cx"], "cy": spot["cy"],
                       "zoom": _zoom_for_spread(spot["spread"])})
            prev_gray = gray
            i += 1
    finally:
        proc.stdout.close()  # type: ignore[union-attr]
        proc.wait()
    return out


def smooth_focus_path(samples: list[dict], *, duration: float, hold: float = 1.5, dead_zone: float = 0.05,
                      ease: float = 0.3, default_cx: float = 0.5, default_cy: float = 0.5,
                      default_zoom: float = 1.0) -> list[dict]:
    """Smooth raw per-sample {t, cx, cy, zoom} detections into held, eased keyframes: a new
    target is only adopted when it differs from the current one by more than `dead_zone`
    (normalized) AND at least `hold` seconds have passed since the last change (so a brief
    flicker of activity doesn't yank the crop around), then the position eases toward that
    target rather than jumping - no jitter, holding still for `hold` seconds at a minimum."""
    if not samples:
        return [{"t": 0.0, "cx": default_cx, "cy": default_cy, "zoom": default_zoom}]
    samples = sorted(samples, key=lambda s: s["t"])
    first = samples[0]
    pos = {"cx": first["cx"], "cy": first["cy"], "zoom": first["zoom"]}
    target = dict(pos)
    keys = [{"t": 0.0, **pos}]
    last_change = first["t"]
    for s in samples:
        moved = any(abs(s[k] - target[k]) > dead_zone for k in ("cx", "cy", "zoom"))
        if moved and s["t"] - last_change >= hold:
            target = {"cx": s["cx"], "cy": s["cy"], "zoom": s["zoom"]}
            last_change = s["t"]
        pos = {k: pos[k] + (target[k] - pos[k]) * ease for k in pos}
        if any(abs(pos[k] - keys[-1][k]) > 0.01 for k in pos):
            keys.append({"t": round(s["t"], 3), **{k: round(v, 4) for k, v in pos.items()}})
    keys.append({"t": round(max(duration, keys[-1]["t"]), 3), **{k: round(v, 4) for k, v in pos.items()}})
    return keys


def merge_focus_keyframes(auto: list[dict], manual: list[dict] | None, *, window: float = 0.4) -> list[dict]:
    """Manual `screen_focus` keyframes (from the plan or project, e.g. placed where the owner's
    pen marks show what matters) override nearby automatic ones: automatic keyframes within
    `window` seconds of a manual one are dropped so the manual point wins there; everywhere
    else the automatic path is kept."""
    if not manual:
        return auto
    manual = sorted(({"t": float(m["t"]), "cx": float(m["cx"]), "cy": float(m["cy"]),
                      "zoom": float(m.get("zoom", 1.0))} for m in manual), key=lambda m: m["t"])
    out = [a for a in auto if not any(abs(a["t"] - m["t"]) <= window for m in manual)]
    out += manual
    return sorted(out, key=lambda k: k["t"])


def offset_keyframes(keys: list[dict], offset: float) -> list[dict]:
    """Shift a take-local focus keyframe list into the concatenated master's timeline."""
    return [{**k, "t": round(k["t"] + offset, 3)} for k in keys]


def _thin_keyframes(keys: list[dict], max_points: int = 80) -> list[dict]:
    """Cap the number of keyframes fed into the ffmpeg crop expression: a long recording with
    constant on-screen activity can produce hundreds of held positions, and ffmpeg's expression
    parser rejects an `if(lt(t,...` chain nested much past ~98 levels deep ("Missing ')' or too
    many args") - 80 leaves headroom. The smoothing already makes in-between points redundant,
    so thinning is invisible."""
    if len(keys) <= max_points:
        return keys
    step = len(keys) / max_points
    thinned = [keys[int(i * step)] for i in range(max_points)]
    if keys[-1] not in thinned:
        thinned.append(keys[-1])
    return thinned


def focus_box_series(keyframes: list[dict], iw: float, ih: float, *, base_width_frac: float = SCREEN_FOCUS_MAX_WIDTH,
                     min_zoom: float = 1.0, max_zoom: float = SCREEN_FOCUS_MAX_WIDTH / SCREEN_FOCUS_MIN_WIDTH
                     ) -> dict[str, list[tuple[float, float]]]:
    """Normalized {t, cx, cy, zoom} focus keyframes -> per-axis pixel keyframes (w, h, x, y)
    for a crop box that keeps the baseline's aspect ratio (base_width_frac * iw : ih) at every
    zoom level, clamped to `[min_zoom, max_zoom]` and kept fully on-frame (x, y clamped so the
    box never runs past the screen's edges)."""
    base_w, base_h = iw * base_width_frac, ih
    series: dict[str, list[tuple[float, float]]] = {"w": [], "h": [], "x": [], "y": []}
    for k in sorted(keyframes, key=lambda k: k["t"]):
        zoom = min(max_zoom, max(min_zoom, float(k.get("zoom", 1.0))))
        w, h = base_w / zoom, base_h / zoom
        x = min(max(0.0, k["cx"] * iw - w / 2), max(0.0, iw - w))
        y = min(max(0.0, k["cy"] * ih - h / 2), max(0.0, ih - h))
        t = float(k["t"])
        series["w"].append((t, w))
        series["h"].append((t, h))
        series["x"].append((t, x))
        series["y"].append((t, y))
    return series


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
                  screen_crop_bottom: float = 0.045, vertical_screen_width: float = SCREEN_FOCUS_MAX_WIDTH,
                  screen_x: list[tuple[float, float]] | None = None, screen_focus: list[dict] | None = None,
                  auto_screen_focus: bool = True,
                  limit: float | None = None, progress: Callable[[float], None] | None = None,
                  cancel: threading.Event | None = None) -> tuple[Path, Path]:
    """`screen_focus` (optional): manual pan/zoom keyframes for the vertical screen panel, in
    the master's own (concatenated) timeline - [{"t", "cx", "cy", "zoom"}], cx/cy normalized to
    the screen recording (0..1), zoom >= 1. These override the automatic content-aware pan/zoom
    (see auto_screen_focus_keyframes) near their own times; set auto_screen_focus=False to skip
    the automatic pass entirely and use only the fixed baseline crop plus any manual keyframes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    land, vert = out_dir / "layout_landscape.mp4", out_dir / "layout_vertical.mp4"
    durs = [min(media.probe(c).duration, media.probe(s).duration) for c, s in takes]
    if limit:  # quick layout test: only the first `limit` seconds of each take
        durs = [min(d, limit) for d in durs]
    total = sum(durs)
    screen_info = media.probe(takes[0][1]) if takes else None
    screen_w = screen_info.width if screen_info and screen_info.width else 1920
    screen_h = (screen_info.height if screen_info and screen_info.height else 1080) * (1 - screen_crop_bottom)
    auto_focus: list[dict] = []
    if auto_screen_focus:
        t0 = 0.0
        for (_, s), d in zip(takes, durs):
            auto_focus += offset_keyframes(auto_screen_focus_keyframes(s, d), t0)
            t0 += d
        auto_focus = smooth_focus_path(auto_focus, duration=total)
    focus_keys = _thin_keyframes(merge_focus_keyframes(auto_focus, screen_focus))
    focus_series = focus_box_series(focus_keys, screen_w, screen_h, base_width_frac=vertical_screen_width)
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
    # content-aware pan/zoom: w/h/x/y are piecewise-linear in `t`, re-evaluated every frame
    # (crop expressions referencing `t` are frame-evaluated automatically) so the crop follows
    # wherever the real content is instead of a fixed centre window; focus_series falls back to
    # the old centred, un-zoomed box when there's no signal
    f.append(f"[S2]crop=w='{_keyframes(focus_series['w'], default=screen_w * vertical_screen_width)}':"
             f"h='{_keyframes(focus_series['h'], default=screen_h)}':"
             f"x='{_keyframes(focus_series['x'], default=(screen_w - screen_w * vertical_screen_width) / 2)}':"
             f"y='{_keyframes(focus_series['y'], default=0.0)}',"
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
