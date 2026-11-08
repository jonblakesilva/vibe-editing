"""Rendering: plan -> finished MP4s.

Stage 1 (cut):    every kept section is encoded to its own cached intermediate file
                  (frame-snapped, PCM audio, tiny fades), then joined losslessly. Failed or
                  cancelled renders resume from the sections already done.
Stage 2 (finish): one FFmpeg pass per output: smart crop, zooms, B-roll, motion graphics,
                  burned captions, audio clean-up, loudness normalization, music ducking.
Stage 3 (verify): FFprobe checks plus a full decode, recorded in a JSON report.

The original recording is only ever read."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import captions as cap_mod
from . import config, media, reframe
from .timeline import Timeline

Progress = Callable[[str, float], None]


def _h(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- stage 1

def render_cut(src: str, segments: list[tuple[float, float]], work: Path, *, fps: float,
               quality: str = "final", progress: Progress | None = None,
               cancel: threading.Event | None = None) -> Path:
    info = media.probe(src)
    seg_dir = work / f"segments_{quality}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    total = sum(e - s for s, e in segments) or 1
    done = 0.0
    files = []
    if quality == "preview":
        vf_scale = ",scale=-2:540" if (info.height or 0) > 540 else ""
        venc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
    else:
        vf_scale = ""
        venc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14"]
    src_key = (str(src), info.size_bytes, info.duration)
    for i, (s, e) in enumerate(segments):
        dur = round(e - s, 6)
        out = seg_dir / f"seg_{i:05d}_{_h(src_key, s, e, fps, quality)}.mkv"
        if not out.exists():
            fade = min(0.012, dur / 4)
            tmp = out.with_suffix(".part.mkv")
            args = ["-ss", f"{s:.6f}", "-i", src, "-t", f"{dur:.6f}", "-map", "0:v:0"]
            args += ["-map", "0:a:0"] if info.has_audio else ["-f", "lavfi", "-t", f"{dur:.6f}", "-i",
                                                             "anullsrc=r=48000:cl=stereo", "-map", "1:a"]
            args += ["-vf", f"fps={fps}{vf_scale},format=yuv420p", *venc, "-g", str(int(fps * 2)),
                     "-af", f"aresample=48000,apad=whole_dur={dur:.6f},atrim=0:{dur:.6f},afade=t=in:d={fade:.4f},afade=t=out:st={max(0, dur - fade):.4f}:d={fade:.4f}",
                     "-ac", "2", "-c:a", "pcm_s16le", "-ar", "48000", str(tmp)]
            media.run_ffmpeg(args, duration=dur, cancel=cancel,
                             on_progress=(lambda p, d=done, du=dur: progress("cut", (d + p * du) / total))
                             if progress else None)
            tmp.replace(out)
        done += dur
        files.append(out)
        if progress:
            progress("cut", done / total)
    listing = work / f"concat_{quality}.txt"
    listing.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    joined = work / f"cut_{quality}_{_h([f.name for f in files])}.mkv"
    if not joined.exists():
        tmp = joined.with_suffix(".part.mkv")
        media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(tmp)], cancel=cancel)
        tmp.replace(joined)
    return joined


# ---------------------------------------------------------------- audio

def measure_loudness(path: Path, pre: str, target: float) -> dict | None:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af",
         f"{pre}loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out.stderr, flags=re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    if data.get("input_i") in ("-inf", None):
        return None
    return data


def audio_chain(audio: dict, cut: Path) -> str:
    pre = ""
    if audio.get("clean", True):
        pre += "highpass=f=75,"
        nf = {"off": None, "light": -28, "medium": -22, "strong": -16}.get(audio.get("denoise", "light"))
        if nf is not None:
            pre += f"afftdn=nf={nf}:tn=1,"
    if audio.get("normalize", True):
        target = float(audio.get("target_lufs", -14))
        m = measure_loudness(cut, pre, target)
        if m:
            pre += (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                    f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                    "linear=true,")
        else:
            pre += f"loudnorm=I={target}:TP=-1.5:LRA=11,"
    return pre + "aresample=48000"


# ---------------------------------------------------------------- stage 2

def zoom_expr(zooms: list[dict]) -> str | None:
    terms = []
    for z in zooms:
        a, b, s = z["start"], z["end"], z["scale"] - 1
        if b - a < 0.2 or s <= 0:
            continue
        if z.get("kind") == "ease":
            r = min(0.6, (b - a) / 3)
            terms.append(f"{s:.3f}*clip((it-{a:.3f})/{r:.3f},0,1)*clip(({b:.3f}-it)/{r:.3f},0,1)")
        else:
            terms.append(f"{s:.3f}*between(it,{a:.3f},{b:.3f})")
    if not terms:
        return None
    return "1+" + "+".join(terms)


def zoom_filter(z_expr: str, fx: float, fy: float, fps: float) -> str:
    """Sub-pixel smooth zoom: the perspective filter samples a shrinking window with bicubic
    interpolation every frame, so slow pushes glide instead of stepping whole pixels
    (zoompan rounds its window to integers). The window stays inside the frame."""
    z = f"({z_expr.replace('it', f'(in/{fps})')})"
    left = f"clip({fx:.4f}*W-W/(2*{z}),0,W-W/{z})"
    top = f"clip({fy:.4f}*H-H/(2*{z}),0,H-H/{z})"
    right, bottom = f"({left}+W/{z})", f"({top}+H/{z})"
    return (f"perspective=x0='{left}':y0='{top}':x1='{right}':y1='{top}':x2='{left}':y2='{bottom}':"
            f"x3='{right}':y3='{bottom}':interpolation=cubic:sense=source:eval=frame")


def graphics_for_output(plan: dict, tl: Timeline, out_spec: dict, motion_dir: Path, *,
                        clip_window: tuple[float, float] | None = None) -> list[dict]:
    """Rendered overlay files for this output's resolution, timed on the edited timeline."""
    from . import motion
    items = []
    for g in plan.get("graphics", []):
        if not g.get("enabled", True):
            continue
        start = tl.to_edit_nearest(g["start"])
        if clip_window and not (clip_window[0] <= start < clip_window[1]):
            continue
        path = motion.render_overlay(g, plan, out_spec, motion_dir)
        if path:
            items.append({"path": path, "start": start, "duration": g["duration"], "id": g["id"],
                          "placement": g.get("placement", "overlay")})
    # Cuts can push graphics on top of each other; stagger them so each one reads on its own.
    items.sort(key=lambda g: g["start"])
    for prev, cur in zip(items, items[1:]):
        end = prev["start"] + prev["duration"]
        if cur["start"] < end + 0.3:
            cur["start"] = round(end + 0.3, 3)
    return [g for g in items if g["start"] < tl.duration - 0.5]


