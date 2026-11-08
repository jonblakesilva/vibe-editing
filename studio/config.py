"""Paths and settings. Secrets are read from the environment or a private file
outside the repository; nothing secret is ever written into the project tree."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STUDIO = REPO / "studio"
PLUGIN = REPO / "plugins" / "vibe-editing"
FONTS_DIR = PLUGIN / "skills" / "caption-clips" / "fonts"
YUNET_MODEL = PLUGIN / "skills" / "horizontal-to-vertical" / "scripts" / "yunet.onnx"
MOTION_DIR = STUDIO / "motion"

# User data lives outside the git checkout by default so footage never lands in the repo.
DATA_HOME = Path(os.environ.get("VIBE_STUDIO_HOME", Path.home() / "VibeStudio")).expanduser()
PROJECTS_DIR = DATA_HOME / "projects"
BRANDS_DIR = DATA_HOME / "brands"
MUSIC_DIR = DATA_HOME / "music"
BROLL_DIR = DATA_HOME / "broll"

# Same private location the original kit uses, so existing keys keep working.
KEYS_FILE = Path(os.environ.get("VIBE_KEYS_FILE", Path.home() / ".config" / "vibe-editing" / "keys.env")).expanduser()

SECRET_NAMES = ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ASSEMBLYAI_API_KEY", "GEMINI_API_KEY")


def load_keys(path: Path | None = None) -> list[str]:
    """Load KEY=VALUE lines from the private keys file into the environment.

    Existing environment variables win. Returns the names loaded (never values)."""
    path = Path(path or KEYS_FILE)
    loaded = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if value and not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def has_key(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def redact(text: str) -> str:
    """Remove any loaded secret values from text before it is logged or shown."""
    for name in SECRET_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            text = text.replace(value, f"<{name}>")
    return text


def ensure_dirs() -> None:
    for d in (PROJECTS_DIR, BRANDS_DIR, MUSIC_DIR, BROLL_DIR):
        d.mkdir(parents=True, exist_ok=True)
