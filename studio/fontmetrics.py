"""Find font files by name and measure text the way libass will draw it, so caption
backgrounds and layout can be sized exactly."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import config


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    from fontTools.ttLib import TTFont
    idx: dict[str, str] = {}
    dirs = [config.FONTS_DIR, config.FONTS_DIR / "free_font", config.BRANDS_DIR]
    for d in dirs:
        if not d.exists():
            continue
        for f in list(d.rglob("*.ttf")) + list(d.rglob("*.otf")):
            try:
                names = TTFont(f, lazy=True)["name"]
                for rec in names.names:
                    if rec.nameID in (1, 4, 6):
                        idx.setdefault(rec.toUnicode().lower(), str(f))
            except Exception:
                continue
    return idx


def font_file(name: str) -> str | None:
    idx = _index()
    key = name.lower()
    return idx.get(key) or idx.get(key.replace(" ", "-")) or idx.get(key.split(" ")[0])


@lru_cache(maxsize=32)
def _pil_font(path: str, ass_size: int):
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    t = TTFont(path, lazy=True)
    os2 = t["OS/2"]
    upm = t["head"].unitsPerEm
    # libass sizes a font so that winAscent + winDescent equals the ASS font size
    em = ass_size * upm / max(1, os2.usWinAscent + os2.usWinDescent)
    return ImageFont.truetype(path, max(1, round(em)))


def text_width(text: str, font: str, ass_size: int, spacing: float = 0.0) -> float:
    path = font_file(font)
    if not path:
        return len(text) * ass_size * 0.5  # rough fallback
    f = _pil_font(path, ass_size)
    return f.getlength(text) + spacing * max(0, len(text) - 1)
