"""Timestamped review comments on a project's videos.

A comment is pinned to a moment in a specific file (the original or an export). Comments on
the main edit are also mapped back to the original recording's time, so they can become
plan revisions. Claude reads open comments and applies them; nothing changes until then."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import plan as plan_mod


def _path(pid: str) -> Path:
    from .pipeline import paths
    return paths(pid)["dir"] / "comments.json"


def load(pid: str) -> list[dict]:
    p = _path(pid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(pid: str, items: list[dict]) -> None:
    p = _path(pid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    tmp.replace(p)


def source_time(pid: str, file: str, at: float) -> float | None:
    """Map a time in `file` to the original recording. Exact for the original and for
    main-edit exports; Shorts are cut from several places, so they keep only their own time."""
    if file in ("", "source"):
        return at
    if file.startswith("shorts/") or "versions/" in file:
        return None  # Shorts are stitched from several places; old versions had other timelines
    from .pipeline import paths
    pp = paths(pid)["plan"]
    if not pp.exists():
        return None
    plan = json.loads(pp.read_text(encoding="utf-8"))
    tl = plan_mod.timeline(plan)
    # previews and finals share the same timeline; only resolution differs
    return round(tl.to_source(min(at, tl.duration)), 3)


def add(pid: str, text: str, *, at: float, file: str = "source", author: str = "you",
        end: float | None = None, annotation: list | None = None, parent: str | None = None) -> dict:
    """end: optional range end; annotation: shapes drawn on the frame in 0..1 coordinates
    ([{"type": "pen|arrow|rect", "color": "#hex", "points": [[x, y], ...]}]);
    parent: id of the comment this replies to."""
    items = load(pid)
    if parent and not any(x["id"] == parent for x in items):
        raise KeyError(f"No comment {parent} to reply to")
    c = {"id": uuid.uuid4().hex[:8], "file": file, "at": round(float(at), 3),
         "end": round(float(end), 3) if end is not None and float(end) > float(at) else None,
         "source_at": source_time(pid, file, float(at)), "text": text.strip(), "author": author or "you",
         "annotation": _clean_shapes(annotation), "parent": parent,
         "status": "open", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "resolution": None}
    items.append(c)
    _save(pid, items)
    return c


def _clean_shapes(shapes) -> list | None:
    if not shapes:
        return None
    out = []
    for sh in shapes[:50]:
        if sh.get("type") not in ("pen", "arrow", "rect"):
            continue
        pts = [[round(min(1, max(0, float(x))), 4), round(min(1, max(0, float(y))), 4)]
               for x, y in (sh.get("points") or [])[:500]]
        if len(pts) >= 2:
            out.append({"type": sh["type"], "color": str(sh.get("color", "#F97316"))[:9], "points": pts})
    return out or None


def update(pid: str, cid: str, **fields) -> dict:
    items = load(pid)
    for c in items:
        if c["id"] == cid:
            c.update({k: v for k, v in fields.items() if k in ("status", "resolution", "text")})
            c["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save(pid, items)
            return c
    raise KeyError(f"No comment {cid}")


def delete(pid: str, cid: str) -> None:
    _save(pid, [c for c in load(pid) if c["id"] != cid and c.get("parent") != cid])


def try_apply(pid: str, cid: str) -> dict:
    """Apply a comment automatically when it is a request the plan understands
    ("remove that zoom", "captions smaller", "keep this section"). Otherwise it stays
    open for Claude to handle."""
    from . import pipeline
    c = next(x for x in load(pid) if x["id"] == cid)
    plan, ops = pipeline.revise(pid, request=c["text"], at=c.get("source_at"))
    if ops:
        return update(pid, cid, status="applied", resolution=f"Plan v{plan['version']}: {json.dumps(ops)[:300]}")
    return c
