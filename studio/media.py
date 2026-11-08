"""FFmpeg / FFprobe helpers.

Everything streams through FFmpeg processes, so long recordings are never loaded
into Python memory. Long-running commands report real progress (parsed from
FFmpeg's -progress output) and can be cancelled."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config


class MediaError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise MediaError(f"{tool} is not installed or not on PATH. Run: python -m studio doctor")
    return path


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    has_video: bool
    vcodec: str | None
    acodec: str | None
    sample_rate: int | None
    size_bytes: int
    rotation: int = 0

    @property
    def aspect(self) -> float | None:
        if self.width and self.height:
            return self.width / self.height
        return None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    if "/" in rate:
        n, d = rate.split("/")
        return float(n) / float(d) if float(d) else None
    return float(rate)


def probe(path: str | Path) -> MediaInfo:
    require("ffprobe")
    path = str(path)
    if not Path(path).is_file():
        raise MediaError(f"File not found: {path}")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe could not read {path}: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (v or a or {}).get("duration") or 0)
    rotation = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(sd["rotation"])
        rotation = int(v.get("tags", {}).get("rotate", rotation))
    w, h = (v.get("width"), v.get("height")) if v else (None, None)
    if rotation in (90, -90, 270, -270) and w and h:
        w, h = h, w
    return MediaInfo(
        path=path, duration=duration, width=w, height=h,
        fps=_fps(v.get("avg_frame_rate") or v.get("r_frame_rate")) if v else None,
        has_audio=a is not None, has_video=v is not None,
        vcodec=v.get("codec_name") if v else None, acodec=a.get("codec_name") if a else None,
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        size_bytes=int(fmt.get("size") or Path(path).stat().st_size), rotation=rotation,
    )


def stream_durations(path: str | Path) -> dict:
    """Per-stream durations in seconds ({'video': x, 'audio': y}); reads MKV DURATION tags too."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,duration:stream_tags=DURATION", "-of", "json", str(path)],
                         capture_output=True, text=True)
    res = {}
    for st in json.loads(out.stdout or "{}").get("streams", []):
        d = st.get("duration")
        if d in (None, "N/A"):
            tag = (st.get("tags") or {}).get("DURATION")
            if tag:
                h, m, sec = tag.split(":")
                d = int(h) * 3600 + int(m) * 60 + float(sec)
        if d not in (None, "N/A") and st.get("codec_type") not in res:
            res[st["codec_type"]] = float(d)
    return res


def run_ffmpeg(args: list[str], *, duration: float | None = None,
               on_progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None, cwd: str | None = None,
               env: dict | None = None) -> None:
    """Run ffmpeg with real progress reporting (0..1) and cooperative cancellation."""
    require("ffmpeg")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc_env = {**os.environ, **(env or {})}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=cwd, env=proc_env)
    stderr_tail: list[str] = []

    def drain_err():
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_tail.append(line)
            if len(stderr_tail) > 60:
                del stderr_tail[:20]

    t = threading.Thread(target=drain_err, daemon=True)
    t.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled("Cancelled by user")
            if on_progress and duration and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(max(0.0, min(1.0, us / 1e6 / duration)))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    t.join(timeout=2)
    if cancel is not None and cancel.is_set():
        raise Cancelled("Cancelled by user")
    if proc.returncode != 0:
        tail = config.redact("".join(stderr_tail[-25:]))
        raise MediaError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    if on_progress:
        on_progress(1.0)


def extract_audio(src: str | Path, dst: str | Path, *, rate: int = 16000, **kw) -> Path:
    """Mono 16 kHz WAV for speech recognition (streamed by ffmpeg)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    if not info.has_audio:
        raise MediaError(f"{src} has no audio track to transcribe.")
    run_ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)],
               duration=info.duration, **kw)
    return dst


def detect_silences(src: str | Path, *, noise_db: float = -35, min_dur: float = 0.6) -> list[tuple[float, float]]:
    """Silence intervals via ffmpeg silencedetect (streamed, no decoding in Python)."""
    require("ffmpeg")
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(src), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    spans, start = [], None
    for line in out.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and start is not None:
            end = float(line.split("silence_end:")[1].split("|")[0].strip())
            spans.append((max(0.0, start), end))
            start = None
    return spans


_FONTCONF = None


def fontconfig_env() -> dict:
    """libass on Windows needs a fontconfig file; point it at the bundled fonts
    plus brand fonts so captions render with the right typeface."""
    global _FONTCONF
    if _FONTCONF is None:
        cache = config.DATA_HOME / "cache" / "fontconfig"
        cache.mkdir(parents=True, exist_ok=True)
        conf = cache / "fonts.conf"
        dirs = [config.FONTS_DIR, config.FONTS_DIR / "free_font", config.BRANDS_DIR]
        if os.name == "nt":
            dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        body = "".join(f"<dir>{d.as_posix()}</dir>" for d in dirs if d.exists())
        conf.write_text(
            f'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>{body}'
            f"<cachedir>{cache.as_posix()}</cachedir></fontconfig>", encoding="utf-8")
        _FONTCONF = str(conf)
    return {"FONTCONFIG_FILE": _FONTCONF}


def filter_path(p: str | Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument (Windows drive colons)."""
    s = Path(p).as_posix()
    return s.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


_ENCODER = None


def video_encoder(quality: str = "final") -> list[str]:
    """libx264 gives the most predictable quality and frame accuracy; previews use a
    fast preset. Hardware encoders are opt-in via VIBE_HW_ENCODER (e.g. h264_amf)."""
    hw = os.environ.get("VIBE_HW_ENCODER")
    if hw and quality == "preview":
        return ["-c:v", hw, "-b:v", "4M"]
    if quality == "preview":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]
