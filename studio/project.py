"""Projects: one folder per recording under ~/VibeStudio/projects/<id>/.

The original recording is referenced read-only (or optionally copied in). Nothing in
the studio ever writes to, moves or deletes the original file."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import config, media

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "video"


def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid


def create(source: str | Path, *, name: str | None = None, brand: str | None = None,
           mode: str = "longform", copy: bool = False, camera: str | Path | None = None,
           vertical: str | Path | None = None, cam_ranges: list | None = None) -> dict:
    """Register a recording. `camera` is an optional separate camera track (e.g. a Tella
    camera file) kept alongside the screen recording for future layouts."""
    config.ensure_dirs()
    src = Path(source).expanduser().resolve()
    info = media.probe(src)
    if not info.has_video and not info.has_audio:
        raise media.MediaError(f"{src} has no audio or video streams.")
    pid = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(name or src.stem)}"
    d = project_dir(pid)
    (d / "work").mkdir(parents=True)
    (d / "exports").mkdir()
    source_path = src
    if copy:
        (d / "source").mkdir()
        source_path = d / "source" / src.name
        shutil.copy2(src, source_path)  # copy; the original stays where it is
    proj = {
        "schema": "vibe-studio.project/v1", "id": pid, "name": name or src.stem, "mode": mode,
        "brand": brand, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "original": str(src),
        "source": {"path": str(source_path), "duration": info.duration, "width": info.width,
                   "height": info.height, "fps": round(info.fps, 3) if info.fps else 30.0,
                   "size_bytes": info.size_bytes, "vcodec": info.vcodec, "acodec": info.acodec,
                   **({"vertical_path": str(Path(vertical).resolve()), "layout": "screencam",
                       "cam_ranges": cam_ranges or []} if vertical else {})},
        "camera": str(Path(camera).resolve()) if camera else None,
        "status": "imported", "exports": [],
    }
    save(proj)
    return proj


def save(proj: dict) -> None:
    p = project_dir(proj["id"]) / "project.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(proj, indent=2), encoding="utf-8")
    tmp.replace(p)


def load(pid: str) -> dict:
    p = project_dir(resolve_id(pid)) / "project.json"
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_id(pid: str) -> str:
    """Accept a full id, a unique prefix/substring, or 'latest'."""
    if (config.PROJECTS_DIR / pid / "project.json").exists():
        return pid
    all_ids = sorted(p.parent.name for p in config.PROJECTS_DIR.glob("*/project.json"))
    if pid == "latest" and all_ids:
        return all_ids[-1]
    hits = [i for i in all_ids if pid in i]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise FileNotFoundError(f"No project matching '{pid}'")
    raise ValueError(f"'{pid}' matches several projects: {', '.join(hits)}")


def list_projects() -> list[dict]:
    config.ensure_dirs()
    out = []
    for p in sorted(config.PROJECTS_DIR.glob("*/project.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return out


def find_videos(folder: str | Path) -> list[Path]:
    """Videos in a folder (e.g. a Tella export folder), largest first."""
    f = Path(folder).expanduser()
    vids = [p for p in f.rglob("*") if p.suffix.lower() in VIDEO_EXTS and p.is_file()]
    return sorted(vids, key=lambda p: -p.stat().st_size)
