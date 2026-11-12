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
from . import qa as qa_mod
from . import media, reframe, render, repurpose, shorts, transcribe
from .timeline import Timeline, keep_segments, pad_cut_starts


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
                                   "outputs": ["shorts"], "captions": "both",
                                   "pace": plan.get("shorts_settings", {}).get("pace", "playbook")}
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
    if any(o.get("op") == "pace" for o in ops):  # pace needs the transcript to rebuild pause cuts
        words = get_transcript(pid)["words"]
        ops = [dict(o, _words=words) if o.get("op") == "pace" else o for o in ops]
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
    cuts = {}

    def cut_for(src):
        if src not in cuts:
            cuts[src] = render.render_cut(src, tl.segments, p["work"], fps=fps, quality=quality,
                                          progress=progress, cancel=cancel)
        return cuts[src]
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
        src, laid_out = _source_for(plan, out)
        oplan = _layout_plan(plan, tl) if laid_out else _landscape_layout_plan(plan)
        info = render.finish(cut_for(src), oplan, tl, words, out, out_path,
                             p["work"], quality=quality, graphics=gfx, faces=[] if laid_out else faces,
                             progress=progress, cancel=cancel)
        rep = render.verify(out_path, expect_w=info["width"], expect_h=info["height"], expect_dur=tl.duration)
        rep["captions"] = info["captions"]
        rep["notes"] = info.get("notes", [])
        # QA sheet: frames 0.9 s into every graphic plus one every ~6 s
        gt = [g["start"] + min(0.9, g["duration"] / 2) for g in gfx] + [i * 6.0 + 1 for i in range(int(tl.duration // 6) + 1)]
        sheet = render.contact_sheet(out_path, gt, p["exports"] / "qa" / f"{out_path.stem}_sheet.jpg",
                                     width=480 if out["width"] >= out["height"] else 240)
        rep["qa_sheet"] = str(sheet) if sheet else None
        # B4 mouth check: the speaker's mouth shouldn't be covered by a caption or graphic
        mouth_faces = [] if laid_out else info.get("out_faces", faces)
        rep["mouth_issues"] = qa_mod.mouth_check(
            mouth_faces, qa_mod.caption_boxes(words, oplan["captions"], info["width"], info["height"]),
            qa_mod.graphic_boxes(gfx, info["width"], info["height"]), info["width"], info["height"],
            _joins(tl), tl.duration) if mouth_faces else []
        rep["word_issues"] = []
        if quality == "preview" and out == plan["outputs"][0] and tl.duration < 15 * 60:
            progress("listen-back check", 0.0)
            rep["listen_issues"] = listen_check_isolated(out_path, p["work"], tl=tl, words=words)
            progress("listen-back check", 1.0)
            rep["word_issues"] = [i for i in (rep["listen_issues"] or []) if i.get("type") == "clipped_word"]
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


def _joins(tl: Timeline) -> list[float]:
    """Edited-time position of every cut: the boundary between one kept segment and the
    next (there's no gap in edited time, so each boundary is a single point)."""
    return [round(tl.offsets[i], 3) for i in range(1, len(tl.segments))]


def _write_expected_words(work: Path, out_path: Path, tl: Timeline, words: list[dict]) -> Path:
    """expected_words (edited time, from the Timeline mapping of kept transcript words) plus
    the joins, for the isolated listen_check subprocess to run qa.word_whole_check against."""
    d = work / "_listen"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{out_path.stem}_expected.json"
    data = {"words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
            "joins": _joins(tl)}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def listen_check(out_path: Path, work: Path, expected_path: Path | None = None,
                 joins: list[float] | None = None) -> list[dict]:
    """Listen back to the RENDERED video: transcribe it and flag leftover restarts, repeats,
    false starts and filler words, with their times in the edited video. Catches stumbles the
    first transcription merged into a single long word.

    With `expected_path` (a JSON file of {"words": [...], "joins": [...]}, see
    _write_expected_words), also runs the B3 "every word whole" check: words the edit kept,
    compared to what was actually heard near every cut. `joins`, when given, overrides the
    joins stored in that JSON."""
    from . import analyze as an_mod
    heard = transcribe.transcribe(out_path, work / "_listen" / out_path.stem, model=transcribe.DEFAULT_MODEL)
    words = heard["words"]
    sents = an_mod.sentences(words, gap=0.6)
    issues = []
    for c in an_mod.find_restarts_and_repeats(words, sents) + an_mod.find_fillers(words, aggressive=False):
        issues.append({"at": round(c["start"], 2), "end": round(c["end"], 2), "type": c["type"],
                       "text": c.get("text", ""), "reason": c["reason"]})
    # a phrase that starts, stops and restarts within a few words ("one business that we.. one business we")
    toks = [an_mod.norm(w["word"]) for w in words]
    for i in range(len(toks) - 3):
        for j in range(i + 2, min(i + 9, len(toks) - 1)):
            if toks[i] and toks[i:i + 2] == toks[j:j + 2] and toks[i] not in ("the", "and", "a", "to", "of", "i"):
                issues.append({"at": round(words[i]["start"], 2), "end": round(words[j]["start"], 2), "type": "restart",
                               "text": " ".join(w["word"] for w in words[i:j + 2]),
                               "reason": f'"{words[i]["word"]} {words[i + 1]["word"]}" said twice close together'})
                break
    if expected_path is not None:
        data = json.loads(Path(expected_path).read_text(encoding="utf-8"))
        j = joins if joins is not None else data["joins"]
        for wi in qa_mod.word_whole_check(data["words"], words, j):
            issues.append({"at": wi["at"], "end": wi["at"], "type": "clipped_word",
                           "text": wi["heard"] or wi["expected"], "reason": wi["reason"]})
    seen, out = set(), []
    for it in sorted(issues, key=lambda x: x["at"]):
        key = round(it["at"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def listen_check_isolated(out_path: Path, work: Path, timeout: int = 900, *,
                          tl: Timeline | None = None, words: list[dict] | None = None) -> list[dict] | None:
    """Run listen_check in a separate process. Inside a render the speaker-mask library and the
    transcriber can contend for threads and stall; a fresh process avoids that.

    When `tl` and `words` (the edited-time kept transcript words) are given, also writes the
    expected-words/joins JSON for the B3 word-whole check and passes its path through to the
    subprocess."""
    import sys
    expected_path = _write_expected_words(work, out_path, tl, words) if (tl is not None and words is not None) else None
    code = ("import json,sys; from pathlib import Path; from studio import pipeline; "
            "ep = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != '-' else None; "
            "print('@@'+json.dumps(pipeline.listen_check(Path(sys.argv[1]), Path(sys.argv[2]), expected_path=ep)))")
    args = [sys.executable, "-c", code, str(out_path), str(work), str(expected_path) if expected_path else "-"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=str(Path(__file__).resolve().parent.parent))
    except subprocess.TimeoutExpired:
        return None
    line = next((l for l in r.stdout.splitlines() if l.startswith("@@")), None)
    return json.loads(line[2:]) if line else None


def render_shorts(pid: str, *, quality: str = "preview", ids: list[str] | None = None, clean_copy: bool = True,
                  progress=_noop, cancel: threading.Event | None = None) -> list[dict]:
    """Render each selected Short as its own vertical video (captioned + optional clean copy)."""
    p = paths(pid)
    plan = plan_mod.load(p["plan"])
    _require_approved(plan, quality)
    t = get_transcript(pid)
    fps = plan["source"].get("fps") or 30.0
    pace = plan.get("shorts_settings", {}).get("pace", "shorts")
    analysis = an.analyze(t, pace=pace, duration=plan["source"]["duration"],
                          filler_guard=bool(plan.get("filler_guard")))
    faces_src = get_faces(pid, progress) if plan["source"].get("width") else []
    clips = [c for c in plan.get("clips", []) if c.get("enabled", True) and (not ids or c["id"] in ids)]
    results = []
    for k, clip in enumerate(clips):
        # automatic tight-pace cuts plus every cut the editor added or kept in the plan
        plan_cuts = [c for c in plan["cuts"] if c.get("enabled", True) and
                     c["type"] in ("manual", "retake", "restart", "repeat", "false_start", "noise")]
        # bad-take decisions come from the plan (the editor may have restored a take);
        # the tight Shorts pass only adds pause / filler / dead-air trims
        pacing = [c for c in analysis["cuts"] if c["type"] in ("pause", "filler", "dead_air")]
        window_cuts = [dict(c) for c in pacing + plan_cuts
                       if c["end"] > clip["start"] and c["start"] < clip["end"]]
        for k in plan.get("keep_overrides", []):
            window_cuts = plan_mod._subtract(window_cuts, k["start"], k["end"])
        if plan.get("cut_pad"):
            window_cuts = pad_cut_starts(window_cuts, plan["cut_pad"])
        window_cuts += [{"start": 0, "end": clip["start"], "enabled": True},
                        {"start": clip["end"], "end": plan["source"]["duration"], "enabled": True}]
        segs = keep_segments(plan["source"]["duration"], window_cuts, fps=fps)
        tl = Timeline(segs)
        sub = (lambda st, x, k=k: progress(f"short {k + 1}/{len(clips)} {st}", x))
        cuts = {}
        words = tl.map_words(t["words"])
        faces = _faces_on_timeline(faces_src, tl)
        zooms = plan_mod.default_zooms(
            {"sentences": [s for s in analysis["sentences"] if clip["start"] <= s["start"] < clip["end"]]},
            "talking_head", "shorts")
        if pace == "playbook":
            zooms = zooms + _clip_punch_ins(plan, clip, t["words"])
        splan = dict(plan, captions=dict(plan["captions"], **_shorts_caption_style(plan)),
                     zooms=zooms, graphics=_short_graphics(plan, clip))
        for out_name in plan.get("shorts_settings", {}).get("outputs", ["shorts"]):
            out = dict(plan_mod.PLATFORM_OUTPUTS[out_name], name=out_name)
            base = f"short{k + 1:02d}_{_safe(clip['title'])}_{out_name}{'_preview' if quality == 'preview' else ''}"
            out_path = p["exports"] / "shorts" / f"{base}.mp4"
            gfx = render.graphics_for_output(splan, tl, _spec_for(out, quality), p["work"] / "motion",
                                             clip_window=(0, tl.duration))
            src, laid_out = _source_for(plan, out)
            if src not in cuts:
                cuts[src] = render.render_cut(src, segs, p["work"], fps=fps, quality=quality, progress=sub, cancel=cancel)
            cut = cuts[src]
            oplan, ofaces = (_layout_plan(splan, tl), []) if laid_out else (splan, faces)
            info = render.finish(cut, oplan, tl, words, out, out_path, p["work"], quality=quality,
                                 graphics=gfx, faces=ofaces, burn_captions=True, progress=sub, cancel=cancel)
            rep = render.verify(out_path, expect_w=info["width"], expect_h=info["height"], expect_dur=tl.duration)
            rep.update({"clip": clip["id"], "captions": info["captions"]})
            # B4 mouth check only (the listen-back transcription pass is too slow to run per Short)
            rep["mouth_issues"] = qa_mod.mouth_check(
                info.get("out_faces", ofaces), qa_mod.caption_boxes(words, oplan["captions"], info["width"], info["height"]),
                qa_mod.graphic_boxes(gfx, info["width"], info["height"]), info["width"], info["height"],
                _joins(tl), tl.duration) if ofaces else []
            rep["word_issues"] = []
            results.append(rep)
            if clean_copy and quality == "final":
                clean = out_path.with_name(base + "_clean.mp4")
                info2 = render.finish(cut, oplan, tl, words, out, clean, p["work"], quality=quality, graphics=gfx,
                                      faces=ofaces, burn_captions=False, progress=sub, cancel=cancel)
                rep2 = render.verify(clean, expect_w=info2["width"], expect_h=info2["height"], expect_dur=tl.duration)
                rep2["clip"] = clip["id"]
                rep2["mouth_issues"], rep2["word_issues"] = rep["mouth_issues"], []
                results.append(rep2)
    plan = plan_mod.load(p["plan"])
    plan["last_shorts_render"] = {"quality": quality, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    plan_mod.save(plan, p["plan"])
    return results


def _shorts_caption_style(plan: dict) -> dict:
    # an explicit Shorts caption style (e.g. "playbook") overrides the long-form one for Shorts only
    ss = (plan.get("shorts_settings") or {}).get("caption_style")
    if ss and ss in plan_mod.CAPTION_STYLES:
        return dict(plan_mod.CAPTION_STYLES[ss]) | {"style": ss}
    if plan["mode"] == "repurpose" and plan["captions"]["style"] in ("clean", "minimal") and plan["captions"].get("box") != "rounded":
        return {k: v for k, v in plan_mod.CAPTION_STYLES["karaoke"].items() if k != "highlight"} | {"style": "karaoke"}
    return {}


def _clip_punch_ins(plan: dict, clip: dict, words: list[dict]) -> list[dict]:
    """Playbook pace: punch-in zooms for one Short, in the same zoom-dict shape as
    plan_mod.default_zooms (id/start/end/scale/kind/enabled/reason), respecting a
    screen-share layout the way plan_mod._zooms_for_layout does for the other zooms."""
    clip_words = [w for w in words if clip["start"] <= w["start"] < clip["end"]]
    keywords = plan.get("summary", {}).get("keywords")
    punches = an.punch_ins(clip_words, clip["end"] - clip["start"], keywords=keywords)
    zooms = [{"id": f"p{n + 1}", "start": p["start"], "end": p["end"], "scale": p["scale"],
             "kind": p.get("kind", "punch"), "enabled": True, "reason": f'Punch-in on "{p["word"]}"'}
            for n, p in enumerate(punches)]
    return plan_mod._zooms_for_layout(zooms, plan["source"])


def _short_graphics(plan: dict, clip: dict) -> list[dict]:
    g = [x for x in plan.get("graphics", []) if x.get("enabled", True) and clip["start"] <= x["start"] < clip["end"]
         and x["template"] in ("KineticTitle", "EditorialTitle", "Callout", "CallToAction", "StatPanels",
                               "FloatingCards", "EndCard", "File")]
    return g


def _source_for(plan: dict, out: dict) -> tuple[str, bool]:
    """(path, is_layout_master) for an output. Screen + camera projects have a ready-made
    vertical layout, so vertical outputs use it instead of cropping the landscape one."""
    vp = plan["source"].get("vertical_path")
    if vp and out["height"] > out["width"] and Path(vp).exists():
        return vp, True
    return plan["source"]["path"], False


def _layout_plan(plan: dict, tl: Timeline | None = None) -> dict:
    """Captions sit on the seam between screen and camera in the vertical layout, and go back
    to the normal band (below the face) while the camera is full-screen."""
    cap = dict(plan["captions"], position="middle")
    cams = plan["source"].get("cam_ranges") or []
    if tl is not None and cams:
        full = [s for a, b in cams if (s := tl.span_to_edit(a, min(b, plan["source"]["duration"])))]
        split, t = [], 0.0
        for a, b in sorted(full):
            if a > t:
                split.append((t, a))
            t = max(t, b)
        if t < tl.duration:
            split.append((t, tl.duration))
        cap["split_windows"] = split
    return dict(plan, captions=cap)


def _landscape_layout_plan(plan: dict) -> dict:
    """Screen + camera landscape: the camera bubble owns the bottom-right corner, so the logo
    moves to the top-right."""
    if plan["source"].get("layout") != "screencam" or not (plan.get("logo_bug") or {}).get("enabled"):
        return plan
    return dict(plan, logo_bug=dict(plan["logo_bug"], position="top-right"))


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
