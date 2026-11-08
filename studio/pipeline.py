"""End-to-end pipeline used by the CLI, the dashboard and Claude Code."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from . import analyze as an
from . import brand as brand_mod
from . import plan as plan_mod
from . import project as proj_mod
from . import media, reframe, render, repurpose, shorts, transcribe
from .timeline import Timeline, keep_segments


def _noop(stage: str, p: float) -> None:
    pass


def paths(pid: str) -> dict:
    d = proj_mod.project_dir(proj_mod.resolve_id(pid))
    return {"dir": d, "work": d / "work", "exports": d / "exports", "plan": d / "plan.json",
            "transcript": d / "work" / "transcript.json", "faces": d / "work" / "faces.json"}


def get_transcript(pid: str, *, engine: str = "local", model: str | None = None, force: bool = False,
                   progress=_noop, cancel: threading.Event | None = None) -> dict:
    proj = proj_mod.load(pid)
    p = paths(pid)
    br = brand_mod.load(proj.get("brand"))
    vocab = list(dict.fromkeys((br.get("vocabulary") or []) + ([br["name"]] if br.get("slug") != "default" else [])))
    t = transcribe.transcribe(Path(proj["source"]["path"]), p["work"], engine=engine,
                              model=model or transcribe.DEFAULT_MODEL, force=force, vocabulary=vocab,
                              on_progress=lambda x: progress("transcribe", x), cancel=cancel)
    merged = transcribe.merge_split_numbers(t["words"])  # also fixes transcripts cached earlier
    if len(merged) != len(t["words"]):
        t["words"] = merged
        # persist so word numbers (used by manual corrections) match everywhere
        p["transcript"].write_text(json.dumps(t, indent=1), encoding="utf-8")
    t["vocabulary_fixes"] = transcribe.apply_vocabulary(t, vocab)
    corr = p["work"] / "corrections.json"
    if corr.exists():
        transcribe.apply_corrections(t, json.loads(corr.read_text(encoding="utf-8")))
    if proj.get("status") == "imported":  # never move a project backwards
        proj["status"] = "transcribed"
        proj_mod.save(proj)
    return t


BROWSER_SAFE = {"h264", "vp8", "vp9", "av1"}


def ensure_proxy(pid: str, progress=_noop, cancel=None) -> Path | None:
    """A small H.264/AAC-stereo copy of the original for in-browser review when the original
    uses a codec browsers often cannot play (e.g. HEVC from Tella or iPhones) or mono audio.
    The original file is untouched and still used for every render."""
    proj = proj_mod.load(pid)
    src = Path(proj["source"]["path"])
    out = paths(pid)["work"] / "browser_proxy.mp4"
    if out.exists():
        return out
    info = media.probe(src)
    mono = False
    if info.has_audio:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                            "-of", "csv=p=0", str(src)], capture_output=True, text=True)
        mono = r.stdout.strip() == "1"
    if info.vcodec in BROWSER_SAFE and not mono:
        return None
    tmp = out.with_suffix(".part.mp4")
    media.run_ffmpeg(["-i", str(src), "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "veryfast",
                      "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-b:a", "128k",
                      "-movflags", "+faststart", str(tmp)], duration=info.duration, cancel=cancel,
                     on_progress=lambda x: progress("browser copy", x))
    tmp.replace(out)
    return out


def get_faces(pid: str, progress=_noop) -> list[dict]:
    p = paths(pid)
    if p["faces"].exists():
        return json.loads(p["faces"].read_text(encoding="utf-8"))
    proj = proj_mod.load(pid)
    progress("faces", 0.0)
    faces = reframe.track_faces(proj["source"]["path"], sample_fps=1.0)
    p["faces"].write_text(json.dumps(faces), encoding="utf-8")
    progress("faces", 1.0)
    return faces


def make_plan(pid: str, *, mode: str | None = None, outputs: list[str] | None = None,
              shorts_count: int = 5, short_min: float = 20, short_max: float = 60,
              options: dict | None = None, progress=_noop, cancel=None) -> dict:
    proj = proj_mod.load(pid)
    mode = mode or proj.get("mode", "longform")
    t = get_transcript(pid, progress=progress, cancel=cancel)
    ensure_proxy(pid, progress=progress, cancel=cancel)
    br = brand_mod.load(proj.get("brand"))
    opts = dict(options or {})
    plan = plan_mod.build(proj, t, brand=br, mode="longform" if mode == "repurpose" else mode,
                          outputs=outputs, options=opts)
    plan["mode"] = mode
    if mode in ("shorts", "repurpose"):
        analysis = an.analyze(t, pace="shorts", duration=proj["source"]["duration"])
        topics = (br.get("topics") or []) + plan["summary"]["keywords"]
        plan["clips"] = shorts.find_clips(t, analysis, count=shorts_count, min_len=short_min,
                                          max_len=short_max, topics=topics)
        plan["shorts_settings"] = {"count": shorts_count, "min_len": short_min, "max_len": short_max,
                                   "outputs": ["shorts"], "captions": "both"}
        if mode == "repurpose":
            plan["outputs"] = [dict(plan_mod.PLATFORM_OUTPUTS["youtube"], name="youtube")]
    if mode == "shorts":
        # a single short-form edit of the whole recording
        plan["outputs"] = [dict(plan_mod.PLATFORM_OUTPUTS[o], name=o) for o in (outputs or ["shorts"])]
    plan["repurpose"] = repurpose.generate(plan, t, br)
    plan_mod.save(plan, paths(pid)["plan"])
    proj = proj_mod.load(pid)
    if proj.get("status") in ("imported", "transcribed"):
        proj["status"] = "planned"
    proj_mod.save(proj)
    return plan


def approve(pid: str) -> dict:
    p = paths(pid)
    plan = plan_mod.load(p["plan"])
    plan["status"] = "approved"
    plan["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    plan_mod.save(plan, p["plan"])
    return plan


def revise(pid: str, *, request: str = "", ops: list[dict] | None = None, at: float | None = None) -> tuple[dict, list]:
    p = paths(pid)
    plan = plan_mod.load(p["plan"])
    ops = ops if ops is not None else plan_mod.parse_request(plan, request, at)
    if not ops:
        return plan, []
    plan = plan_mod.revise(plan, ops, request)
    plan_mod.save(plan, p["plan"])
    return plan, ops


def _require_approved(plan: dict, quality: str) -> None:
    if quality == "final" and plan["status"] not in ("approved", "rendered"):
        raise PermissionError("The editing plan has not been approved yet. Review plan.md, then approve it "
                              "(python -m studio approve <project>). Previews do not need approval.")


def render_main(pid: str, *, quality: str = "preview", progress=_noop,
                cancel: threading.Event | None = None) -> list[dict]:
    """Render the main edit (long-form, or a full-recording short) for every output."""
    p = paths(pid)
    proj = proj_mod.load(pid)
    plan = plan_mod.load(p["plan"])
    _require_approved(plan, quality)
    t = get_transcript(pid)
    tl = plan_mod.timeline(plan)
    fps = plan["source"].get("fps") or 30.0
    cut = render.render_cut(plan["source"]["path"], tl.segments, p["work"], fps=fps, quality=quality,
                            progress=progress, cancel=cancel)
    words = tl.map_words(t["words"])
    faces_src = get_faces(pid, progress) if proj["source"].get("width") else []
    faces = _faces_on_timeline(faces_src, tl)
    results = []
    for out in plan["outputs"]:
        name = f"{_safe(plan['summary']['topic'])}_{out['name']}{'_preview' if quality == 'preview' else ''}"
        out_path = p["exports"] / f"{name}.mp4"
        fsum = reframe.summarize(faces)
        gfx = render.graphics_for_output(plan, tl, _spec_for(out, quality), p["work"] / "motion",
                                         face_x=fsum["cx"] if fsum else None, face_w=fsum["w"] if fsum else None)
        info = render.finish(cut, plan, tl, words, out, out_path, p["work"], quality=quality, graphics=gfx,
                             faces=faces, progress=progress, cancel=cancel)
        rep = render.verify(out_path, expect_w=info["width"], expect_h=info["height"], expect_dur=tl.duration)
        rep["captions"] = info["captions"]
        rep["notes"] = info.get("notes", [])
        # QA sheet: frames 0.9 s into every graphic plus one every ~6 s
        gt = [g["start"] + min(0.9, g["duration"] / 2) for g in gfx] + [i * 6.0 + 1 for i in range(int(tl.duration // 6) + 1)]
        sheet = render.contact_sheet(out_path, gt, p["exports"] / "qa" / f"{out_path.stem}_sheet.jpg",
                                     width=480 if out["width"] >= out["height"] else 240)
        rep["qa_sheet"] = str(sheet) if sheet else None
        results.append(rep)
    if plan["mode"] == "longform" or plan["mode"] == "repurpose":
        _write_extras(p["exports"], plan, tl)
    plan["last_render"] = {"quality": quality, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    if quality == "final" and all(r["ok"] for r in results):
        plan["status"] = "rendered"
    plan_mod.save(plan, p["plan"])
    proj["exports"] = sorted(set(proj.get("exports", []) + [r["path"] for r in results]))
    proj["status"] = "rendered" if quality == "final" else "previewed"
    proj_mod.save(proj)
    return results


def render_shorts(pid: str, *, quality: str = "preview", ids: list[str] | None = None, clean_copy: bool = True,
                  progress=_noop, cancel: threading.Event | None = None) -> list[dict]:
    """Render each selected Short as its own vertical video (captioned + optional clean copy)."""
    p = paths(pid)
    plan = plan_mod.load(p["plan"])
    _require_approved(plan, quality)
    t = get_transcript(pid)
    fps = plan["source"].get("fps") or 30.0
    analysis = an.analyze(t, pace="shorts", duration=plan["source"]["duration"])
    faces_src = get_faces(pid, progress) if plan["source"].get("width") else []
    clips = [c for c in plan.get("clips", []) if c.get("enabled", True) and (not ids or c["id"] in ids)]
    results = []
    for k, clip in enumerate(clips):
        # automatic tight-pace cuts plus every cut the editor added or kept in the plan
        plan_cuts = [c for c in plan["cuts"] if c.get("enabled", True) and
                     c["type"] in ("manual", "restart", "repeat", "false_start", "noise")]
        # bad-take decisions come from the plan (the editor may have restored a take);
        # the tight Shorts pass only adds pause / filler / dead-air trims
        pacing = [c for c in analysis["cuts"] if c["type"] in ("pause", "filler", "dead_air")]
        window_cuts = [dict(c) for c in pacing + plan_cuts
                       if c["end"] > clip["start"] and c["start"] < clip["end"]]
        for k in plan.get("keep_overrides", []):
            window_cuts = plan_mod._subtract(window_cuts, k["start"], k["end"])
        window_cuts += [{"start": 0, "end": clip["start"], "enabled": True},
                        {"start": clip["end"], "end": plan["source"]["duration"], "enabled": True}]
        segs = keep_segments(plan["source"]["duration"], window_cuts, fps=fps)
        tl = Timeline(segs)
        sub = (lambda st, x, k=k: progress(f"short {k + 1}/{len(clips)} {st}", x))
        cut = render.render_cut(plan["source"]["path"], segs, p["work"], fps=fps, quality=quality,
                                progress=sub, cancel=cancel)
        words = tl.map_words(t["words"])
        faces = _faces_on_timeline(faces_src, tl)
        splan = dict(plan, captions=dict(plan["captions"], **_shorts_caption_style(plan)),
                     zooms=[z for z in plan_mod.default_zooms(
                         {"sentences": [s for s in analysis["sentences"] if clip["start"] <= s["start"] < clip["end"]]},
                         "talking_head", "shorts")],
                     graphics=_short_graphics(plan, clip))
        for out_name in plan.get("shorts_settings", {}).get("outputs", ["shorts"]):
            out = dict(plan_mod.PLATFORM_OUTPUTS[out_name], name=out_name)
            base = f"short{k + 1:02d}_{_safe(clip['title'])}_{out_name}{'_preview' if quality == 'preview' else ''}"
            out_path = p["exports"] / "shorts" / f"{base}.mp4"
            gfx = render.graphics_for_output(splan, tl, _spec_for(out, quality), p["work"] / "motion",
                                             clip_window=(0, tl.duration))
            info = render.finish(cut, splan, tl, words, out, out_path, p["work"], quality=quality,
                                 graphics=gfx, faces=faces, burn_captions=True, progress=sub, cancel=cancel)
            rep = render.verify(out_path, expect_w=info["width"], expect_h=info["height"], expect_dur=tl.duration)
            rep.update({"clip": clip["id"], "captions": info["captions"]})
            results.append(rep)
            if clean_copy and quality == "final":
                clean = out_path.with_name(base + "_clean.mp4")
                info2 = render.finish(cut, splan, tl, words, out, clean, p["work"], quality=quality, graphics=gfx,
                                      faces=faces, burn_captions=False, progress=sub, cancel=cancel)
                rep2 = render.verify(clean, expect_w=info2["width"], expect_h=info2["height"], expect_dur=tl.duration)
                rep2["clip"] = clip["id"]
                results.append(rep2)
    plan = plan_mod.load(p["plan"])
    plan["last_shorts_render"] = {"quality": quality, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    plan_mod.save(plan, p["plan"])
    return results


def _shorts_caption_style(plan: dict) -> dict:
    if plan["mode"] == "repurpose" and plan["captions"]["style"] in ("clean", "minimal") and plan["captions"].get("box") != "rounded":
        return {k: v for k, v in plan_mod.CAPTION_STYLES["karaoke"].items() if k != "highlight"} | {"style": "karaoke"}
    return {}


def _short_graphics(plan: dict, clip: dict) -> list[dict]:
    g = [x for x in plan.get("graphics", []) if x.get("enabled", True) and clip["start"] <= x["start"] < clip["end"]
         and x["template"] in ("KineticTitle", "EditorialTitle", "Callout", "CallToAction", "StatPanels",
                               "FloatingCards", "EndCard", "File")]
    return g


def _faces_on_timeline(faces: list[dict], tl: Timeline) -> list[dict]:
    out = []
    for f in faces:
        e = tl.to_edit(f["t"])
        if e is not None:
            out.append({**f, "t": round(e, 3)})
    return out


def _spec_for(out: dict, quality: str) -> dict:
    if quality == "preview":
        return dict(out, width=out["width"] // 2 // 2 * 2, height=out["height"] // 2 // 2 * 2)
    return out


def _safe(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:40] or "video"


def _write_extras(exports: Path, plan: dict, tl: Timeline) -> None:
    lines = [f"{plan_mod.fmt_time(tl.to_edit_nearest(c['start'])).split('.')[0]} {c['title']}"
             for c in plan.get("chapters", [])]
    if len(lines) >= 3:
        (exports / "chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        (exports / "chapters.txt").write_text(
            "\n".join(lines) + "\n\n(YouTube needs at least 3 chapters of 10+ seconds; this video has fewer.)\n",
            encoding="utf-8")
    (exports / "publishing_pack.md").write_text(repurpose.to_markdown(plan.get("repurpose", {})), encoding="utf-8")
