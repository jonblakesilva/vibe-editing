"""Branded YouTube thumbnails (1280x720 landscape, or 1080x1920 for the "shorts-cover"
layout).

Picks sharp frames where the speaker's face is clear, cuts the speaker out with the local
rembg/MediaPipe segmenter (falls back to the plain frame), and lays out one of several
proof-driven layouts -- modelled on the high-performing creators the owner likes -- with the
Remotion "Thumbnail" still template. Writes JPGs to exports/thumbnails.

The title, amounts and checklist items are always the caller's words: this module only
lays out what it is given, it never invents a number or a claim."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from . import media, motion
from . import plan as plan_mod
from . import project as proj_mod

W, H = 1280, 720
SHORTS_W, SHORTS_H = 1080, 1920

LAYOUTS = ("face-number", "payment", "checklist", "screenshot", "two-person", "clean-white", "shorts-cover")
CHIPS = ("maps_pin",)


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


def fit_title(text: str, max_width: int, max_height: int, *, min_size: int = 40, max_size: int = 160,
              char_width: float = 0.40, line_height: float = 1.08) -> dict:
    """Largest size (px) of the bundled heavy condensed display font (Anton) at which
    `text` wraps to fit inside max_width x max_height.

    The width estimate (`char_width` * size per character) is a simple, font-specific
    average for Anton's heavy condensed caps -- measured directly off a rendered sample
    ("WIDE TEST LINE" at 150px renders ~0.37 * len * size wide; 0.40 keeps a small safety
    margin for letter mixes with more wide characters) -- good enough to pick a size that
    fills the box without the guesswork of an actual glyph measurement in Python. Words are wrapped,
    never cut, so a long title still renders in full, just smaller and on more lines; it
    only drops below `min_size` if even that doesn't fit, in which case `min_size` wins
    and the caller should shorten the text or widen the box.

    Returns {"size": int, "lines": [str, ...]} with lines already upper-cased, matching
    the reference thumbnails' all-caps treatment."""
    words = text.upper().split()
    if not words:
        return {"size": max_size, "lines": [""]}

    def wrap(size: int) -> list[str]:
        lines: list[str] = []
        line: list[str] = []
        for w in words:
            trial = line + [w]
            if len(" ".join(trial)) * size * char_width <= max_width or not line:
                line = trial
            else:
                lines.append(" ".join(line))
                line = [w]
        if line:
            lines.append(" ".join(line))
        return lines

    size = max_size
    while size > min_size:
        lines = wrap(size)
        if len(lines) * size * line_height <= max_height:
            return {"size": size, "lines": lines}
        size -= 2
    return {"size": min_size, "lines": wrap(min_size)}


def _normalize_items(items: list) -> list[dict]:
    """Checklist rows as {"text", "done"}. Accepts plain strings -- optionally ending (or
    starting) with a check/cross glyph, e.g. "Follow-up ✓" or "More leads ✗" -- or
    {"text": ..., "done": bool} dicts. The owner's own wording is kept as-is; nothing here
    adds or removes a claim, only a layout decision (which row gets the highlighted tick)."""
    marks = (("✓", True), ("✔", True), ("✗", False), ("✘", False), ("✕", False))
    out = []
    for raw in items:
        if isinstance(raw, dict):
            out.append({"text": str(raw.get("text", "")).strip(), "done": bool(raw.get("done", False))})
            continue
        text = str(raw).strip()
        done = False
        for mark, val in marks:
            if text.endswith(mark) or text.startswith(mark):
                done, text = val, text.replace(mark, "").strip()
                break
        out.append({"text": text, "done": done})
    return out


def _face_crop_box(face: tuple[float, float, float, float], img_w: int, img_h: int,
                    mask_top: float | None = None) -> tuple[int, int, int, int]:
    """Head-and-shoulders crop (left, top, right, bottom) around a detected face box.

    The crop always bottoms out at the image's bottom edge (the speaker bleeds off the
    frame, per the reference thumbnails), and `top` is pulled up just enough to keep the
    hair in frame while still letting a close face fill most of the crop -- for a face
    that fills a normal amount of a close headshot, that comfortably clears the "at least
    40% of the crop's height" rule. `mask_top` (the topmost unmasked pixel row, if a
    person cut-out is available) can pull `top` down further when the matte starts lower
    than the face box alone would suggest."""
    fx, fy, fw, fh = face
    cx = fx + fw / 2
    top = fy - fh * 1.1
    if mask_top is not None:
        top = max(top, mask_top - img_h * 0.04)
    top = min(top, fy - fh * 0.45)  # always keep the hair
    top = max(0.0, top)
    half = (img_h - top) * 0.55
    left = max(0.0, cx - half)
    right = min(float(img_w), cx + half)
    return int(left), int(top), int(right), img_h


