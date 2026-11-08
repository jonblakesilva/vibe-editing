"""Speaker tracking for smart crops (9:16, 1:1) and zoom centering.

Frames are streamed from FFmpeg at a low sample rate and small size, so even long
videos use little memory. The camera path uses a dead zone (the crop only moves when
the speaker moves meaningfully) and smoothing, which looks like a human operator
rather than a jittery tracker."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import config, media


def track_faces(src: str | Path, *, start: float = 0.0, duration: float | None = None,
                sample_fps: float = 2.0, width: int = 640) -> list[dict]:
    """Returns [{t, cx, cy, w, h, score}] in normalized 0..1 coordinates (t relative to start)."""
    import cv2
    info = media.probe(src)
    if not info.has_video:
        return []
    h = int(round(width * info.height / info.width / 2) * 2)
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-vf", f"fps={sample_fps},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    if not config.YUNET_MODEL.exists():
        return []
    det = cv2.FaceDetectorYN.create(str(config.YUNET_MODEL), "", (width, h), 0.6, 0.3, 50)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    frame_bytes = width * h * 3
    out, i = [], 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)  # type: ignore[union-attr]
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, width, 3)
            _, faces = det.detect(frame)
            t = i / sample_fps
            if faces is not None and len(faces):
                # largest face = main speaker
                f = max(faces, key=lambda r: r[2] * r[3])
                x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
                out.append({"t": round(t, 3), "cx": (x + fw / 2) / width, "cy": (y + fh / 2) / h,
                            "w": fw / width, "h": fh / h, "score": round(score, 3)})
            i += 1
    finally:
        proc.stdout.close()  # type: ignore[union-attr]
        proc.wait()
    return out


def summarize(faces: list[dict]) -> dict | None:
    if not faces:
        return None
    cx = float(np.median([f["cx"] for f in faces]))
    cy = float(np.median([f["cy"] for f in faces]))
    w = float(np.median([f["w"] for f in faces]))
    h = float(np.median([f["h"] for f in faces]))
    return {"cx": cx, "cy": cy, "w": w, "h": h, "box": {"x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h},
            "coverage": len(faces)}


def camera_path(faces: list[dict], duration: float, *, src_w: int, src_h: int, out_aspect: float,
                dead_zone: float = 0.08, smooth: float = 0.35) -> list[tuple[float, float]]:
    """Keyframes [(t, crop_x_pixels)] for a crop of width src_h*out_aspect."""
    crop_w = min(src_w, int(round(src_h * out_aspect / 2) * 2))
    max_x = src_w - crop_w
    if max_x <= 0:
        return [(0.0, 0.0)]
    if not faces:
        return [(0.0, max_x / 2)]
    target = faces[0]["cx"]
    pos = target
    keys = [(0.0, pos)]
    for f in faces[1:]:
        if abs(f["cx"] - target) > dead_zone:
            target = f["cx"]
        new = pos + (target - pos) * smooth
        if abs(new - keys[-1][1]) > 0.01:
            keys.append((f["t"], new))
        pos = new
    keys.append((duration, pos))
    return [(t, float(np.clip(c * src_w - crop_w / 2, 0, max_x))) for t, c in keys]


def crop_x_expr(keys: list[tuple[float, float]], max_points: int = 120) -> str:
    """Piecewise-linear FFmpeg expression for crop x over time."""
    if len(keys) > max_points:  # thin long paths; the smoothing makes this invisible
        step = len(keys) / max_points
        keys = [keys[int(i * step)] for i in range(max_points)] + [keys[-1]]
    if len(keys) == 1:
        return f"{keys[0][1]:.1f}"
    expr = f"{keys[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        if t1 - t0 <= 1e-3:
            continue
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr
