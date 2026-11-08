"""Review assets (Frame.io style): every exported video with its versions and an
approval status. Approval here is a reviewer sign-off on a rendered video; it is
separate from approving the editing plan and never publishes anything."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import media

STATUSES = ("needs_review", "in_progress", "changes_requested", "approved")


def _exports(pid: str) -> Path:
    from .pipeline import paths
    return paths(pid)["exports"]


def _status_file(pid: str) -> Path:
    return _exports(pid).parent / "review.json"


def statuses(pid: str) -> dict:
    p = _status_file(pid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def set_status(pid: str, file: str, status: str, author: str = "you") -> dict:
    if status not in STATUSES:
        raise ValueError(f"Status must be one of {', '.join(STATUSES)}")
    data = statuses(pid)
    data[file] = {"status": status, "by": author, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _status_file(pid).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data[file]


def friendly_name(rel: str, dims: dict, clip_titles: list | None = None) -> str:
    import re
    stem = Path(rel).stem
    preview = " (preview)" if "_preview" in stem else ""
    stem = stem.replace("_preview", "")
    w, h = dims.get("width") or 16, dims.get("height") or 9
    shape = "Vertical 9:16" if h > w else ("Square 1:1" if h == w else ("YouTube 16:9 4K" if w >= 3800 else "YouTube 16:9"))
    m = re.match(r"short(\d+)_(.+?)_(shorts|tiktok|reels|square|linkedin|youtube)(_clean)?$", stem)
    if m:
        n = int(m.group(1))
        title = (clip_titles[n - 1] if clip_titles and n <= len(clip_titles) and clip_titles[n - 1]
                 else m.group(2).replace("_", " ").strip())
        return f"Short {int(m.group(1))}: {title[:1].upper() + title[1:]}{' - no captions' if m.group(4) else ''}{preview}"
    return f"Full video - {shape}{preview}"


def assets(pid: str) -> list[dict]:
    from . import comments
    ex = _exports(pid)
    st = statuses(pid)
    cm = comments.load(pid)
    plan_file = ex.parent / "plan.json"
    clip_titles = [c.get("title") for c in json.loads(plan_file.read_text(encoding="utf-8")).get("clips", [])
                   if c.get("enabled", True)] if plan_file.exists() else []
    out = []
    for f in sorted(ex.rglob("*.mp4")):
        rel = f.relative_to(ex).as_posix()
        if "versions/" in rel or ".part." in f.name:
            continue
        vdir = f.parent / "versions" / f.stem
        meta = vdir / "versions.json"
        vmeta = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
        prefix = (f.parent.relative_to(ex).as_posix() + "/") if f.parent != ex else ""
        versions = [{"v": v["v"], "file": prefix + v["file"], "created": v.get("archived"),
                     "plan_version": v.get("plan_version")} for v in vmeta]
        versions.append({"v": len(vmeta) + 1, "file": rel, "current": True,
                         "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))})
        try:
            info = media.probe(f)
            dims = {"width": info.width, "height": info.height, "duration": round(info.duration, 3),
                    "fps": info.fps or 30}
        except media.MediaError:
            dims = {}
        files = {v["file"] for v in versions}
        out.append({"file": rel, "name": friendly_name(rel, dims, clip_titles),
                    "kind": "short" if rel.startswith("shorts/") else "main",
                    "preview": "_preview" in f.stem, **dims, "versions": versions,
                    "status": st.get(rel, {"status": "needs_review"}),
                    "open_comments": sum(1 for c in cm if c["file"] in files and c["status"] == "open"
                                         and not c.get("parent"))})
    out.sort(key=lambda a: (a["kind"] != "main", "Vertical" in a["name"], a["preview"] is False, a["name"]))
    return out
