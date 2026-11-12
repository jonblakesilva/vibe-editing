"""Checks from Nate Herk's editing playbook, run against a RENDERED video and reported
(never auto-fixed) alongside the rest of the render report.

B3 "every word whole": a cut can clip the first consonant or the last syllable of a word
right at the join, even when nothing was wrong with the restart/filler pass that chose the
cut. B4 "mouth check": the speaker's mouth should never be covered by a caption or a motion
graphic, especially in the first couple of seconds (where a viewer decides to keep watching)
and right after every cut (where a graphic timed to the old cut point can land on the new
one)."""
from __future__ import annotations

import difflib
import subprocess

import numpy as np

from . import analyze as an

# ---------------------------------------------------------------- B3: every word whole


def word_whole_check(expected_words: list[dict], heard_words: list[dict], joins: list[float],
                     window: float = 0.6) -> list[dict]:
    """Compare, near every cut, the words the edit was supposed to keep (`expected_words`,
    source words mapped to edited time) against what the listen-back transcription actually
    heard (`heard_words`). A word normalized differently (e.g. "first" heard as "firs") or
    missing entirely near a join is flagged."""
    issues = []
    for join in joins:
        exp = sorted((w for w in expected_words if abs((w["start"] + w["end"]) / 2 - join) <= window),
                     key=lambda w: w["start"])
        heard = sorted((w for w in heard_words if abs((w["start"] + w["end"]) / 2 - join) <= window),
                       key=lambda w: w["start"])
        exp_norm = [an.norm(w["word"]) for w in exp]
        heard_norm = [an.norm(w["word"]) for w in heard]
        sm = difflib.SequenceMatcher(None, exp_norm, heard_norm, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            exp_text = " ".join(w["word"] for w in exp[i1:i2]).strip()
            heard_text = " ".join(w["word"] for w in heard[j1:j2]).strip()
            if not exp_text:
                continue  # something extra was heard, not a source word clipped or dropped
            at = round(exp[i1]["start"], 2)
            reason = (f'"{exp_text}" heard as "{heard_text}"' if heard_text else f'"{exp_text}" missing near the cut')
            issues.append({"at": at, "expected": exp_text, "heard": heard_text, "reason": reason})
    return issues


# ---------------------------------------------------------------- B4: mouth check

MOUTH_LOWER_FRAC = 0.45  # the mouth box is the lower 45% of the face box...
MOUTH_EXTEND_FRAC = 0.10  # ...extended 10% of the face height further down (chin/jaw)

# Rough pixel zones for render.ZONES labels, used to turn an active graphic into a box
# for the overlap test. Deliberately conservative (bigger than the real graphic).
ZONE_RECTS = {
    "full": (0.0, 0.0, 1.0, 1.0),
    "top": (0.0, 0.0, 1.0, 0.25),
    "top-right": (0.55, 0.0, 1.0, 0.22),
    "bottom-left": (0.0, 0.78, 0.55, 1.0),
    "bottom-center": (0.2, 0.8, 0.8, 1.0),
    "left": (0.0, 0.15, 0.35, 0.85),
    "sides": (0.0, 0.15, 1.0, 0.85),
}


def _mouth_box(face: dict, W: float, H: float) -> dict:
    fw, fh = face["w"] * W, face["h"] * H
    fx, fy = face["cx"] * W - fw / 2, face["cy"] * H - fh / 2
    top = fy + fh * (1 - MOUTH_LOWER_FRAC)
    bottom = fy + fh + fh * MOUTH_EXTEND_FRAC
    return {"x": fx, "y": top, "w": fw, "h": bottom - top}


def _overlaps(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and
            a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])


def _face_at(faces: list[dict], t: float, max_gap: float = 1.5) -> dict | None:
    if not faces:
        return None
    f = min(faces, key=lambda f: abs(f["t"] - t))
    return f if abs(f["t"] - t) <= max_gap else None


def mouth_check(faces: list[dict], caption_boxes: list[dict], graphic_boxes: list[dict], W: float, H: float,
                joins: list[float], duration: float, *, frame: float = 1 / 30) -> list[dict]:
    """faces: whatever reframe.track_faces/pipeline.get_faces returns (normalized 0..1
    cx/cy/w/h per sampled time `t`, already mapped to edited time). caption_boxes and
    graphic_boxes: [{start, end, x, y, w, h}] in pixels. Checks 0-2.5s (every 0.1s, where
    viewers decide to keep watching) and the first frame of every shot (join + one frame,
    where a graphic timed to the old cut can land on the new one)."""
    times = [round(i * 0.1, 2) for i in range(26) if i * 0.1 <= min(2.5, duration)]
    times += [round(j + frame, 3) for j in joins if 0 <= j + frame < duration]
    issues, seen = [], set()
    for t in times:
        face = _face_at(faces, t)
        if not face:
            continue
        mouth = _mouth_box(face, W, H)
        for label, boxes in (("caption", caption_boxes), ("graphic", graphic_boxes)):
            for b in boxes:
                if b["start"] <= t < b["end"] and _overlaps(mouth, b):
                    key = (round(t, 1), label)
                    if key not in seen:
                        seen.add(key)
                        issues.append({"at": t, "type": f"{label}_over_mouth",
                                      "reason": f"{label} box overlaps the speaker's mouth"})
                    break
    return sorted(issues, key=lambda i: i["at"])


