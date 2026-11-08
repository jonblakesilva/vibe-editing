"""Motion graphics via Remotion (React). Each graphic is rendered once as a
transparent ProRes 4444 overlay at the output resolution, cached by its props, and
composited by FFmpeg in the finish pass.

If Remotion is not installed, graphics are skipped and the render reports it;
nothing pretends to have been drawn."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config

REMOTION_DIR = config.MOTION_DIR / "remotion"
TEMPLATES = ["KineticTitle", "LowerThird", "ChapterCard", "CallToAction", "Callout", "BrandIntro", "File"]
_status: dict = {}


def remotion_bin() -> Path:
    return REMOTION_DIR / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")


def available() -> bool:
    return remotion_bin().exists() and (REMOTION_DIR / "src" / "index.ts").exists() and shutil.which("node") is not None


def brand_props(plan: dict) -> dict:
    from . import brand as brand_mod
    try:
        b = brand_mod.load(plan.get("brand") if plan.get("brand") != "default" else None)
    except FileNotFoundError:
        b = brand_mod.load(None)
    return {"colors": b["colors"], "fontTitle": b["fonts"]["title"], "logo": None}


def render_overlay(graphic: dict, plan: dict, out_spec: dict, cache_dir: Path) -> Path | None:
    if graphic["template"] == "File":
        # A ready-made transparent overlay (e.g. rendered with HyperFrames: --format mov).
        p = Path(graphic.get("props", {}).get("path", "")).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Overlay file not found: {p}")
        return p
    if graphic["template"] not in TEMPLATES:
        raise ValueError(f"Unknown motion template {graphic['template']}. Available: {', '.join(TEMPLATES)}")
    if not available():
        _status["skipped"] = _status.get("skipped", 0) + 1
        return None
    fps = int(round(plan["source"].get("fps") or 30))
    props = {**brand_props(plan), **graphic.get("props", {}), "placement": graphic.get("placement", "overlay")}
    payload = {"template": graphic["template"], "props": props, "w": out_spec["width"], "h": out_spec["height"],
               "fps": fps, "duration": graphic["duration"]}
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:14]
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{graphic['template']}_{key}.mov"
    if out.exists():
        return out
    frames = max(1, int(round(graphic["duration"] * fps)))
    props_file = cache_dir / f"{key}.props.json"
    props_file.write_text(json.dumps({**props, "width": out_spec["width"], "height": out_spec["height"],
                                      "durationInFrames": frames, "fps": fps}), encoding="utf-8")
    tmp = out.with_suffix(".part.mov")
    cmd = [str(remotion_bin()), "render", "src/index.ts", graphic["template"], str(tmp),
           f"--props={props_file}", "--codec=prores", "--prores-profile=4444",
           "--pixel-format=yuva444p10le", "--image-format=png", "--log=error",
           f"--width={out_spec['width']}", f"--height={out_spec['height']}"]
    res = subprocess.run(cmd, cwd=REMOTION_DIR, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if res.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"Remotion render failed for {graphic['template']}:\n{config.redact(res.stderr[-1500:])}")
    tmp.replace(out)
    return out