def cutout(img: np.ndarray, out: Path) -> Path:
    """Person cut-out as a transparent PNG (plain frame if segmentation is unavailable)."""
    from PIL import Image
    from . import mask as mask_mod
    alpha = _rembg_alpha(img)
    if alpha is None and mask_mod.available():
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
        if len(xs):  # head-and-shoulders crop centred on the FACE (a raised arm must not steer it)
            face = _face_box(img)
            if face:
                left, top, right, bottom = _face_crop_box(face, img.shape[1], img.shape[0], mask_top=float(ys.min()))
            else:
                top = max(0, ys.min() - int(img.shape[0] * 0.04))
                head = xs[ys < ys.min() + (img.shape[0] - ys.min()) * 0.3]
                cx = int(np.median(head)) if len(head) else int(np.median(xs))
                half = int((img.shape[0] - top) * 0.55)
                left, right, bottom = max(0, cx - half), min(img.shape[1], cx + half), img.shape[0]
            im = im.crop((left, top, right, bottom))
        im = _polish(im)
    im.save(out)
    return out


def _rembg_alpha(img: np.ndarray) -> np.ndarray | None:
    """Crisp, hair-level person matte with BiRefNet-portrait via rembg (MIT; model ~1 GB,
    downloaded once to ~/VibeStudio/models/rembg). None if rembg isn't installed."""
    try:
        import os
        from . import config
        os.environ.setdefault("U2NET_HOME", str(config.DATA_HOME / "models" / "rembg"))
        from PIL import Image
        from rembg import new_session, remove
    except ImportError:
        return None
    global _REMBG
    try:
        _REMBG
    except NameError:
        _REMBG = new_session("birefnet-portrait")
    out = remove(Image.fromarray(img), session=_REMBG, only_mask=True, post_process_mask=False)
    return np.asarray(out.convert("L"))


def _face_box(img: np.ndarray) -> tuple[float, float, float, float] | None:
    """Largest face (x, y, w, h) in pixels, using the YuNet detector already used for reframing."""
    import cv2
    from . import config
    if not config.YUNET_MODEL.exists():
        return None
    h, w = img.shape[:2]
    scale = 640 / max(h, w)
    small = cv2.resize(img[..., ::-1], (int(w * scale), int(h * scale)))
    det = cv2.FaceDetectorYN.create(str(config.YUNET_MODEL), "", (small.shape[1], small.shape[0]), 0.6, 0.3, 50)
    _, faces = det.detect(small)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda r: r[2] * r[3])
    return float(f[0]) / scale, float(f[1]) / scale, float(f[2]) / scale, float(f[3]) / scale


def _polish(im, *, outline: bool = False):
    """Thumbnail treatment for a webcam cut-out: smoother edges, brighter, punchier colour,
    a little sharpening, and -- by default -- a soft dark contact shadow rather than a thick
    white outline (the reference thumbnails use at most a subtle rim light or shadow to
    separate the speaker from the background; a heavy white ring reads as a cheap sticker).
    Pass `outline=True` for the old white-ring treatment if a particular brand wants it."""
    from PIL import Image, ImageEnhance, ImageFilter
    rgb, a = im.convert("RGB"), im.getchannel("A")
    rgb = ImageEnhance.Brightness(rgb).enhance(1.06)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.10)
    rgb = ImageEnhance.Color(rgb).enhance(1.10)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60, threshold=2))
    pad = 24 if outline else 16
    w, h = im.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad), (0, 0, 0, 0))
    mask = Image.new("L", canvas.size, 0)
    mask.paste(a, (pad, pad))
    edge = mask.point(lambda v: 255 if v > 110 else 0)
    if outline:
        ring = edge.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(0.6))
        canvas.paste(Image.new("RGBA", canvas.size, (255, 255, 255, 255)), (0, 0), ring)
    else:
        # soft dark contact shadow, offset down-right a touch -- just enough depth to lift
        # the cut-out off the background without drawing a line around the person
        shadow_mask = edge.filter(ImageFilter.GaussianBlur(10))
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 150)), (5, 9), shadow_mask)
        canvas.alpha_composite(shadow)
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


def _cutout_photo(path: str, out: Path) -> Path:
    """Cut out a single posed photo (used for `photo2` and standalone `screenshot`-adjacent
    stills), the same treatment the video-frame path gets."""
    from PIL import Image, ImageOps
    img = np.asarray(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))
    return cutout(img, out)


