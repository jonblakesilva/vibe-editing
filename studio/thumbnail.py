"""Branded YouTube thumbnails (1280x720).

Picks sharp frames where the speaker's face is clear, cuts the speaker out with the local
MediaPipe selfie segmenter (falls back to the plain frame), and lays a big brand-font title
beside them with the Remotion "Thumbnail" still template. Writes JPGs to exports/thumbnails.
The title is the user's choice (or the plan topic); nothing is claimed that wasn't said."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from . import media, motion
from . import plan as plan_mod
from . import project as proj_mod

W, H = 1280, 720


def _frame(src: str, t: float) -> np.ndarray | None:
    info = media.probe(src)
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    n = info.width * info.height * 3
    if r.returncode != 0 or len(r.stdout) < n:
        return None
    return np.frombuffer(r.stdout[:n], np.uint8).reshape(info.height, info.width, 3)


def _sharpness(img: np.ndarray) -> float:
    g = img.mean(axis=2)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def candidate_times(pid: str, plan: dict, n: int = 3, pool: int = 18) -> list[float]:
    """Frames in the short pauses between words (mouth at rest, no mid-word face), in kept
    footage where the camera shows the speaker; the sharpest few are used."""
    from .pipeline import get_transcript
    tl = plan_mod.timeline(plan)
    cams = plan["source"].get("cam_ranges")
    words = get_transcript(pid)["words"]
    gaps = [(a["end"] + b["start"]) / 2 for a, b in zip(words, words[1:])
            if 0.25 <= b["start"] - a["end"] <= 1.5 and tl.to_edit((a["end"] + b["start"]) / 2) is not None
            and (not cams or any(x <= a["end"] <= y for x, y in cams))]
    if len(gaps) >= n:
        step = max(1, len(gaps) // pool)
        return gaps[::step][:pool]
    return _face_times(pid, plan, n)


def _face_times(pid: str, plan: dict, n: int = 3) -> list[float]:
    from .pipeline import get_faces
    tl = plan_mod.timeline(plan)
    cams = plan["source"].get("cam_ranges")
    faces = [f for f in get_faces(pid) if tl.to_edit(f["t"]) is not None]
    if cams:  # screen + camera: only where the camera is full-screen
        faces = [f for f in faces if any(a <= f["t"] <= b for a, b in cams)]
    faces = [f for f in faces if f.get("w", 0) > 0.08] or faces
    if not faces:
        return [s for s, _ in tl.segments[:n]]
    faces.sort(key=lambda f: f["t"])
    chunk = max(1, len(faces) // n)
    picks = []
    for i in range(n):
        group = faces[i * chunk:(i + 1) * chunk] or faces[-chunk:]
        picks.append(max(group, key=lambda f: f.get("w", 0))["t"])
    return sorted(set(round(t, 2) for t in picks))


def cutout(img: np.ndarray, out: Path) -> Path:
    """Person cut-out as a transparent PNG (plain frame if segmentation is unavailable)."""
    from PIL import Image
    from . import mask as mask_mod
    alpha = None
    if mask_mod.available():
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
            seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=str(mask_mod.model_path())),
                running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True))
            m = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)))
            a = m.confidence_masks[0].numpy_view().astype(np.float32)
            a = a[..., 0] if a.ndim == 3 else a
            alpha = (np.clip((a - 0.35) / 0.3, 0, 1) * 255).astype(np.uint8)
            seg.close()
        except Exception:  # noqa: BLE001 - fall back to the plain frame
            alpha = None
    im = Image.fromarray(img).convert("RGBA")
    if alpha is not None:
        # keep only the largest blob (the speaker), drop stray bits of background
        from scipy import ndimage
        lab, n = ndimage.label(alpha > 128)
        if n > 1:
            sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
            alpha = np.where(lab == (int(np.argmax(sizes)) + 1), alpha, 0).astype(np.uint8)
        im.putalpha(Image.fromarray(alpha))
        ys, xs = np.nonzero(alpha > 128)
        if len(xs):  # head-and-shoulders crop centred on the head, a little air above it
            top = max(0, ys.min() - int(img.shape[0] * 0.04))
            head = xs[ys < ys.min() + (img.shape[0] - ys.min()) * 0.3]
            cx = int(np.median(head)) if len(head) else int(np.median(xs))
            half = int((img.shape[0] - top) * 0.55)
            im = im.crop((max(0, cx - half), top, min(img.shape[1], cx + half), img.shape[0]))
        im = _polish(im)
    im.save(out)
    return out


def _polish(im):
    """Thumbnail treatment for a webcam cut-out: smoother edges, brighter, punchier colour,
    a little sharpening, and a clean white outline (hides any rough mask edge)."""
    from PIL import Image, ImageEnhance, ImageFilter
    rgb, a = im.convert("RGB"), im.getchannel("A")
    a = a.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.6))  # tuck in + feather
    rgb = ImageEnhance.Brightness(rgb).enhance(1.14)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.12)
    rgb = ImageEnhance.Color(rgb).enhance(1.12)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
    pad = 16
    w, h = im.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad), (0, 0, 0, 0))
    ring = Image.new("L", canvas.size, 0)
    ring.paste(a, (pad, pad))
    ring = ring.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(1.2))
    canvas.paste(Image.new("RGBA", canvas.size, (255, 255, 255, 255)), (0, 0), ring)
    person = rgb.convert("RGBA")
    person.putalpha(a)
    canvas.alpha_composite(person, (pad, pad))
    return canvas


def screen_card(plan: dict, out: Path) -> Path | None:
    """For screen + camera projects: a frame of the screen share, used as a card behind the speaker."""
    if plan["source"].get("layout") != "screencam":
        return None
    tl = plan_mod.timeline(plan)
    cams = plan["source"].get("cam_ranges") or []
    split = [(a, b) for a, b in tl.segments if not any(x <= (a + b) / 2 <= y for x, y in cams)]
    if not split:
        return None
    a, b = max(split, key=lambda s: s[1] - s[0])
    img = _frame(plan["source"]["path"], a + (b - a) * 0.4)
    if img is None:
        return None
    from PIL import Image
    Image.fromarray(img).save(out, quality=92)
    return out


def make(pid: str, *, title: str | None = None, highlight: str | None = None, times: list[float] | None = None,
         count: int = 3, photos: list[str] | None = None) -> list[Path]:
    """photos: posed thumbnail photos to use instead of video frames (best results)."""
    proj = proj_mod.load(pid)
    d = proj_mod.project_dir(proj["id"])
    plan = plan_mod.load(d / "plan.json")
    title = (title or plan["summary"].get("topic") or proj["name"]).strip()
    out_dir = d / "exports" / "thumbnails"
    work = d / "work" / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    src = plan["source"]["path"]
    times = times or ([] if photos else candidate_times(pid, plan, count))
    if photos:
        from PIL import Image
        frames = [(0.0, np.asarray(Image.open(ph).convert("RGB"))) for ph in photos]
    else:
        frames = [(t, f) for t in times if (f := _frame(src, t)) is not None]
    frames.sort(key=lambda x: -(_sharpness(x[1]) * (0.6 + x[1].mean() / 255)))
    results = []
    for k, (t, img) in enumerate(frames[:count], start=1):
        person = cutout(img, work / f"person_{k}.png")
        bg = work / f"frame_{k}.jpg"
        from PIL import Image
        Image.fromarray(img).save(bg, quality=92)
        card = screen_card(plan, work / "screen_card.jpg")
        props = {**motion.brand_props(plan), **motion.stage_images({"image": str(person)}),
                 "card": motion.stage_images({"image": str(card)})["image"] if card else "",
                 "background": motion.stage_images({"image": str(bg)})["image"],
                 "title": title, "highlight": highlight or "", "width": W, "height": H, "fps": 30,
                 "durationInFrames": 1}
        pf = work / f"thumb_{k}.props.json"
        pf.write_text(json.dumps(props), encoding="utf-8")
        png = work / f"thumb_{k}.png"
        r = subprocess.run([str(motion.remotion_bin()), "still", "src/index.ts", "Thumbnail", str(png),
                            f"--props={pf}", "--frame=0", "--log=error", f"--width={W}", f"--height={H}"],
                           cwd=motion.REMOTION_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not png.exists():
            raise RuntimeError(f"Thumbnail render failed:\n{r.stderr[-1200:]}")
        jpg = out_dir / f"thumbnail_{k}.jpg"
        Image.open(png).convert("RGB").save(jpg, quality=92)  # YouTube limit is 2 MB; this lands well under
        results.append(jpg)
    return results
