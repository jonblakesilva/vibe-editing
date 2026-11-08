"""Command line for Vibe Studio. Claude Code drives the studio through these commands;
you can also run them yourself.

  python -m studio doctor                     check tools (real tests, not guesses)
  python -m studio import <video|folder>      register a recording (original untouched)
  python -m studio plan <project>             transcribe + analyze + write plan.md
  python -m studio revise <project> "make the captions smaller"
  python -m studio approve <project>
  python -m studio preview <project> [--shorts]
  python -m studio render <project> [--shorts]
  python -m studio serve                      open the local dashboard
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from pathlib import Path

from . import brand as brand_mod
from . import config
from . import project as proj_mod


def _progress_printer():
    state = {"stage": None, "last": 0.0}

    def cb(stage: str, p: float) -> None:
        now = time.time()
        if stage != state["stage"] or now - state["last"] > 2 or p >= 1:
            state.update(stage=stage, last=now)
            print(f"  [{stage}] {p * 100:5.1f}%", flush=True)
    return cb


def cmd_doctor(a):
    from . import doctor
    report = doctor.run(fix=a.fix, quick=a.quick)
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        doctor.print_report(report)
    return 0 if report["ready"]["core"] else 1


def cmd_import(a):
    src = Path(a.source).expanduser()
    camera = a.camera
    if getattr(a, "screencam", False) and src.is_dir():
        return _import_screencam(a, src)
    if src.is_dir():
        vids = proj_mod.find_videos(src)
        if not vids:
            print(f"No videos found in {src}")
            return 1
        src = vids[0]
        cams = [v for v in vids[1:] if any(k in v.stem.lower() for k in ("camera", "cam", "webcam", "face"))]
        if cams and not camera:
            camera = str(cams[0])
        print(f"Using {src.name}" + (f" with camera track {Path(camera).name}" if camera else ""))
    proj = proj_mod.create(src, name=a.name, brand=a.brand, mode=a.mode, copy=a.copy, camera=camera)
    print(json.dumps({"project": proj["id"], "duration_s": round(proj["source"]["duration"], 1),
                      "resolution": f"{proj['source']['width']}x{proj['source']['height']}",
                      "folder": str(proj_mod.project_dir(proj["id"]))}, indent=2))
    return 0


def _parse_ranges(text: str | None) -> list[list[float]]:
    out = []
    for part in (text or "").split(","):
        if "-" in part:
            a_, b_ = part.split("-", 1)
            out.append([float(a_), 1e9 if b_.strip() in ("end", "") else float(b_)])
    return out


def _import_screencam(a, folder: Path) -> int:
    """Tella raw export with Camera.mp4 + Screen.mp4 per clip: build the landscape and vertical
    layout masters (originals untouched), then register the landscape one as the project source."""
    from . import brand as brand_mod, compose
    takes = compose.find_takes(folder)
    if not takes:
        print(f"No Camera.mp4 + Screen.mp4 clip folders found in {folder}")
        return 1
    br = brand_mod.load(a.brand)
    cam = _parse_ranges(a.cam)
    out = folder / "layouts"
    print(f"Building screen + camera layouts from {len(takes)} take(s)...")
    land, vert = compose.build_masters(takes, out, cam_ranges=cam,
                                       bg=br["colors"].get("navy") or br["colors"].get("background", "#0F1E4A"),
                                       accent=br["colors"].get("highlight", "#F97316"),
                                       progress=lambda x: print(f"  layouts {x * 100:5.1f}%", end=chr(13), flush=True))
    print()
    proj = proj_mod.create(land, name=a.name, brand=a.brand, mode=a.mode, vertical=vert, cam_ranges=cam)
    print(json.dumps({"project": proj["id"], "duration_s": round(proj["source"]["duration"], 1),
                      "layout": "screencam", "folder": str(proj_mod.project_dir(proj["id"]))}, indent=2))
    return 0


def cmd_download(a):
    import subprocess
    out = config.DATA_HOME / "downloads"
    out.mkdir(parents=True, exist_ok=True)
    print("Only download videos you own or have permission to use.")
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
                        "--merge-output-format", "mp4", "-o", str(out / "%(title).80s [%(id)s].%(ext)s"),
                        "--print", "after_move:filepath", a.url], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-800:])
        return 1
    path = r.stdout.strip().splitlines()[-1]
    print(path)
    if a.import_:
        a.source, a.camera, a.copy = path, None, False
        return cmd_import(a)
    return 0


def cmd_fetch(a):
    """Download a direct file link (e.g. a Tella export downloadUrl) in chunks, then import it."""
    import requests
    from urllib.parse import urlparse
    if urlparse(a.url).scheme != "https":
        print("Only https download links are accepted.")
        return 1
    out = config.DATA_HOME / "tella"
    out.mkdir(parents=True, exist_ok=True)
    name = (a.name or Path(urlparse(a.url).path).stem or "recording").replace("/", "_")[:80]
    stamp = time.strftime('%Y%m%d-%H%M%S')
    with requests.get(a.url, stream=True, timeout=60) as r:
        r.raise_for_status()
        is_zip = "zip" in r.headers.get("content-type", "") or ".zip" in urlparse(a.url).path
        dst = out / f"{stamp}_{name}.{'zip' if is_zip else 'mp4'}"
        total = int(r.headers.get("content-length") or 0)
        done = 0
        cb = _progress_printer()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(4 * 1024 * 1024):
                f.write(chunk)
                done += len(chunk)
                if total:
                    cb("download", done / total)
    print(f"Saved {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    if dst.suffix == ".zip":
        # Tella "raw"/"tracks" exports: separate screen and camera recordings in one zip.
        import zipfile
        folder = dst.with_suffix("")
        with zipfile.ZipFile(dst) as z:
            for m in z.infolist():
                target = (folder / m.filename).resolve()
                if folder.resolve() not in target.parents and target != folder.resolve():
                    raise ValueError(f"Unsafe path in zip: {m.filename}")
            z.extractall(folder)
        print("Contains:", ", ".join(p.name for p in proj_mod.find_videos(folder)))
        a.source = str(folder)
    else:
        a.source = str(dst)
    a.copy = False
    return cmd_import(a)


def cmd_projects(a):
    for p in proj_mod.list_projects():
        print(f"{p['id']:<48} {p['status']:<12} {p['source']['duration'] / 60:6.1f} min  brand={p.get('brand') or '-'}")
    return 0


def cmd_transcribe(a):
    from . import pipeline
    t = pipeline.get_transcript(a.project, engine=a.engine, model=a.model, force=a.force, progress=_progress_printer())
    print(f"{len(t['words'])} words, language={t['language']}, engine={t['engine']}/{t['model']}")
    if t.get("vocabulary_fixes"):
        print("Vocabulary fixes:", t["vocabulary_fixes"])
    return 0


def cmd_words(a):
    from . import pipeline
    t = pipeline.get_transcript(a.project)
    for i, w in enumerate(t["words"]):
        if a.find and a.find.lower() not in w["word"].lower():
            continue
        print(f"{i:>6}  {w['start']:8.2f}  {w['word']}  ({w.get('prob', 1):.2f})")
    return 0


def cmd_correct(a):
    from . import pipeline
    p = pipeline.paths(a.project)["work"] / "corrections.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[str(a.index)] = a.text
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"Word {a.index} -> {a.text!r} (timing unchanged). Re-run plan/preview to apply.")
    return 0


def cmd_plan(a):
    from . import pipeline
    opts = {k: v for k, v in {"caption_style": a.caption_style, "pace": a.pace, "video_type": a.type,
                              "topic": a.topic, "cold_open": a.cold_open or None}.items() if v is not None}
    plan = pipeline.make_plan(a.project, mode=a.mode, outputs=a.outputs.split(",") if a.outputs else None,
                              shorts_count=a.shorts, short_min=a.short_min, short_max=a.short_max,
                              options=opts, progress=_progress_printer())
    d = pipeline.paths(a.project)["dir"]
    print((d / "plan.md").read_text(encoding="utf-8") if not a.quiet else f"Plan written to {d / 'plan.md'}")
    return 0


def cmd_show(a):
    from . import pipeline
    d = pipeline.paths(a.project)
    print((d["dir"] / ("plan.json" if a.json else "plan.md")).read_text(encoding="utf-8"))
    return 0


def cmd_revise(a):
    from . import pipeline
    ops = json.loads(a.ops) if a.ops else None
    plan, applied = pipeline.revise(a.project, request=a.request or "", ops=ops, at=a.at)
    if not applied:
        print("I couldn't turn that request into a plan change automatically. Express it as --ops "
              "(see studio/plan.py revise()) or be more specific.")
        return 2
    print(json.dumps({"version": plan["version"], "status": plan["status"], "applied": applied}, indent=1))
    return 0


def cmd_set(a):
    from . import pipeline
    try:
        value = json.loads(a.value)
    except json.JSONDecodeError:
        value = a.value
    plan, _ = pipeline.revise(a.project, ops=[{"op": "set", "path": a.path, "value": value}],
                              request=f"set {a.path}")
    print(f"{a.path} = {value!r} (plan v{plan['version']})")
    return 0


def cmd_approve(a):
    from . import pipeline
    plan = pipeline.approve(a.project)
    print(f"Plan v{plan['version']} approved at {plan['approved_at']}.")
    return 0


def _render(a, quality):
    from . import pipeline
    cb = _progress_printer()
    results = []
    if not a.shorts_only:
        plan = json.loads(pipeline.paths(a.project)["plan"].read_text(encoding="utf-8"))
        if plan["mode"] != "shorts" or not plan.get("clips"):
            results += pipeline.render_main(a.project, quality=quality, progress=cb)
    if a.shorts or a.shorts_only:
        results += pipeline.render_shorts(a.project, quality=quality, progress=cb,
                                          clean_copy=not getattr(a, "no_clean", False))
    ok = all(r["ok"] for r in results)
    for r in results:
        bad = [k for k, v in r["checks"].items() if not v]
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['path']}  {r['width']}x{r['height']}  "
              f"{r['video_duration']:.1f}s  {r['size_mb']} MB" + (f"  failed: {bad}" if bad else ""))
        for n in r.get("notes", []):
            print(f"      note: {n}")
        if r.get("silent_gaps"):
            print(f"      check: silence left at {', '.join(f'{s}s ({d}s long)' for s, d in r['silent_gaps'][:5])}")
        for it in r.get("listen_issues") or []:
            print(f"      listen: possible {it['type'].replace('_', ' ')} at {it['at']:.1f}s - {it['text'][:70]}")
        if r.get("qa_sheet"):
            print(f"      QA frames: {r['qa_sheet']}")
    return 0 if ok else 1


def cmd_preview(a):
    return _render(a, "preview")


def cmd_render(a):
    return _render(a, "final")


def cmd_brand(a):
    if a.action == "list":
        for b in brand_mod.list_brands():
            print(f"{b['slug']:<28} {b['name']}  {'(complete)' if b.get('complete') else '(interview in progress)'}")
        return 0
    if a.action == "new":
        b = brand_mod.create(a.args[0])
        print(f"Created brand '{b['name']}' ({b['slug']}).")
        q = brand_mod.next_question(b)
        if q:
            print(f"Next question [{q[0]}]: {q[1]}")
        return 0
    b = brand_mod.load(a.args[0])
    if a.action == "show":
        print(json.dumps(b, indent=2))
    elif a.action == "next":
        q = brand_mod.next_question(b)
        print(f"[{q[0]}] {q[1]}" if q else "Brand interview complete.")
    elif a.action == "answer":
        key, value = a.args[1], " ".join(a.args[2:])
        brand_mod.answer(b, key, value)
        q = brand_mod.next_question(b)
        print(f"Saved {key}. " + (f"Next [{q[0]}]: {q[1]}" if q else "Brand interview complete."))
    elif a.action == "set":
        try:
            value = json.loads(" ".join(a.args[2:]))
        except json.JSONDecodeError:
            value = " ".join(a.args[2:])
        from .plan import set_path
        set_path(b, a.args[1], value)
        brand_mod.save(b)
        print(f"{a.args[1]} updated.")
    elif a.action == "add-reference":
        path = brand_mod.import_asset(b, a.args[1], "references")
        b.setdefault("style_references", []).append(path)
        brand_mod.save(b)
        print(f"Saved style reference {path} (used only to guide your edits; not redistributed).")
    return 0


def cmd_keys(a):
    config.KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if a.action == "status":
        config.load_keys()
        for n in config.SECRET_NAMES:
            print(f"{n:<20} {'set' if config.has_key(n) else 'not set'}")
        print(f"(stored privately in {config.KEYS_FILE}, never in the repository)")
        return 0
    name = a.name
    value = getpass.getpass(f"Paste {name} (input hidden): ").strip()
    lines = []
    if config.KEYS_FILE.exists():
        lines = [l for l in config.KEYS_FILE.read_text(encoding="utf-8").splitlines() if not l.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    config.KEYS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{name} saved to {config.KEYS_FILE}")
    return 0


def cmd_comments(a):
    from . import comments
    pid = proj_mod.resolve_id(a.project)
    if a.add:
        c = comments.add(pid, a.add, at=a.at or 0.0, file=a.file)
        print(f"Added comment {c['id']} at {c['at']}s")
        return 0
    if a.reply:
        parent = next((c for c in comments.load(pid) if c["id"] == a.reply), None)
        if not parent:
            print(f"No comment {a.reply}")
            return 1
        c = comments.add(pid, a.text or "", at=parent["at"], file=parent["file"], author="Claude (editor)", parent=a.reply)
        print(f"Replied {c['id']} under {a.reply}")
        return 0
    if a.resolve:
        comments.update(pid, a.resolve, status="resolved", resolution=a.note or "Done")
        print(f"Resolved {a.resolve}")
        return 0
    items = comments.load(pid)
    shown = [c for c in items if a.all or c["status"] == "open"]
    if not shown:
        print("No open comments." if not a.all else "No comments.")
    for c in [x for x in shown if not x.get("parent")]:
        where = "original" if c["file"] == "source" else c["file"]
        src = f" (original {c['source_at']:.1f}s)" if c.get("source_at") is not None and c["file"] != "source" else ""
        rng = f"-{c['end']:.1f}s" if c.get("end") else ""
        extra = " [has drawing]" if c.get("annotation") else ""
        print(f"[{c['id']}] {c['status']:<8} {c.get('author', 'you')} | {where} @ {c['at']:.1f}s{rng}{src}{extra}: {c['text']}")
        for r in [x for x in items if x.get("parent") == c["id"]]:
            print(f"      reply from {r.get('author', 'you')}: {r['text']}")
    return 0


def cmd_serve(a):
    import uvicorn
    from .web.app import app
    print(f"Vibe Studio dashboard: http://127.0.0.1:{a.port}")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


def main(argv=None):
    config.load_keys()
    ap = argparse.ArgumentParser(prog="studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("doctor", help="check and test the toolchain")
    s.add_argument("--fix", action="store_true", help="install missing project-local Python packages")
    s.add_argument("--quick", action="store_true", help="skip the slower real render tests")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    for name, fn in (("import", cmd_import), ("download", cmd_download)):
        s = sub.add_parser(name)
        if name == "import":
            s.add_argument("source", help="video file, or a folder (e.g. Tella export)")
        else:
            s.add_argument("url")
            s.add_argument("--import", dest="import_", action="store_true")
        s.add_argument("--name")
        s.add_argument("--brand")
        s.add_argument("--mode", default="longform", choices=["longform", "shorts", "repurpose"])
        s.add_argument("--copy", action="store_true", help="copy the original into the project folder")
        s.add_argument("--camera", help="separate camera recording (optional)")
        if name == "import":
            s.add_argument("--screencam", action="store_true",
                           help="Tella folder with Camera.mp4 + Screen.mp4 per clip: screen + camera layouts")
            s.add_argument("--cam", help='full-screen camera ranges in seconds, e.g. "0-12.5,340-end"')
        s.set_defaults(fn=fn)

    s = sub.add_parser("fetch", help="download a direct link (e.g. Tella export URL) and import it")
    s.add_argument("url")
    s.add_argument("--name")
    s.add_argument("--brand")
    s.add_argument("--mode", default="longform", choices=["longform", "shorts", "repurpose"])
    s.add_argument("--camera", help="separate camera recording (optional)")
    s.set_defaults(fn=cmd_fetch)

    sub.add_parser("projects").set_defaults(fn=cmd_projects)

    s = sub.add_parser("transcribe")
    s.add_argument("project")
    s.add_argument("--engine", default="local", choices=["local", "groq"])
    s.add_argument("--model")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_transcribe)

    s = sub.add_parser("words", help="list transcript words with indices (for corrections)")
    s.add_argument("project")
    s.add_argument("--find")
    s.set_defaults(fn=cmd_words)

    s = sub.add_parser("correct", help="fix a mis-heard word (timing unchanged)")
    s.add_argument("project")
    s.add_argument("index", type=int)
    s.add_argument("text")
    s.set_defaults(fn=cmd_correct)

    s = sub.add_parser("plan")
    s.add_argument("project")
    s.add_argument("--mode", choices=["longform", "shorts", "repurpose"])
    s.add_argument("--outputs", help="comma list: youtube,youtube_4k,shorts,tiktok,reels,square,linkedin")
    s.add_argument("--shorts", type=int, default=5, help="number of Shorts to find (repurpose mode)")
    s.add_argument("--short-min", type=float, default=20)
    s.add_argument("--short-max", type=float, default=60)
    s.add_argument("--caption-style", choices=["clean", "minimal", "karaoke", "bold"])
    s.add_argument("--pace", choices=["relaxed", "natural", "tight", "shorts"])
    s.add_argument("--type", choices=["tutorial", "sales", "talking_head", "promo", "interview"])
    s.add_argument("--topic")
    s.add_argument("--cold-open", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("show")
    s.add_argument("project")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("revise")
    s.add_argument("project")
    s.add_argument("request", nargs="?")
    s.add_argument("--at", type=float, help="source time in seconds the request refers to")
    s.add_argument("--ops", help="JSON list of revision ops")
    s.set_defaults(fn=cmd_revise)

    s = sub.add_parser("set", help="set one plan value, e.g. captions.size_scale 0.8")
    s.add_argument("project")
    s.add_argument("path")
    s.add_argument("value")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("approve")
    s.add_argument("project")
    s.set_defaults(fn=cmd_approve)

    for name, fn in (("preview", cmd_preview), ("render", cmd_render)):
        s = sub.add_parser(name)
        s.add_argument("project")
        s.add_argument("--shorts", action="store_true", help="also render the selected Shorts")
        s.add_argument("--shorts-only", action="store_true")
        if name == "render":
            s.add_argument("--no-clean", action="store_true", help="skip caption-free copies of Shorts")
        s.set_defaults(fn=fn)

    s = sub.add_parser("brand")
    s.add_argument("action", choices=["list", "new", "show", "next", "answer", "set", "add-reference"])
    s.add_argument("args", nargs="*")
    s.set_defaults(fn=cmd_brand)

    s = sub.add_parser("keys")
    s.add_argument("action", choices=["set", "status"])
    s.add_argument("name", nargs="?", choices=list(config.SECRET_NAMES))
    s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("comments", help="list, add or resolve review comments")
    s.add_argument("project")
    s.add_argument("--add", help="comment text")
    s.add_argument("--at", type=float, help="seconds into the file")
    s.add_argument("--file", default="source", help="'source' or an export path like name_youtube.mp4")
    s.add_argument("--resolve", help="comment id to mark resolved")
    s.add_argument("--reply", help="comment id to reply to (use with --text)")
    s.add_argument("--text", help="reply text")
    s.add_argument("--note", help="what was done (with --resolve)")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_comments)

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except (FileNotFoundError, PermissionError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