def make(pid: str, *, title: str | None = None, highlight: str | None = None, times: list[float] | None = None,
         count: int = 3, photos: list[str] | None = None, out_dir: Path | None = None,
         name: str = "thumbnail", layout: str = "face-number", items: list | None = None,
         amount: str | None = None, photo2: str | None = None, screenshot: str | None = None,
         screenshot_box: tuple[float, float, float, float] | None = None,
         chip: str | None = None) -> list[Path]:
    """photos: posed thumbnail photos to use instead of video frames (best results).

    layout: "face-number" (default, big edge-cropped face + title), "payment" (+ a
    payment-received card for `amount`), "checklist" (+ 2-3 `items`, one ticked),
    "screenshot" (+ a tilted `screenshot` card, optionally circled with `screenshot_box`
    = (x, y, w, h) in 0-1 fractions of the screenshot), "two-person" (a second speaker from
    `photo2`), "clean-white" (face-number on a plain light background) or "shorts-cover"
    (1080x1920: screen/background on top, face on the bottom, title on the seam).
    `chip`: an optional small icon chip next to the title, e.g. "maps_pin"."""
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown thumbnail layout {layout!r}; choose one of: {', '.join(LAYOUTS)}")
    if layout == "payment" and not amount:
        raise ValueError('layout="payment" needs an `amount` (e.g. "$30,000+"); nothing is invented here.')
    if layout == "checklist" and not items:
        raise ValueError('layout="checklist" needs `items` (2-3 strings, e.g. ["More leads ✗", "Follow-up ✓"]).')
    if layout == "two-person" and not photo2:
        raise ValueError('layout="two-person" needs `photo2` (the second speaker\'s photo).')
    if layout == "screenshot" and not screenshot:
        raise ValueError('layout="screenshot" needs `screenshot` (the image/frame to feature).')
    if chip is not None and chip not in CHIPS:
        raise ValueError(f"Unknown chip {chip!r}; choose one of: {', '.join(CHIPS)}")

    proj = proj_mod.load(pid)
    d = proj_mod.project_dir(proj["id"])
    plan = plan_mod.load(d / "plan.json")
    title = (title or plan["summary"].get("topic") or proj["name"]).strip()
    out_dir = Path(out_dir) if out_dir else d / "exports" / "thumbnails"
    work = d / "work" / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    src = plan["source"]["path"]
    out_w, out_h = (SHORTS_W, SHORTS_H) if layout == "shorts-cover" else (W, H)

    # text box the title must auto-fit into without ever touching the face OR a proof
    # element -- these max_height numbers match the reserved bands in Thumbnail.tsx's
    # BANDS (studio/motion/remotion/src/templates/Thumbnail.tsx): payment/checklist
    # reserve room below the title for their card, screenshot reserves room above it.
    _title_budget = {"payment": 380, "checklist": 300, "screenshot": 240}
    if layout == "shorts-cover":
        fit = fit_title(title, max_width=out_w - 200, max_height=240, min_size=52, max_size=108)
    elif layout == "two-person":
        fit = fit_title(title, max_width=560, max_height=out_h - 220, min_size=44, max_size=140)
    else:
        fit = fit_title(title, max_width=560, max_height=_title_budget.get(layout, out_h - 200),
                         min_size=40, max_size=150)

    checklist = _normalize_items(items) if items else None
    photo2_path = None
    if layout == "two-person" and photo2:
        photo2_path = _cutout_photo(photo2, work / "person2.png")
    screenshot_staged = str(Path(screenshot).expanduser()) if screenshot else None

    times = times or ([] if photos else candidate_times(pid, plan, count))
    if photos:
        from PIL import Image, ImageOps
        frames = [(0.0, np.asarray(ImageOps.exif_transpose(Image.open(ph)).convert("RGB"))) for ph in photos]
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
                 "layout": layout, "titleSize": fit["size"], "titleLines": fit["lines"],
                 "title": title, "highlight": highlight or "", "width": out_w, "height": out_h, "fps": 30,
                 "durationInFrames": 1}
        # a blurred real frame only reads well as a background when it IS the real frame behind
        # the speaker; a posed photo blurred behind itself just looks like a mistake
        if layout == "shorts-cover" and card:
            # screen + camera project: the shorts-cover top half is the screen, not another
            # copy of the camera frame the face was just cut from
            props["background"] = motion.stage_images({"image": str(card)})["image"]
        elif not photos:
            props["background"] = motion.stage_images({"image": str(bg)})["image"]
        if card and layout not in ("screenshot", "clean-white", "shorts-cover"):
            props["card"] = motion.stage_images({"image": str(card)})["image"]
        if layout == "two-person" and photo2_path:
            props["image2"] = motion.stage_images({"image": str(photo2_path)})["image"]
        if layout == "payment":
            props["amount"] = amount
        if layout == "checklist":
            props["items"] = checklist
        if layout == "screenshot" and screenshot_staged:
            props["screenshot"] = motion.stage_images({"image": screenshot_staged})["image"]
            if screenshot_box:
                x, y, bw, bh = screenshot_box
                props["screenshotBox"] = {"x": x, "y": y, "w": bw, "h": bh}
        if chip:
            props["chip"] = chip
        pf = work / f"thumb_{k}.props.json"
        pf.write_text(json.dumps(props), encoding="utf-8")
        png = work / f"thumb_{k}.png"
        r = subprocess.run([str(motion.remotion_bin()), "still", "src/index.ts", "Thumbnail", str(png),
                            f"--props={pf}", "--frame=0", "--log=error", f"--width={out_w}", f"--height={out_h}"],
                           cwd=motion.REMOTION_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not png.exists():
            raise RuntimeError(f"Thumbnail render failed:\n{r.stderr[-1200:]}")
        jpg = out_dir / f"{name}_{k}.jpg"
        Image.open(png).convert("RGB").save(jpg, quality=92)  # YouTube limit is 2 MB; this lands well under
        results.append(jpg)
    return results