def caption_boxes(words: list[dict], style: dict, W: int, H: int) -> list[dict]:
    """Rough per-phrase caption boxes for the overlap test. Conservative: uses the caption
    band's vertical rectangle (captions.caption_band) for the chunk's time span; width is the
    measured text width when fontmetrics can give one cheaply, else 80% of the frame width.

    For the playbook style (`style["style"] == "playbook"`), chunks are the 1-3 word playbook
    chunks and the vertical position follows `style["position_overrides"]`
    ([{start, end, cy}], the same per-segment override `render.finish` passes into the ASS
    builder) instead of the split-screen seam logic other styles use."""
    from . import captions as cap_mod
    band = cap_mod.caption_band(W, H, style)
    normal_cy = cap_mod.caption_band(W, H, dict(style, position="auto"))["cy"]
    split = style.get("split_windows")
    playbook = style.get("style") == "playbook"
    overrides = style.get("position_overrides") or []
    chunks = (cap_mod.chunk_playbook(words, max_words=int(style.get("max_words", 3))) if playbook
              else cap_mod.chunk_words(words, max_words=int(style.get("max_words", 6))))
    boxes = []
    for ch in chunks:
        if not ch:
            continue
        text = " ".join(w["word"] for w in ch)
        try:
            from . import fontmetrics
            font = style.get("font", "Outfit Bold" if style.get("box") == "rounded" else "Montserrat ExtraBold")
            tw = fontmetrics.text_width(text, font, band["size"], band["size"] * 0.01)
        except Exception:
            tw = W * 0.8
        tw = min(max(tw, W * 0.1), W * 0.95)
        pad_x = band["size"] * 0.5 if playbook else 0  # playbook's box pads the text on each side
        cy = band["cy"]
        mid = (ch[0]["start"] + ch[-1]["end"]) / 2
        if playbook:
            for ov in overrides:
                if ov["start"] <= mid < ov["end"]:
                    cy = ov["cy"]
                    break
        elif split is not None:
            cy = H * 0.5 if any(a <= mid <= b for a, b in split) else normal_cy
        top = cy - (band["cy"] - band["top"])
        bottom = cy + (band["bottom"] - band["cy"])
        boxes.append({"start": ch[0]["start"], "end": ch[-1]["end"] + 0.3,
                      "x": W / 2 - tw / 2 - pad_x, "y": top, "w": tw + 2 * pad_x, "h": bottom - top})
    return boxes


def graphic_boxes(graphics: list[dict], W: int, H: int) -> list[dict]:
    """Rough pixel boxes for active motion graphics, from the screen zone each template
    occupies (render.ZONES)."""
    from .render import ZONES
    boxes = []
    for g in graphics:
        for zone in ZONES.get(g.get("template"), {"full"}):
            x0, y0, x1, y1 = ZONE_RECTS.get(zone, ZONE_RECTS["full"])
            boxes.append({"start": g["start"], "end": g["start"] + g["duration"],
                          "x": x0 * W, "y": y0 * H, "w": (x1 - x0) * W, "h": (y1 - y0) * H})
    return boxes


# ---------------------------------------------------------------- playbook contrast check
#
# "White captions on a bright website are unreadable" -> every playbook caption sits in
# the same dark box, so this is run against the RENDERED video (never a guess from the
# ASS source) and reported alongside the rest of the render report (never auto-fixed).


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (_srgb_to_linear(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio between two hex colours (1..21)."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _box_mean_luma(video_path, t: float, box: dict, W: int, H: int) -> float | None:
    """Mean 0..1 luminance of the rendered frame at time `t`, cropped to `box` (pixels)."""
    x = max(0, min(W - 2, int(box["x"])))
    y = max(0, min(H - 2, int(box["y"])))
    w = max(2, min(int(box["w"]), W - x))
    h = max(2, min(int(box["h"]), H - y))
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video_path),
         "-vf", f"crop={w}:{h}:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True)
    if not out.stdout:
        return None
    arr = np.frombuffer(out.stdout, dtype=np.uint8)
    return float(arr.mean()) / 255.0 if arr.size else None


def check_contrast(video_path, caption_boxes: list[dict], *, samples: int = 40,
                   box_color: str = "#0B0B0F", text_color: str = "#FFFFFF",
                   dark_luma_max: float = 0.35, min_contrast: float = 4.5) -> dict:
    """Samples frames at chunk midpoints from the RENDERED video. Flags any caption box
    whose measured mean luminance isn't dark (>= `dark_luma_max`, so the box reads on any
    background) and the text/box WCAG contrast ratio if it falls under `min_contrast`
    (4.5 is WCAG AA for normal-size text). Returns a report; never fixes anything."""
    from . import media
    info = media.probe(video_path)
    boxes = [b for b in caption_boxes if 0 <= (b["start"] + b["end"]) / 2 <= info.duration]
    if samples > 0 and len(boxes) > samples:
        denom = max(1, samples - 1)
        idx = sorted({round(k * (len(boxes) - 1) / denom) for k in range(samples)})
        boxes = [boxes[i] for i in idx]
    issues = []
    for b in boxes:
        mid = (b["start"] + b["end"]) / 2
        luma = _box_mean_luma(video_path, mid, b, info.width, info.height)
        if luma is None:
            continue
        if luma >= dark_luma_max:
            issues.append({"at": round(mid, 2), "type": "box_not_dark", "luma": round(luma, 3),
                          "reason": f"caption box luminance {luma:.2f} >= {dark_luma_max} at t={mid:.2f}s"})
    contrast = round(_contrast_ratio(text_color, box_color), 2)
    if contrast < min_contrast:
        issues.append({"type": "low_text_contrast", "contrast": contrast,
                      "reason": f"text/box contrast {contrast} < {min_contrast} (WCAG AA)"})
    return {"issues": issues, "samples_checked": len(boxes), "text_box_contrast": contrast, "ok": not issues}
