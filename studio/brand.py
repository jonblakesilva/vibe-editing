"""Brand profiles: one folder per brand under ~/VibeStudio/brands/<slug>/ holding
brand.json plus any logo, fonts, music and style-reference files the user adds."""
from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from pathlib import Path

from . import config

# Asked one at a time by Claude Code or the dashboard. Keys map into the profile.
INTERVIEW = [
    ("name", "What is the brand name?"),
    ("logo", "Do you have a logo file? Share the path or drop it in (PNG with transparency works best), or say skip."),
    ("colors", "What are your brand colors? Hex codes are ideal (e.g. primary #FFD400, accent #111111)."),
    ("fonts", "Which fonts should titles and captions use? Pick from the bundled list or give a font file."),
    ("caption_style", "Caption style: clean (educational), bold (word-by-word pop), karaoke (highlighted word), or minimal?"),
    ("pace", "Editing pace: relaxed, natural, or tight?"),
    ("music", "Music: none, or the folder/tracks you have licensed for use? Preferred mood?"),
    ("intro_style", "Intro style: cold open with your hook, branded title card, or straight in?"),
    ("outro_style", "Outro style: end card, logo sting, or just the call to action?"),
    ("cta", "What should viewers do at the end (e.g. book a free call at example.com)?"),
    ("audience", "Who is the target audience?"),
    ("topics", "What topics does this brand usually cover?"),
]

DEFAULT_PROFILE = {
    "schema": "vibe-studio.brand/v1",
    "name": "Default",
    "slug": "default",
    "logo": None,
    "colors": {"primary": "#FFD400", "accent": "#FFFFFF", "text": "#FFFFFF", "background": "#0B0B0F",
               "highlight": "#FFD400"},
    "fonts": {"title": "Montserrat ExtraBold", "captions": "Montserrat ExtraBold", "body": "Inter"},
    "caption_style": "clean",
    "caption": {"size": 1.0, "position": "auto", "uppercase": False, "max_words": 6},
    "pace": "natural",
    "music": {"enabled": False, "folder": None, "mood": "", "volume_db": -22},
    "intro_style": "straight",
    "outro_style": "cta",
    "cta": {"text": "", "url": ""},
    "audience": "",
    "topics": [],
    "vocabulary": [],
    "lower_third": {"name": "", "title": ""},
    "style_references": [],
    "complete": False,
}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "brand"


def brand_dir(slug: str) -> Path:
    return config.BRANDS_DIR / slug


def list_brands() -> list[dict]:
    config.ensure_dirs()
    out = []
    for p in sorted(config.BRANDS_DIR.glob("*/brand.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def load(slug: str | None) -> dict:
    if not slug:
        return deepcopy(DEFAULT_PROFILE)
    p = brand_dir(slug) / "brand.json"
    if not p.exists():
        raise FileNotFoundError(f"No brand profile named '{slug}'. Create one with: python -m studio brand new \"Name\"")
    data = json.loads(p.read_text(encoding="utf-8"))
    merged = deepcopy(DEFAULT_PROFILE)
    _deep_update(merged, data)
    return merged


def save(profile: dict) -> Path:
    slug = profile.get("slug") or slugify(profile["name"])
    profile["slug"] = slug
    d = brand_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "brand.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def create(name: str, **fields) -> dict:
    profile = deepcopy(DEFAULT_PROFILE)
    profile["name"] = name
    profile["slug"] = slugify(name)
    _deep_update(profile, fields)
    save(profile)
    return profile


def next_question(profile: dict) -> tuple[str, str] | None:
    """The next unanswered interview question (one at a time)."""
    answered = set(profile.get("_answered", []))
    for key, q in INTERVIEW:
        if key not in answered:
            return key, q
    return None


def answer(profile: dict, key: str, value) -> dict:
    """Record one interview answer. Values may be plain strings; they are parsed."""
    if key == "colors" and isinstance(value, str):
        hexes = re.findall(r"#[0-9a-fA-F]{6}", value)
        if hexes:
            profile["colors"]["primary"] = hexes[0]
            profile["colors"]["highlight"] = hexes[0]
            if len(hexes) > 1:
                profile["colors"]["accent"] = hexes[1]
    elif key == "fonts" and isinstance(value, str) and value.lower() != "skip":
        profile["fonts"]["title"] = profile["fonts"]["captions"] = value
    elif key == "logo" and isinstance(value, str) and value.lower() != "skip":
        profile["logo"] = import_asset(profile, value, "logo")
    elif key == "music" and isinstance(value, str):
        if value.lower() in ("none", "no", "skip"):
            profile["music"]["enabled"] = False
        else:
            p = Path(value.strip('"')).expanduser()
            profile["music"].update({"enabled": p.exists(), "folder": str(p) if p.exists() else None,
                                     "mood": "" if p.exists() else value})
    elif key == "cta" and isinstance(value, str):
        url = re.search(r"(https?://\S+|\b[\w-]+\.(?:com|net|org|io|co)\S*)", value)
        profile["cta"] = {"text": value, "url": url.group(0) if url else ""}
    elif key == "topics" and isinstance(value, str):
        profile["topics"] = [t.strip() for t in re.split(r"[,;\n]", value) if t.strip()]
    elif key == "pace" and isinstance(value, str):
        v = value.lower()
        profile["pace"] = "tight" if "tight" in v or "fast" in v else "relaxed" if "relax" in v or "slow" in v else "natural"
    elif key == "caption_style" and isinstance(value, str):
        v = value.lower()
        profile["caption_style"] = next((s for s in ("karaoke", "bold", "minimal", "clean") if s in v), "clean")
    else:
        profile[key] = value
    answered = set(profile.get("_answered", []))
    answered.add(key)
    profile["_answered"] = sorted(answered)
    profile["complete"] = next_question(profile) is None
    save(profile)
    return profile


def import_asset(profile: dict, src: str, kind: str) -> str:
    """Copy a user-supplied file into the brand folder (the original is untouched)."""
    sp = Path(src.strip('"')).expanduser()
    if not sp.is_file():
        raise FileNotFoundError(f"File not found: {sp}")
    d = brand_dir(profile.get("slug") or slugify(profile["name"])) / kind
    d.mkdir(parents=True, exist_ok=True)
    dst = d / sp.name
    shutil.copy2(sp, dst)
    return str(dst)


def _deep_update(base: dict, new: dict) -> None:
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
