"""Motion-graphic cards via HyperFrames (the vendored card library + CLI, under
studio/motion/hyperframes/). A card is a standalone HyperFrames HTML composition;
staging copies it, applies brand colors/fonts and fills its text slots, and
render_card renders the result once as a transparent ProRes 4444 overlay,
cached by its content key.

If HyperFrames is not installed, cards are skipped and the render reports it;
nothing pretends to have been drawn."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config

LIBRARY_DIR = config.HYPERFRAMES_DIR / "library"

_registry_cache: dict | None = None
_style_slots_cache: dict[str, dict] = {}
_status: dict = {}

CANVAS_VARS = ("canvas", "canvas-deep", "paper", "paper-2", "bg")
ACCENT_VARS = ("accent", "yellow", "highlight")
TEXT_VARS = ("ink", "fg", "text")
NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s?[kKmMbB%]?")


def available() -> bool:
    return (config.HYPERFRAMES_DIR / "node_modules" / "hyperframes").exists() and shutil.which("node") is not None


def _npx() -> str:
    if os.name == "nt":
        return "npx.cmd"
    return shutil.which("npx") or "npx"


def registry() -> dict:
    global _registry_cache
    if _registry_cache is None:
        p = LIBRARY_DIR / "registry.json"
        _registry_cache = json.loads(p.read_text(encoding="utf-8"))
    return _registry_cache


def _style_entry(style_id: str) -> dict:
    for s in registry()["styles"]:
        if s["id"] == style_id:
            return s
    raise ValueError(f"Unknown HyperFrames style: {style_id}")


def _style_folder(style_id: str) -> Path:
    return LIBRARY_DIR / _style_entry(style_id)["folder"]


def _style_slots_by_id(style_id: str) -> dict[str, list[dict]]:
    """Per-card slot declarations (name/type/max) from the style's own style.json,
    which carries more detail than the generated registry.json."""
    if style_id not in _style_slots_cache:
        style_json = _style_folder(style_id) / "style.json"
        out: dict[str, list[dict]] = {}
        if style_json.is_file():
            data = json.loads(style_json.read_text(encoding="utf-8"))
            for c in data.get("cards", []):
                slots = []
                for s in c.get("slots", []):
                    if isinstance(s, dict):
                        slots.append({"name": s["name"], "type": s.get("type", "text"), "max": s.get("max")})
                    else:
                        slots.append({"name": s, "type": "text", "max": None})
                out[c["id"]] = slots
        _style_slots_cache[style_id] = out
    return _style_slots_cache[style_id]


def cards(tier: str | None = None, purpose: str | None = None, style: str | None = None) -> list[dict]:
    """Normalized card entries: {id, style, tier, purpose, file (abs path), slots, duration_range}."""
    out = []
    for s in registry()["styles"]:
        if style and s["id"] != style:
            continue
        slot_lookup = _style_slots_by_id(s["id"])
        for c in s.get("cards", []):
            if tier and c["tier"] != tier:
                continue
            if purpose and c["purpose"] != purpose:
                continue
            slots = slot_lookup.get(c["id"])
            if not slots:
                slots = [{"name": n, "type": "text", "max": None} for n in c.get("slots", [])]
            dur = c.get("duration") or {}
            out.append({
                "id": c["id"],
                "style": c.get("style", s["id"]),
                "tier": c["tier"],
                "purpose": c["purpose"],
                "file": str((LIBRARY_DIR / c["file"]).resolve()),
                "slots": slots,
                "duration_range": (dur.get("min"), dur.get("max")),
            })
    return out


def _find_card(card_id: str) -> dict:
    for c in cards():
        if c["id"] == card_id:
            return c
    raise ValueError(f"Unknown HyperFrames card id: {card_id}")


def pick_card(tier: str, purpose: str, style: str = "kallaway", seed: str = "") -> dict | None:
    """Deterministic pick among matching cards: a stable hash of the seed selects
    the index, so the same seed always returns the same card. Falls back to
    another style if the requested one has no match for this tier/purpose."""
    matches = cards(tier=tier, purpose=purpose, style=style)
    if not matches:
        for s in registry()["styles"]:
            if s["id"] == style:
                continue
            matches = cards(tier=tier, purpose=purpose, style=s["id"])
            if matches:
                break
    if not matches:
        return None
    matches = sorted(matches, key=lambda c: c["id"])
    digest = hashlib.sha1(f"{tier}|{purpose}|{style}|{seed}".encode()).hexdigest()
    return matches[int(digest, 16) % len(matches)]


def _fill_slot(text: str, name: str, value) -> str:
    """Replace a data-slot element's inner text (HTML-escaped). Assumes slot
    elements don't nest another element of the same tag, true of every card in
    the library."""
    pattern = re.compile(rf'<([a-zA-Z0-9]+)([^>]*\bdata-slot="{re.escape(name)}"[^>]*)>(.*?)</\1>', re.DOTALL)
    escaped = html.escape(str(value))
    new_text, _ = pattern.subn(lambda m: f"<{m.group(1)}{m.group(2)}>{escaped}</{m.group(1)}>", text, count=1)
    return new_text


def _patch_root(text: str, duration: float) -> str:
    """Set data-duration on the composition root div and make sure data-width /
    data-height are present (defaulting to 1920x1080 if a card ever lacks them)."""
    def repl(m):
        attrs = m.group(1)
        if "data-duration=" in attrs:
            attrs = re.sub(r'data-duration="[^"]*"', f'data-duration="{duration}"', attrs)
        else:
            attrs += f' data-duration="{duration}"'
        if "data-width=" not in attrs:
            attrs += ' data-width="1920"'
        if "data-height=" not in attrs:
            attrs += ' data-height="1080"'
        return f"<div{attrs}>"
    new_text, n = re.subn(r'<div\b([^>]*\bdata-composition-id="[^"]+"[^>]*)>', repl, text, count=1)
    if n == 0:
        raise ValueError("No HyperFrames composition root (data-composition-id) found in card HTML")
    return new_text


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}"


def _defined_vars(tokens_css: str) -> set[str]:
    return set(re.findall(r"--([a-zA-Z0-9-]+)\s*:", tokens_css))


# Token var names styles use for the display/title and body typefaces (see kallaway's and
# vox-explainer's tokens.css). Only overridden when that brand font actually got embedded
# (an @font-face rule exists for it) - never point a var at a font that isn't there.
FONT_VARS = {"title": ("font-display",), "body": ("font-body",)}


def _build_override(tokens_css: str, brand: dict, font_rules: str = "") -> str:
    """A :root{} block mapping brand colors (and, where embedded, brand fonts) onto
    whichever token variables this style actually defines: background/canvas -> brand
    navy/background, accent -> brand orange/accent, text -> brand text color (usually
    white), font-display/font-body -> the brand's title/body fonts so cards use brand
    type instead of the style's own default typeface."""
    names = _defined_vars(tokens_css)
    colors = brand.get("colors") or {}
    bg = colors.get("background") or colors.get("navy") or colors.get("primary") or "#0B0B0F"
    accent = colors.get("accent") or colors.get("highlight") or colors.get("primary") or "#FFD400"
    text_color = colors.get("text") or "#FFFFFF"
    lines = []
    for n in CANVAS_VARS:
        if n in names:
            lines.append(f"  --{n}: {bg};")
    for n in ACCENT_VARS:
        if n in names:
            lines.append(f"  --{n}: {accent};")
    if "accent-rgb" in names:
        lines.append(f"  --accent-rgb: {_hex_to_rgb(accent)};")
    for n in TEXT_VARS:
        if n in names:
            lines.append(f"  --{n}: {text_color};")
    fonts = brand.get("fonts") or {}
    for key, var_names in FONT_VARS.items():
        font_name = fonts.get(key)
        if not font_name or f'font-family: "{font_name}"' not in font_rules:
            continue  # no @font-face was embedded for this font: leave the style's own default
        for n in var_names:
            if n in names:
                lines.append(f'  --{n}: "{font_name}", sans-serif;')
    if not lines:
        return ""
    return ":root {\n" + "\n".join(lines) + "\n}\n"


