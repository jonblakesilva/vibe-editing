"""Toolchain checker. A feature is only READY after it passes a real test:
an actual transcription, an actual render, an actual Remotion render."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config

READY, MISSING, FAILED, SKIPPED, OPTIONAL = "READY", "MISSING", "FAILED", "NOT TESTED", "OPTIONAL (not installed)"


def _ver(cmd: list[str], pattern: str = r"(\d+\.\d+(?:\.\d+)?)") -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
        m = re.search(pattern, out.stdout + out.stderr)
        return m.group(1) if m else (out.stdout.strip().splitlines() or ["?"])[0]
    except (OSError, subprocess.TimeoutExpired):
        return None


def _pyver(mod: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(mod)
    except Exception:
        return None


def install_hint(tool: str) -> str:
    system = platform.system()
    winget = {"ffmpeg": "Gyan.FFmpeg", "node": "OpenJS.NodeJS.LTS", "git": "Git.Git",
              "tesseract": "UB-Mannheim.TesseractOCR", "rclone": "Rclone.Rclone"}
    if system == "Windows" and tool in winget:
        return f"winget install --id {winget[tool]} -e"
    if system == "Darwin":
        return f"brew install {'node' if tool == 'node' else tool}"
    return f"sudo apt install {tool}"


def gpu_info() -> dict:
    names = []
    if platform.system() == "Windows":
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True)
        names = [n.strip() for n in out.stdout.splitlines() if n.strip()]
    elif shutil.which("nvidia-smi"):
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True)
        names = [n.strip() for n in out.stdout.splitlines() if n.strip()]
    cuda = False
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    working = []
    if shutil.which("ffmpeg"):
        for enc in ("h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                                "testsrc2=s=640x360:d=1:r=30", "-c:v", enc, "-f", "null", "-"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                working.append(enc)
    return {"gpus": names, "cuda_for_transcription": cuda, "working_hw_encoders": working,
            "note": ("Transcription runs on the CPU (no NVIDIA CUDA GPU). " if not cuda else "") +
                    (f"Hardware encoding available: {', '.join(working)} (opt-in via VIBE_HW_ENCODER)." if working
                     else "No working hardware encoder; libx264 software encoding is used.")}


def _speech_wav(path: Path, text: str) -> bool:
    """Make a spoken test clip with the OS speech engine (Windows/macOS)."""
    if platform.system() == "Windows":
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
        return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True).returncode == 0
    if platform.system() == "Darwin" and shutil.which("say"):
        aiff = path.with_suffix(".aiff")
        ok = subprocess.run(["say", "-o", str(aiff), text]).returncode == 0
        return ok and subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), str(path)]).returncode == 0
    if shutil.which("espeak-ng"):
        return subprocess.run(["espeak-ng", "-w", str(path), text]).returncode == 0
    return False


def test_transcription(tmp: Path) -> tuple[str, str]:
    wav = tmp / "speech.wav"
    phrase = "Testing the booked solid system, one two three."
    if not _speech_wav(wav, phrase):
        return SKIPPED, "No text-to-speech engine to make a test clip"
    from . import transcribe
    try:
        t0 = time.time()
        t = transcribe.transcribe(wav, tmp / "tx", model=os.environ.get("VIBE_WHISPER_MODEL", "small"))
        text = " ".join(w["word"] for w in t["words"]).lower()
        ok = "testing" in text and ("three" in text or "3" in text)
        return (READY if ok else FAILED), f'heard "{text}" in {time.time() - t0:.1f}s with word timestamps'
    except Exception as e:
        return FAILED, f"{type(e).__name__}: {e}"


def test_render(tmp: Path) -> tuple[str, str]:
    from . import media, render
    from .timeline import Timeline
    src = tmp / "src.mp4"
    media.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=4", "-f", "lavfi", "-i",
                      "sine=f=440:d=4:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                      "-c:a", "aac", "-shortest", str(src)])
    segs = [(0.0, 1.5), (2.0, 3.5)]
    tl = Timeline(segs)
    cut = render.render_cut(str(src), segs, tmp, fps=30, quality="preview")
    plan = {"source": {"fps": 30, "duration": 4}, "zooms": [{"start": 0.2, "end": 1.2, "scale": 1.2, "enabled": True}],
            "graphics": [], "broll": [],
            "captions": {"enabled": True, "style": "clean", "font": "Montserrat ExtraBold", "size": 64,
                         "primary": "#FFFFFF", "outline": 4, "shadow": 2, "max_words": 4, "lines": 1},
            "audio": {"clean": True, "denoise": "light", "normalize": True, "target_lufs": -14}}
    words = [{"word": "Doctor", "start": 0.1, "end": 0.6}, {"word": "test.", "start": 0.7, "end": 1.2},
             {"word": "Rendering", "start": 1.6, "end": 2.2}, {"word": "works.", "start": 2.3, "end": 2.9}]
    results = []
    for name, w, h in (("h", 1920, 1080), ("v", 1080, 1920)):
        out = tmp / f"out_{name}.mp4"
        render.finish(cut, plan, tl, words, {"width": w, "height": h}, out, tmp, quality="final")
        results.append(render.verify(out, expect_w=w, expect_h=h, expect_dur=3.0))
    bad = [f"{Path(r['path']).name}: {[k for k, v in r['checks'].items() if not v]}" for r in results if not r["ok"]]
    return (READY, "cut + zoom + captions + loudness -> 16:9 and 9:16, verified with ffprobe and a full decode") \
        if not bad else (FAILED, "; ".join(bad))


def test_motion(tmp: Path) -> tuple[str, str]:
    from . import motion
    if not motion.available():
        return MISSING, f"Remotion not installed: cd {motion.REMOTION_DIR} && npm install"
    g = {"id": "t", "template": "KineticTitle", "start": 0, "duration": 0.5, "props": {"text": "DOCTOR TEST"}}
    plan = {"brand": "default", "source": {"fps": 30}}
    try:
        out = motion.render_overlay(g, plan, {"width": 640, "height": 360}, tmp / "motion")
        from . import media
        pix = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True).stdout.strip()
        info = media.probe(out)
        ok = "yuva" in pix and info.width == 640
        return (READY if ok else FAILED), f"rendered transparent overlay ({pix}, {info.width}x{info.height})"
    except Exception as e:
        return FAILED, str(e)[-400:]


def run(fix: bool = False, quick: bool = False) -> dict:
    config.load_keys()
    if fix:
        req = config.STUDIO / "requirements.txt"
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
    tools = {}
    ff = shutil.which("ffmpeg")
    libass = False
    if ff:
        libass = "subtitles" in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    tools["ffmpeg"] = {"version": _ver(["ffmpeg", "-version"], r"ffmpeg version (\S+)") if ff else None,
                       "status": READY if ff and libass else (FAILED if ff else MISSING),
                       "note": "libass captions OK" if libass else ("ffmpeg lacks libass (captions)" if ff else install_hint("ffmpeg"))}
    fp = shutil.which("ffprobe")
    tools["ffprobe"] = {"version": _ver(["ffprobe", "-version"], r"ffprobe version (\S+)") if fp else None,
                        "status": READY if fp else MISSING}
    tools["python"] = {"version": platform.python_version(), "status": READY,
                       "note": f"{'project venv' if '.venv' in sys.executable else 'NOT the project venv'}: {sys.executable}"}
    for t in ("node", "npm", "git"):
        p = shutil.which(t)
        tools[t] = {"version": _ver([p, "--version"]) if p else None, "status": READY if p else MISSING,
                    **({} if p else {"note": install_hint("node" if t == "npm" else t)})}
    for mod, imp in (("faster-whisper", "faster_whisper"), ("opencv-python", "cv2"), ("numpy", "numpy"),
                     ("Pillow", "PIL"), ("soundfile", "soundfile"), ("yt-dlp", "yt_dlp"), ("fastapi", "fastapi"),
                     ("uvicorn", "uvicorn"), ("requests", "requests")):
        v = _pyver(mod)
        tools[mod] = {"version": v, "status": READY if v else MISSING}
    for t in ("tesseract", "rclone"):
        p = shutil.which(t)
        tools[t] = {"version": _ver([t, "--version"]) if p else None, "status": READY if p else OPTIONAL,
                    **({} if p else {"note": install_hint(t)})}
    tools["yunet face model"] = {"status": READY if config.YUNET_MODEL.exists() else MISSING}
    hf = shutil.which("hyperframes")
    tools["hyperframes"] = {"version": _ver(["hyperframes", "--version"]) if hf else None,
                            "status": READY if hf else OPTIONAL,
                            "note": "optional second motion engine (Apache-2.0); see docs/STUDIO_MOTION.md"}
    features = {}
    with tempfile.TemporaryDirectory(prefix="vibe-doctor-") as td:
        tmp = Path(td)
        core_tools = all(tools[k]["status"] == READY for k in ("ffmpeg", "ffprobe", "faster-whisper", "numpy", "soundfile"))
        if quick:
            features = {k: {"status": SKIPPED, "detail": "run without --quick for real tests"}
                        for k in ("transcription", "rendering", "motion_graphics")}
        else:
            for name, fn in (("transcription", test_transcription), ("rendering", test_render), ("motion_graphics", test_motion)):
                if not core_tools and name != "motion_graphics":
                    features[name] = {"status": MISSING, "detail": "core tools missing"}
                    continue
                try:
                    st, detail = fn(tmp)
                except Exception as e:
                    st, detail = FAILED, f"{type(e).__name__}: {e}"
                features[name] = {"status": st, "detail": detail}
    features["groq_transcription"] = {"status": "KEY SAVED" if config.has_key("GROQ_API_KEY") else "OPTIONAL (no key)",
                                      "detail": "key saved (not called during checks)" if config.has_key("GROQ_API_KEY")
                                      else "optional: python -m studio keys set GROQ_API_KEY"}
    features["tella"] = {"status": "VIA CLAUDE CODE",
                         "detail": "Tella exports import from any folder; the Tella connector in Claude Code can fetch recordings"}
    gpu = gpu_info()
    ready = {
        "core": all(features.get(k, {}).get("status") in (READY, SKIPPED) for k in ("transcription", "rendering")),
        "motion_graphics": features.get("motion_graphics", {}).get("status") == READY,
    }
    return {"system": f"{platform.system()} {platform.release()} ({platform.machine()})", "tools": tools,
            "gpu": gpu, "features": features, "ready": ready, "data_home": str(config.DATA_HOME)}


def print_report(r: dict) -> None:
    print(f"\n  Vibe Studio doctor - {r['system']}\n  " + "-" * 60)
    for name, t in r["tools"].items():
        print(f"  {name:<20} {t['status']:<24} {t.get('version') or '':<14} {t.get('note', '')}")
    print("  " + "-" * 60)
    print(f"  GPU: {', '.join(r['gpu']['gpus']) or 'none detected'}")
    print(f"       {r['gpu']['note']}")
    print("  " + "-" * 60)
    for name, f in r["features"].items():
        print(f"  {name:<20} {f['status']:<24} {f['detail']}")
    print("  " + "-" * 60)
    print(f"  Core editing: {'READY' if r['ready']['core'] else 'NOT READY'}   "
          f"Motion graphics: {'READY' if r['ready']['motion_graphics'] else 'NOT READY'}")
    print(f"  Projects and brands live in {r['data_home']}\n")


if __name__ == "__main__":
    rep = run(quick="--quick" in sys.argv)
    print(json.dumps(rep, indent=2)) if "--json" in sys.argv else print_report(rep)
