"""Licensed background-music library at ~/VibeStudio/music: a flat folder of tracks plus
manifest.json (mood tags, bpm, duration, LUFS) and LICENSES.md. Nothing here downloads or
licenses music itself - it only reads what's already there, and only offers tracks that are
actually on disk and don't require an attribution line (so nothing is picked that would need
bookkeeping the rest of the studio doesn't do).

Picks are deterministic by seed, same spirit as hyperframes.pick_card: the same plan/seed
always gets the same track, but different plans spread across the available tracks."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import config

# Mood words the rest of the studio uses (plan.py, brief copy, etc.) map onto the manifest's
# own mood tags. A mood that isn't one of these aliases is tried as an exact tag match instead
# (e.g. "lofi" or "driving" straight from the manifest).
MOOD_ALIASES = {
    "confident": {"confident", "hip-hop", "driving"},
    "claims": {"confident", "hip-hop", "driving"},
    "chill": {"lo-fi", "chill", "calm"},
    "method": {"lo-fi", "chill", "calm"},
}


def library() -> list[dict]:
    """Every licensed track whose file exists and doesn't require attribution."""
    man = config.MUSIC_DIR / "manifest.json"
    if not man.exists():
        return []
    try:
        items = json.loads(man.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        if it.get("attribution_required"):
            continue
        path = config.MUSIC_DIR / it["file"]
        if not path.is_file():
            continue
        out.append({**it, "path": str(path)})
    return out


def pick(mood: str, seed: str = "") -> dict | None:
    """Deterministic pick among the tracks matching `mood`. Falls back to treating `mood`
    as a literal manifest tag when it isn't one of the known aliases, so exact tag matches
    (e.g. "lofi") work too. Returns None if nothing matches (including an empty library)."""
    if not mood:
        return None
    tags = MOOD_ALIASES.get(mood.lower(), {mood.lower()})
    matches = [t for t in library() if tags & {str(m).lower() for m in t.get("mood", [])}]
    if not matches:
        return None
    matches.sort(key=lambda t: t["file"])  # stable order before hashing
    digest = hashlib.sha1(f"{mood}|{seed}".encode()).hexdigest()
    return matches[int(digest, 16) % len(matches)]


def status() -> dict:
    """{folder, count, moods: {tag: n}} - a quick health check (`studio music status`)."""
    tracks = library()
    moods = Counter(str(m).lower() for t in tracks for m in t.get("mood", []))
    return {"folder": str(config.MUSIC_DIR), "count": len(tracks), "moods": dict(moods)}