def _norm_font_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _brand_font_dirs(brand: dict) -> list[Path]:
    dirs = [config.FONTS_DIR]
    slug = brand.get("slug")
    if slug:
        bd = config.BRANDS_DIR / slug
        dirs += [bd, bd / "fonts"]
    return [d for d in dirs if d.is_dir()]


def _find_font_file(name: str, dirs: list[Path]) -> Path | None:
    target = _norm_font_name(name)
    if not target:
        return None
    candidates = [f for d in dirs for f in d.rglob("*") if f.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2")]
    exact = [f for f in candidates if _norm_font_name(f.stem) == target]
    if exact:
        return exact[0]
    prefix = [f for f in candidates if _norm_font_name(f.stem).startswith(target)]
    return prefix[0] if prefix else None


_FONT_FORMATS = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}


def _font_face_rules(brand: dict, dest_dir: Path) -> str:
    dirs = _brand_font_dirs(brand)
    names = [v for v in (brand.get("fonts") or {}).values() if v]
    rules = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        f = _find_font_file(name, dirs)
        if not f:
            continue
        dest_fonts = dest_dir / "fonts"
        dest_fonts.mkdir(exist_ok=True)
        dst = dest_fonts / f.name
        if not dst.exists():
            shutil.copy2(f, dst)
        fmt = _FONT_FORMATS[f.suffix.lower()]
        rules.append(f'@font-face {{ font-family: "{name}"; src: url("./fonts/{f.name}") format("{fmt}"); '
                      f'font-display: swap; }}')
    return "\n".join(rules)


def _stage_tokens(style_id: str, brand: dict, dest_dir: Path) -> None:
    text = (_style_folder(style_id) / "tokens.css").read_text(encoding="utf-8")
    text = re.sub(r"@import\s+url\([^)]*\)\s*;\s*", "", text)  # Google Fonts import: no network at render time
    font_rules = _font_face_rules(brand, dest_dir)
    override = _build_override(text, brand, font_rules)
    text = text.rstrip() + "\n\n" + font_rules + "\n\n" + override
    (dest_dir / "tokens.css").write_text(text, encoding="utf-8")


