"""Local dashboard API (binds to 127.0.0.1 only). Long work runs as background jobs
whose real progress the page polls."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .. import brand as brand_mod
from .. import config, pipeline
from .. import plan as plan_mod
from .. import project as proj_mod
from ..jobs import JobManager

app = FastAPI(title="Vibe Studio")


def _log(name: str, line: str) -> None:
    d = config.DATA_HOME / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / name, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


@app.middleware("http")
async def request_log(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.method != "GET" or response.status_code >= 400:
        _log("server.log", f"{request.method} {request.url.path} -> {response.status_code}")
    return response


@app.post("/api/clientlog")
def client_log(body: dict = Body(...)):
    _log("client.log", config.redact(json.dumps(body)[:2000]))
    return {"ok": True}
STATIC = Path(__file__).parent / "static"
jobs: JobManager | None = None


def jm() -> JobManager:
    global jobs
    if jobs is None:
        config.ensure_dirs()
        jobs = JobManager()
    return jobs


def _err(e: Exception, code: int = 400):
    raise HTTPException(code, config.redact(str(e)))


NO_CACHE = {"Cache-Control": "no-cache"}  # always serve the latest page code after an update


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"), headers=NO_CACHE)


@app.get("/static/{name}")
def static(name: str):
    p = (STATIC / name).resolve()
    if p.parent != STATIC.resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers=NO_CACHE)


# ------------------------------------------------------------ projects

@app.get("/api/projects")
def projects():
    return proj_mod.list_projects()


@app.post("/api/projects")
async def create_project(file: UploadFile | None = File(None), path: str | None = Form(None),
                         name: str | None = Form(None), brand: str | None = Form(None),
                         mode: str = Form("longform")):
    try:
        if file is not None and file.filename:
            up = config.DATA_HOME / "uploads"
            up.mkdir(parents=True, exist_ok=True)
            dst = up / f"{time.strftime('%Y%m%d-%H%M%S')}_{Path(file.filename).name}"
            with open(dst, "wb") as f:  # streamed in chunks; never held in memory
                while chunk := await file.read(4 * 1024 * 1024):
                    f.write(chunk)
            src = dst
        elif path:
            src = Path(path.strip('"')).expanduser()
            if src.is_dir():
                vids = proj_mod.find_videos(src)
                if not vids:
                    raise FileNotFoundError(f"No videos found in {src}")
                src = vids[0]
        else:
            raise ValueError("Choose a video file or paste a file/folder path.")
        return proj_mod.create(src, name=name or None, brand=brand or None, mode=mode)
    except Exception as e:
        _err(e)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    try:
        proj = proj_mod.load(pid)
    except Exception as e:
        _err(e, 404)
    p = pipeline.paths(proj["id"])
    plan = json.loads(p["plan"].read_text(encoding="utf-8")) if p["plan"].exists() else None
    segments = None
    if plan:
        tl = plan_mod.timeline(plan)
        segments = tl.segments
        plan["stats"] = plan_mod.stats(plan)
    exports = sorted(str(x.relative_to(p["exports"])).replace("\\", "/") for x in p["exports"].rglob("*")
                     if x.is_file() and ".part." not in x.name and "versions" not in x.parts)
    return {"project": proj, "plan": plan, "segments": segments,
            "plan_md": (p["dir"] / "plan.md").read_text(encoding="utf-8") if (p["dir"] / "plan.md").exists() else None,
            "exports": exports}


@app.get("/api/projects/{pid}/thumb.jpg")
def thumb(pid: str):
    """Small poster frame for the library (from the latest export, else the original)."""
    import subprocess
    p = pipeline.paths(pid)
    out = p["work"] / "thumb.jpg"
    exports = sorted(p["exports"].glob("*youtube*.mp4")) or sorted(p["exports"].glob("*.mp4"))
    src = exports[0] if exports else (p["work"] / "browser_proxy.mp4" if (p["work"] / "browser_proxy.mp4").exists()
                                      else Path(proj_mod.load(pid)["source"]["path"]))
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        from .. import media
        dur = media.probe(src).duration
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * 0.3:.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=640:-2", "-q:v", "4", str(out)], capture_output=True)
    if not out.exists():
        raise HTTPException(404)
    return FileResponse(out, headers={"Cache-Control": "no-cache"})


@app.get("/api/music")
def music_library():
    """Licensed tracks and sound effects available to use (with their license info)."""
    out = {}
    for kind, d in (("music", config.MUSIC_DIR), ("sfx", config.DATA_HOME / "sfx")):
        man = d / "manifest.json"
        items = json.loads(man.read_text(encoding="utf-8")) if man.exists() else []
        for it in items:
            it["path"] = str(d / it.get("file", ""))
        out[kind] = [it for it in items if Path(it["path"]).exists()]
    return out


@app.get("/api/projects/{pid}/transcript")
def get_transcript(pid: str):
    p = pipeline.paths(pid)
    if not p["transcript"].exists():
        return {"words": []}
    t = json.loads(p["transcript"].read_text(encoding="utf-8"))
    corr = p["work"] / "corrections.json"
    if corr.exists():
        from .. import transcribe
        transcribe.apply_corrections(t, json.loads(corr.read_text(encoding="utf-8")))
    return {"words": t["words"], "engine": t.get("engine"), "language": t.get("language")}


@app.post("/api/projects/{pid}/correct")
def correct(pid: str, body: dict = Body(...)):
    p = pipeline.paths(pid)["work"] / "corrections.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[str(int(body["index"]))] = str(body["text"])
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"ok": True}


@app.post("/api/projects/{pid}/plan")
def make_plan(pid: str, body: dict = Body(default={})):
    pid = proj_mod.resolve_id(pid)
    opts = {k: body[k] for k in ("caption_style", "pace", "video_type", "topic", "cold_open") if body.get(k)}
    return jm().submit("plan", pid, pipeline.make_plan, pid=pid, mode=body.get("mode"),
                       outputs=body.get("outputs") or None, shorts_count=int(body.get("shorts_count", 5)),
                       short_min=float(body.get("short_min", 20)), short_max=float(body.get("short_max", 60)),
                       options=opts)


@app.post("/api/projects/{pid}/revise")
def revise(pid: str, body: dict = Body(...)):
    try:
        plan, ops = pipeline.revise(pid, request=body.get("request", ""), ops=body.get("ops"), at=body.get("at"))
    except Exception as e:
        _err(e)
    note = None
    if not ops and body.get("request"):
        # not something the plan can change by itself: keep it as a note for Claude instead of losing it
        from .. import comments
        note = comments.add(proj_mod.resolve_id(pid), body["request"], at=float(body.get("at") or 0),
                            file=body.get("file") or "source", author=body.get("author") or "you")
    return {"applied": ops, "version": plan["version"], "understood": bool(ops), "saved_note": bool(note)}


@app.post("/api/projects/{pid}/approve")
def approve(pid: str):
    return pipeline.approve(pid)


@app.post("/api/projects/{pid}/render")
def render(pid: str, body: dict = Body(default={})):
    pid = proj_mod.resolve_id(pid)
    quality = "final" if body.get("quality") == "final" else "preview"
    what = body.get("what", "main")
    if quality == "final":
        plan = json.loads(pipeline.paths(pid)["plan"].read_text(encoding="utf-8"))
        if plan["status"] not in ("approved", "rendered"):
            raise HTTPException(409, "Approve the plan before the final render.")
    fn = pipeline.render_shorts if what == "shorts" else pipeline.render_main
    return jm().submit(f"render-{what}-{quality}", pid, fn, pid=pid, quality=quality)


def _playable(f: Path, work: Path, key: str) -> Path:
    """In-app playback copy: same video stream, audio as Opus. Some browsers (notably the one
    built into VS Code) show H.264 picture but cannot play AAC audio. Downloads keep AAC."""
    import subprocess
    out = work / "play" / (key.replace("/", "__") + ".mp4")
    if out.exists() and out.stat().st_mtime >= f.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy",
                        "-c:a", "libopus", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        _log("server.log", f"playable copy failed for {f.name}: {r.stderr[-300:]}")
        return f
    tmp.replace(out)
    return out


@app.get("/media/{pid}/{kind}/{rel:path}")
def media(pid: str, kind: str, rel: str):
    p = pipeline.paths(pid)
    if kind == "play":  # browser-friendly playback of an export ("source" = the original)
        if rel in ("source", "source/file"):
            proxy = p["work"] / "browser_proxy.mp4"
            src = proxy if proxy.exists() else Path(proj_mod.load(pid)["source"]["path"])
        else:
            base = p["exports"].resolve()
            src = (base / rel).resolve()
            if base not in src.parents or not src.exists():
                raise HTTPException(404)
        return FileResponse(_playable(src, p["work"], rel), media_type="video/mp4")
    if kind == "source":
        proxy = p["work"] / "browser_proxy.mp4"
        f = proxy if proxy.exists() else Path(proj_mod.load(pid)["source"]["path"])
    elif kind == "exports":
        base = p["exports"].resolve()
        f = (base / rel).resolve()
        if base not in f.parents:
            raise HTTPException(403)
    else:
        raise HTTPException(404)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)  # supports Range requests for seeking


# ------------------------------------------------------------ comments

@app.get("/api/projects/{pid}/comments")
def list_comments(pid: str):
    from .. import comments
    return comments.load(proj_mod.resolve_id(pid))


@app.post("/api/projects/{pid}/comments")
def add_comment(pid: str, body: dict = Body(...)):
    from .. import comments
    if not str(body.get("text", "")).strip():
        raise HTTPException(400, "Write a comment first.")
    try:
        return comments.add(proj_mod.resolve_id(pid), body["text"], at=float(body.get("at", 0)),
                            file=body.get("file", "source"), author=body.get("author") or "you",
                            end=body.get("end"), annotation=body.get("annotation"), parent=body.get("parent"))
    except KeyError as e:
        _err(e)


@app.post("/api/projects/{pid}/comments/{cid}")
def edit_comment(pid: str, cid: str, body: dict = Body(...)):
    from .. import comments
    pid = proj_mod.resolve_id(pid)
    try:
        if body.get("action") == "apply":
            return comments.try_apply(pid, cid)
        if body.get("action") == "delete":
            comments.delete(pid, cid)
            return {"deleted": cid}
        return comments.update(pid, cid, **{k: v for k, v in body.items() if k != "action"})
    except Exception as e:
        _err(e)


@app.get("/api/projects/{pid}/assets")
def list_assets(pid: str):
    from .. import review
    return review.assets(proj_mod.resolve_id(pid))


@app.post("/api/projects/{pid}/assets/status")
def asset_status(pid: str, body: dict = Body(...)):
    from .. import review
    try:
        return review.set_status(proj_mod.resolve_id(pid), body["file"], body["status"], body.get("author") or "you")
    except ValueError as e:
        _err(e)


@app.get("/review/{pid}", response_class=HTMLResponse)
def review_page(pid: str):
    return HTMLResponse((STATIC / "review.html").read_text(encoding="utf-8"), headers=NO_CACHE)


# ------------------------------------------------------------ jobs

@app.get("/api/jobs")
def list_jobs(project: str | None = None):
    return jm().list(project)


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    return {"cancelled": jm().cancel(jid)}


@app.post("/api/jobs/{jid}/retry")
def retry(jid: str):
    try:
        return jm().retry(jid)
    except Exception as e:
        _err(e)


# ------------------------------------------------------------ brands

@app.get("/api/brands")
def brands():
    return brand_mod.list_brands()


@app.post("/api/brands")
def new_brand(body: dict = Body(...)):
    b = brand_mod.create(body["name"])
    return {"brand": b, "next": brand_mod.next_question(b)}


@app.get("/api/brands/{slug}")
def get_brand(slug: str):
    b = brand_mod.load(slug)
    return {"brand": b, "next": brand_mod.next_question(b)}


@app.post("/api/brands/{slug}/answer")
def answer(slug: str, body: dict = Body(...)):
    try:
        b = brand_mod.answer(brand_mod.load(slug), body["key"], body["value"])
    except Exception as e:
        _err(e)
    return {"brand": b, "next": brand_mod.next_question(b)}


@app.get("/api/status")
def status():
    from .. import motion
    return {"motion_graphics": motion.available(), "data_home": str(config.DATA_HOME),
            "ffmpeg": shutil.which("ffmpeg") is not None}