def archive_previous(out_path: Path, note: dict | None = None) -> int | None:
    """Keep every earlier render as a numbered version (exports/.../versions/<name>/vN.mp4)
    so reviewers can compare versions, Frame.io style. Returns the archived number."""
    if not out_path.exists():
        return None
    vdir = out_path.parent / "versions" / out_path.stem
    vdir.mkdir(parents=True, exist_ok=True)
    n = len(list(vdir.glob("v*.mp4"))) + 1
    out_path.replace(vdir / f"v{n}.mp4")
    meta = vdir / "versions.json"
    data = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
    data.append({"v": n, "file": f"versions/{out_path.stem}/v{n}.mp4",
                 "archived": time.strftime("%Y-%m-%d %H:%M:%S"), **(note or {})})
    meta.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return n


def finish(cut: Path, plan: dict, tl: Timeline, words: list[dict], out_spec: dict, out_path: Path,
           work: Path, *, quality: str = "final", burn_captions: bool | None = None,
           graphics: list[dict] | None = None, faces: list[dict] | None = None,
           progress: Progress | None = None, cancel: threading.Event | None = None) -> dict:
    info = media.probe(cut)
    W, H = int(out_spec["width"]), int(out_spec["height"])
    if quality == "preview":
        W, H = (W // 2) // 2 * 2, (H // 2) // 2 * 2
    out_aspect = W / H
    src_aspect = info.width / info.height
    fps = plan["source"].get("fps") or info.fps or 30
    inputs = ["-i", str(cut)]
    filters = []
    v = "[0:v]"
    face_sum = reframe.summarize(faces or [])
    mode = (plan.get("reframe") or {}).get("mode", "auto")
    people = reframe.two_people(faces or []) if (mode in ("auto", "split") and out_aspect < 0.8) else None
    # 1) aspect: interview split, smart crop around the speaker, or plain center crop
    if people:
        filters.append(reframe.split_filter(v, people, src_w=info.width, src_h=info.height, out_w=W, out_h=H) + "[vc]")
        v = "[vc]"
        face_sum = None  # captions sit on the seam area below; zooms stay centered
    elif abs(out_aspect - src_aspect) > 0.01:
        if out_aspect < src_aspect:
            crop_w = int(round(info.height * out_aspect / 2) * 2)
            keys = reframe.camera_path(faces if mode != "center" else [], info.duration, src_w=info.width, src_h=info.height,
                                       out_aspect=out_aspect)
            filters.append(f"{v}crop=w={crop_w}:h={info.height}:x='{reframe.crop_x_expr(keys)}':y=0[vc]")
        else:
            crop_h = int(round(info.width / out_aspect / 2) * 2)
            cy = (face_sum["cy"] if face_sum else 0.45) * info.height
            y = max(0, min(info.height - crop_h, int(cy - crop_h / 2)))
            filters.append(f"{v}crop=w={info.width}:h={crop_h}:x=0:y={y}[vc]")
        v = "[vc]"
    filters.append(f"{v}scale={W}:{H}:flags=lanczos,setsar=1[vs]")
    v = "[vs]"
    # 2) zooms (punch-ins / slow pushes), centered on the speaker
    zooms = []
    for z in plan.get("zooms", []):
        if z.get("enabled", True) and tl.to_edit((z["start"] + z["end"]) / 2) is not None:
            span = tl.span_to_edit(z["start"], z["end"])
            if span:
                zooms.append({**z, "start": span[0], "end": span[1]})
    ze = zoom_expr(zooms)
    if ze:
        fx = face_sum["cx"] if (face_sum and abs(out_aspect - src_aspect) <= 0.01) else 0.5
        fy = max(0.3, min(0.6, face_sum["cy"])) if face_sum else 0.42
        filters.append(f"{v}{zoom_filter(ze, fx, fy, fps)}[vz]")
        v = "[vz]"
    # 3) B-roll (video replaces picture, speech continues)
    idx = 1
    for b in plan.get("broll", []):
        if not b.get("enabled", True) or not Path(b["asset"]).exists():
            continue
        st = tl.to_edit_nearest(b["start"])
        d = float(b.get("duration", 3))
        inputs += ["-i", b["asset"]]
        filters.append(f"[{idx}:v]trim=0:{d:.3f},setpts=PTS-STARTPTS+{st:.3f}/TB,scale={W}:{H}:force_original_aspect_ratio=increase,"
                       f"crop={W}:{H},fps={fps}[b{idx}]")
        filters.append(f"{v}[b{idx}]overlay=enable='between(t,{st:.3f},{st + d:.3f})':eof_action=pass[vb{idx}]")
        v = f"[vb{idx}]"
        idx += 1
    # 4) motion graphics overlays (transparent renders). "behind" graphics are composited
    #    after this pass, between the background and the speaker (see mask.py).
    from . import mask as mask_mod
    behind = [g for g in graphics or [] if g.get("placement") == "behind" and mask_mod.available()]
    for g in [g for g in graphics or [] if g not in behind]:
        inputs += ["-i", str(g["path"])]
        st = g["start"]
        filters.append(f"[{idx}:v]setpts=PTS-STARTPTS+{st:.3f}/TB,scale={W}:{H}[g{idx}]")
        filters.append(f"{v}[g{idx}]overlay=enable='between(t,{st:.3f},{st + g['duration']:.3f})':eof_action=pass:format=auto[vg{idx}]")
        v = f"[vg{idx}]"
        idx += 1
    # 5) captions
    cap_info = None
    style = dict(plan["captions"])
    if people and style.get("position", "auto") == "auto":
        style["position"] = "middle"  # on the seam between the two people, never over a face
    do_caps = style.get("enabled", True) if burn_captions is None else burn_captions
    stem = out_path.stem
    if words:
        avoid = [face_sum["box"]] if face_sum and abs(out_aspect - src_aspect) <= 0.01 else None
        if face_sum and out_aspect < src_aspect:
            # after a speaker-centered crop the face sits horizontally centered
            avoid = [{"x": 0.3, "y": face_sum["box"]["y"], "w": 0.4, "h": face_sum["box"]["h"]}]
        cap_info = cap_mod.write_all(words, style, out_path.parent, stem, width=W, height=H, avoid=avoid)
        if do_caps:
            ass_local = work / f"{stem}.ass"
            ass_local.write_text(Path(cap_info["ass"]).read_text(encoding="utf-8"), encoding="utf-8")
            filters.append(f"{v}subtitles=filename='{media.filter_path(ass_local)}':"
                           f"fontsdir='{media.filter_path(config.FONTS_DIR)}'[vcap]")
            v = "[vcap]"
    filters.append(f"{v}format=yuv420p[vout]")
    # audio
    achain = audio_chain(plan.get("audio", {}), cut)
    music = (plan.get("audio") or {}).get("music")
    if music and Path(music.get("path", "")).exists():
        inputs += ["-stream_loop", "-1", "-i", music["path"]]
        vol = float(music.get("volume_db", -22))
        filters.append(f"[0:a]{achain},asplit=2[voice][sc]")
        filters.append(f"[{idx}:a]aresample=48000,volume={vol}dB,atrim=0:{info.duration:.3f}[mus]")
        filters.append("[mus][sc]sidechaincompress=threshold=0.04:ratio=8:attack=25:release=450[duck]")
        filters.append("[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]")
        idx += 1
    else:
        filters.append(f"[0:a]{achain}[aout]")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".part.mp4")
    script = work / f"{stem}.filter.txt"
    script.write_text(";\n".join(filters), encoding="utf-8")
    args = [*inputs, "-filter_complex_script", str(script), "-map", "[vout]", "-map", "[aout]",
            "-r", str(fps), *media.video_encoder(quality), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{info.duration:.3f}", str(tmp)]
    media.run_ffmpeg(args, duration=info.duration, cancel=cancel, env=media.fontconfig_env(),
                     on_progress=(lambda p: progress("finish", p)) if progress else None)
    archive_previous(out_path, {"plan_version": plan.get("version")})
    tmp.replace(out_path)
    notes = []
    if behind:
        if progress:
            progress("subject mask", 0.0)
        mask_mod.composite_behind(out_path, behind, work, fps=fps, cancel=cancel, notes=notes)
        if progress:
            progress("subject mask", 1.0)
    elif any(g.get("placement") == "behind" for g in graphics or []):
        notes.append("Subject masking unavailable (mediapipe not installed): 'behind' graphics were placed in front.")
    if people:
        notes.append("Two people detected: vertical version uses a stacked interview layout.")
    return {"captions": cap_info, "width": W, "height": H, "notes": notes, "behind": len(behind)}


# ---------------------------------------------------------------- stage 3

def verify(path: Path, *, expect_w: int, expect_h: int, expect_dur: float | None = None,
           full_decode: bool = True) -> dict:
    """FFprobe + decode checks. 'ok' is only True if every check passes."""
    info = media.probe(path)
    checks = {
        "has_video": info.has_video, "has_audio": info.has_audio,
        "codec_h264": info.vcodec == "h264", "codec_aac": info.acodec == "aac",
        "resolution": (info.width, info.height) == (expect_w, expect_h),
    }
    sd = media.stream_durations(path)
    vd, ad = sd.get("video", info.duration), sd.get("audio", 0.0)
    checks["av_sync_drift_ok"] = abs(vd - ad) <= 0.05
    if expect_dur is not None:
        checks["duration_ok"] = abs(info.duration - expect_dur) <= max(0.25, expect_dur * 0.005)
    if full_decode:
        dec = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        checks["decodes_cleanly"] = dec.returncode == 0 and not dec.stderr.strip()
    return {"path": str(path), "ok": all(checks.values()), "checks": checks,
            "video_duration": round(vd, 3), "audio_duration": round(ad, 3),
            "width": info.width, "height": info.height, "size_mb": round(info.size_bytes / 1e6, 2)}