def _stage_gsap(dest_dir: Path) -> None:
    src = config.HYPERFRAMES_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if src.is_file():
        shutil.copy2(src, dest_dir / "gsap.min.js")


def stage(card_id: str, slots: dict, brand: dict, duration: float, work: Path, fps: int = 30) -> Path:
    """Build a standalone, render-ready copy of a card: brand tokens applied,
    slots filled, local gsap/tokens. Returns the staged index.html path."""
    card = _find_card(card_id)
    known = {s["name"] for s in card["slots"]}
    unknown = sorted(set(slots) - known)
    if unknown:
        raise ValueError(f"Unknown slot(s) for card {card_id}: {', '.join(unknown)}")

    key_payload = {"card": card_id, "slots": slots, "colors": brand.get("colors", {}),
                   "fonts": brand.get("fonts", {}), "duration": duration, "fps": fps}
    key = hashlib.sha1(json.dumps(key_payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    dest_dir = Path(work) / "_stage" / key
    dest_dir.mkdir(parents=True, exist_ok=True)

    text = Path(card["file"]).read_text(encoding="utf-8")
    text = re.sub(r'href="[^"]*tokens\.css"', 'href="./tokens.css"', text)
    text = re.sub(r'<script\s+src="[^"]*gsap[^"]*"[^>]*></script>', '<script src="./gsap.min.js"></script>', text)
    for name, value in slots.items():
        text = _fill_slot(text, name, value)
    text = _patch_root(text, duration)
    (dest_dir / "index.html").write_text(text, encoding="utf-8")

    _stage_tokens(card["style"], brand, dest_dir)
    _stage_gsap(dest_dir)
    return dest_dir / "index.html"


def render_card(card_id: str, slots: dict, brand: dict, duration: float, out_dir: Path, fps: int = 30,
                quality: str = "standard", work: Path | None = None) -> Path | None:
    key_payload = {"card": card_id, "slots": slots, "colors": brand.get("colors", {}),
                   "fonts": brand.get("fonts", {}), "duration": duration, "fps": fps, "quality": quality}
    key = hashlib.sha1(json.dumps(key_payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"HyperCard_{key}.mov"
    if out.exists():
        return out
    if not available():
        _status["skipped"] = _status.get("skipped", 0) + 1
        return None

    index_html = stage(card_id, slots, brand, duration, Path(work) if work else out_dir / "_work", fps=fps)
    tmp = out.with_suffix(".part.mov")
    cmd = [_npx(), "hyperframes", "render", str(index_html.parent), "--format", "mov", "-o", str(tmp),
           "--fps", str(fps), "--quality", quality]
    try:
        res = subprocess.run(cmd, cwd=config.HYPERFRAMES_DIR, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"HyperFrames render failed for {card_id}: {exc}")
        _status["failed"] = _status.get("failed", 0) + 1
        return None
    if res.returncode != 0 or not tmp.exists():
        print(f"HyperFrames render failed for {card_id}:\n{config.redact(res.stderr[-1500:])}")
        _status["failed"] = _status.get("failed", 0) + 1
        return None
    tmp.replace(out)
    return out


def _normalize_number(tok: str) -> str:
    t = tok.strip().lstrip("$").replace(",", "").replace(" ", "")
    mult = 1
    if t[-1:].lower() == "k":
        mult, t = 1_000, t[:-1]
    elif t[-1:].lower() == "m":
        mult, t = 1_000_000, t[:-1]
    elif t[-1:].lower() == "b":
        mult, t = 1_000_000_000, t[:-1]
    is_pct = t.endswith("%")
    if is_pct:
        t = t[:-1]
    try:
        val = float(t) * mult
    except ValueError:
        return tok.strip()
    val_str = str(int(val)) if val == int(val) else f"{val:g}"
    return f"{val_str}%" if is_pct else val_str


def _numeric_tokens(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.finditer(text):
        tok = m.group(0).strip()
        if tok and any(ch.isdigit() for ch in tok):
            out.add(_normalize_number(tok))
    return out


def check_slot_text(slots: dict, transcript_text: str, knowledge_text: str = "") -> list[str]:
    """A warning for every number, percentage or $ amount in the slot text that
    doesn't show up (loosely normalized) in the transcript or knowledge text."""
    present = _numeric_tokens(f"{transcript_text}\n{knowledge_text}")
    warnings = []
    for name, value in slots.items():
        for m in NUM_RE.finditer(str(value)):
            tok = m.group(0).strip()
            if not tok or not any(ch.isdigit() for ch in tok):
                continue
            if _normalize_number(tok) not in present:
                warnings.append(f'{name}: "{tok}" not found in transcript/knowledge')
    return warnings


def tier_allowed(tier: str, width: int, height: int) -> bool:
    """tier1 takeovers are full-bleed landscape cards; they don't fit a vertical frame."""
    if tier == "tier1" and height > width:
        return False
    return True
