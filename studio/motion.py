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
TEMPLATES = ["KineticTitle", "EditorialTitle", "LowerThird", "ChapterCard", "CallToAction", "Callout", "BrandIntro",
             "FloatingCards", "StatPanels", "EndCard", "File"]
_status: dict = {}


def remotion_bin() -> Path:
    return REMOTION_DIR / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")


def available() -> bool:
    return remotion_bin().exists() and (REMOTION_DIR / "src" / "index.ts").exists() and shutil.which("node") is not None


def templates_hash() -> str:
    """Changes whenever any template source changes, so cached renders are never stale."""
    h = hashlib.sha256()
    for f in sorted((REMOTION_DIR / "src").rglob("*.ts*")):
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def brand_props(plan: dict) -> dict:
    from . import brand as brand_mod
    try:
        b = brand_mod.load(plan.get("brand") if plan.get("brand") != "default" else None)
    except FileNotFoundError:
        b = brand_mod.load(None)
    logo = None
    src = b.get("logo_light") or b.get("logo")  # graphics sit on video, so prefer the light version
    if src and Path(src).is_file():
        dst = REMOTION_DIR / "public" / "brand" / b["slug"] / Path(src).name
        if not dst.exists() or dst.stat().st_mtime < Path(src).stat().st_mtime:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        logo = f"brand/{b['slug']}/{Path(src).name}"
    return {"colors": b["colors"], "fontTitle": b["fonts"]["title"], "logo": logo,
            "brand": b["name"], "tagline": b.get("tagline", "")}


def stage_images(props: dict) -> dict:
    """Copy image files referenced by props (cards[].image, image, logo) into the Remotion
    public folder, so templates can load them; returns props with relative paths."""
    def stage(path: str) -> str:
        p = Path(path).expanduser()
        if not p.is_file():
            return path  # already relative to public/ (or missing; the template shows a text card)
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        dst = REMOTION_DIR / "public" / "staged" / f"{digest}{p.suffix.lower()}"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        return f"staged/{dst.name}"
    props = dict(props)
    if isinstance(props.get("cards"), list):
        props["cards"] = [dict(c, image=stage(c["image"])) if c.get("image") else c for c in props["cards"]]
    for k in ("image",):
        if props.get(k):
            props[k] = stage(props[k])
    return props


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
    props = {**brand_props(plan), **stage_images(graphic.get("props", {})), "placement": graphic.get("placement", "overlay")}
    payload = {"template": graphic["template"], "props": props, "w": out_spec["width"], "h": out_spec["height"],
               "fps": fps, "duration": graphic["duration"], "code": templates_hash()}
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
