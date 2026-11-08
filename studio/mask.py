"""'Title behind me': composite a graphic between the background and the speaker.

Uses Google's MediaPipe selfie segmenter (Apache-2.0, runs locally on the CPU) on the
FINISHED frames, only for the seconds the graphic is on screen, then stacks:
background -> graphic -> person cut-out.

Limitations (tell the user): works best with one person and a background that differs
from clothing/hair; fine hair edges are soft; hands or objects held away from the body
may be treated as background; a busy screen recording behind the speaker can confuse it."""
from __future__ import annotations

import os
import subprocess
import threading
import urllib.request
from pathlib import Path

import numpy as np

from . import media

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/"
             "float16/latest/selfie_segmenter.tflite")
MODELS_DIR = Path(os.environ.get("VIBE_MODELS_DIR", Path.home() / "VibeStudio" / "models"))


def available() -> bool:
    try:
        import mediapipe  # noqa: F401
        return True
    except ImportError:
        return False


def model_path() -> Path:
    p = MODELS_DIR / "selfie_segmenter.tflite"
    if not p.exists():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)  # official Google model bucket
        tmp.replace(p)
    return p


def mask_video(src: Path, start: float, duration: float, out: Path, *, width: int, height: int, fps: float,
               cancel: threading.Event | None = None) -> Path:
    """Write a grayscale person-mask video for [start, start+duration] of src (streamed)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(model_path())),
        running_mode=vision.RunningMode.VIDEO, output_confidence_masks=True))
    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", str(src),
                               "-t", f"{duration:.3f}", "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                               "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-c:v", "ffv1", str(out)],
                              stdin=subprocess.PIPE)
    size = width * height * 3
    prev = None
    i = 0
    cover = []
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise media.Cancelled("Cancelled by user")
            buf = reader.stdout.read(size)  # type: ignore[union-attr]
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            res = seg.segment_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame)),
                                        int(i * 1000 / fps))
            m = res.confidence_masks[0].numpy_view().astype(np.float32)
            if m.ndim == 3:
                m = m[..., 0]
            # temporal smoothing removes edge flicker; soft threshold keeps natural edges
            prev = m if prev is None else prev * 0.35 + m * 0.65
            alpha = np.clip((prev - 0.35) / 0.3, 0, 1)
            cover.append(float(alpha[: int(height * 0.4)].mean()))  # how much of the title zone is person
            writer.stdin.write((alpha * 255).astype(np.uint8).tobytes())  # type: ignore[union-attr]
            i += 1
    finally:
        reader.stdout.close()  # type: ignore[union-attr]
        reader.wait()
        writer.stdin.close()  # type: ignore[union-attr]
        writer.wait()
        seg.close()
    if writer.returncode != 0 or i == 0:
        raise media.MediaError("Could not build the subject mask.")
    mask_video.last_coverage = float(np.mean(cover)) if cover else 0.0
    return out


def composite_behind(video: Path, items: list[dict], work: Path, *, fps: float,
                     cancel: threading.Event | None = None, notes: list | None = None) -> Path:
    """Re-composite `video` in place with each graphic placed behind the speaker. If the
    speaker fills most of the title zone (tight vertical crops), the title would vanish, so
    it is placed in front instead and a note explains why."""
    info = media.probe(video)
    W, H = info.width, info.height
    inputs = ["-i", str(video)]
    filt = []
    v = "[0:v]"
    k = 1
    for n, g in enumerate(items):
        st, d = g["start"], g["duration"]
        mpath = work / f"mask_{video.stem}_{n}.mkv"
        mask_video(video, st, d, mpath, width=W, height=H, fps=fps, cancel=cancel)
        front = mask_video.last_coverage > 0.55
        if front and notes is not None:
            notes.append(f"{g.get('id', 'title')}: the speaker fills {mask_video.last_coverage:.0%} of the title area "
                         f"in this {W}x{H} frame, so the title was placed in front to stay readable.")
        inputs += ["-i", str(g["path"]), "-i", str(mpath)]
        gi, mi = k, k + 1
        k += 2
        filt.append(f"{v}split=2[bg{n}][src{n}]")
        filt.append(f"[{gi}:v]setpts=PTS-STARTPTS+{st:.3f}/TB,scale={W}:{H}[g{n}]")
        filt.append(f"[bg{n}][g{n}]overlay=enable='between(t,{st:.3f},{st + d:.3f})':eof_action=pass[bt{n}]")
        filt.append(f"[src{n}]trim=start={st:.3f}:duration={d:.3f},setpts=PTS-STARTPTS[fg{n}]")
        filt.append(f"[{mi}:v]format=gray,setpts=PTS-STARTPTS[m{n}]")
        filt.append(f"[fg{n}][m{n}]alphamerge,setpts=PTS+{st:.3f}/TB[p{n}]")
        if front:
            filt.append(f"[bt{n}]null[v{n}]")
            filt.append(f"[p{n}]nullsink")
        else:
            filt.append(f"[bt{n}][p{n}]overlay=enable='between(t,{st:.3f},{st + d:.3f})':eof_action=pass[v{n}]")
        v = f"[v{n}]"
    filt.append(f"{v}format=yuv420p[vout]")
    tmp = video.with_name(video.stem + ".behind.part.mp4")
    script = work / f"{video.stem}.behind.txt"
    script.write_text(";\n".join(filt), encoding="utf-8")
    media.run_ffmpeg([*inputs, "-filter_complex_script", str(script), "-map", "[vout]", "-map", "0:a",
                      "-r", str(fps), *media.video_encoder("final"), "-c:a", "copy", str(tmp)],
                     duration=info.duration, cancel=cancel)
    tmp.replace(video)
    return video
