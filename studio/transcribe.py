"""Word-level transcription.

Engines:
  local  faster-whisper on this computer (free, offline; default)
  groq   Groq's hosted Whisper (optional, needs GROQ_API_KEY; faster on slow PCs)

Output is a normalized transcript dict cached next to the project, so re-running a
plan or revision never re-transcribes."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Callable

from . import config, media

DEFAULT_MODEL = os.environ.get("VIBE_WHISPER_MODEL", "small")


class TranscriptionError(RuntimeError):
    pass


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def normalize(segments: list[dict], *, language: str, duration: float, engine: str, model: str) -> dict:
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            text = w["word"].strip()
            if not text:
                continue
            words.append({"word": text, "start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3), "prob": round(float(w.get("prob", 1.0)), 3)})
    # Guarantee monotonic, non-overlapping word times (some engines overlap by a few ms).
    for i in range(1, len(words)):
        if words[i]["start"] < words[i - 1]["end"]:
            words[i]["start"] = words[i - 1]["end"]
        if words[i]["end"] < words[i]["start"]:
            words[i]["end"] = words[i]["start"]
    return {
        "schema": "vibe-studio.transcript/v1", "engine": engine, "model": model,
        "language": language, "duration": round(duration, 3),
        "segments": [{"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"].strip()}
                     for s in segments],
        "words": words,
    }


def transcribe_local(wav: Path, *, model: str = DEFAULT_MODEL, language: str | None = None,
                     vocabulary: list[str] | None = None, on_progress: Callable[[float], None] | None = None,
                     cancel: threading.Event | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscriptionError("faster-whisper is not installed. Run: python -m studio doctor --fix") from e
    duration = media.probe(wav).duration
    device = os.environ.get("VIBE_WHISPER_DEVICE", "auto")
    compute = os.environ.get("VIBE_WHISPER_COMPUTE", "int8")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    wm = WhisperModel(model, device=device, compute_type=compute)
    # Feed the 16 kHz mono WAV ffmpeg already produced (about 115 MB per hour as float32)
    # instead of letting faster-whisper decode media through PyAV, whose API drifts between versions.
    import soundfile as sf
    audio, rate = sf.read(str(wav), dtype="float32")
    if rate != 16000:
        raise TranscriptionError(f"Expected 16 kHz audio, got {rate} Hz")
    seg_iter, info = wm.transcribe(audio, language=language, word_timestamps=True,
                                   vad_filter=True, beam_size=5,
                                   # Keep disfluencies ("um", restarts) so the editor can find them.
                                   initial_prompt="Um, uh, so, like, you know. I mean, let me start again. "
                                   + ", ".join(vocabulary or []),
                                   condition_on_previous_text=False)
    segments = []
    for seg in seg_iter:  # generator: audio is decoded incrementally, never all at once
        if cancel is not None and cancel.is_set():
            raise media.Cancelled("Cancelled by user")
        segments.append({"start": seg.start, "end": seg.end, "text": seg.text,
                         "words": [{"word": w.word, "start": w.start, "end": w.end, "prob": w.probability}
                                   for w in (seg.words or [])]})
        if on_progress and duration:
            on_progress(min(1.0, seg.end / duration))
    return normalize(segments, language=info.language, duration=duration, engine="faster-whisper", model=model)


def transcribe_groq(wav: Path, *, language: str | None = None,
                    on_progress: Callable[[float], None] | None = None, **_) -> dict:
    config.load_keys()
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise TranscriptionError("GROQ_API_KEY is not set. Save it privately with: python -m studio keys set GROQ_API_KEY")
    import requests
    # Compress to a small mono MP3 so long recordings fit Groq's upload limit.
    mp3 = wav.with_suffix(".groq.mp3")
    media.run_ffmpeg(["-i", str(wav), "-ac", "1", "-ar", "16000", "-b:a", "32k", str(mp3)])
    if mp3.stat().st_size > 24 * 1024 * 1024:
        raise TranscriptionError("Recording is too long for a single Groq upload; use the local engine.")
    with open(mp3, "rb") as f:
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (mp3.name, f, "audio/mpeg")},
            data={"model": "whisper-large-v3", "response_format": "verbose_json",
                  "timestamp_granularities[]": ["word", "segment"],
                  **({"language": language} if language else {})},
            timeout=600,
        )
    mp3.unlink(missing_ok=True)
    if resp.status_code != 200:
        raise TranscriptionError(f"Groq transcription failed: HTTP {resp.status_code} {config.redact(resp.text[:200])}")
    data = resp.json()
    words = data.get("words", [])
    segments = []
    for s in data.get("segments", []):
        segments.append({"start": s["start"], "end": s["end"], "text": s["text"],
                         "words": [{"word": w["word"], "start": w["start"], "end": w["end"]}
                                   for w in words if s["start"] - 0.01 <= w["start"] < s["end"]]})
    if on_progress:
        on_progress(1.0)
    return normalize(segments, language=data.get("language", language or "en"),
                     duration=float(data.get("duration") or 0), engine="groq", model="whisper-large-v3")


def transcribe(src: Path, work_dir: Path, *, engine: str = "local", model: str = DEFAULT_MODEL,
               language: str | None = None, vocabulary: list[str] | None = None, on_progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None, force: bool = False) -> dict:
    """Extract audio, transcribe it, and cache the result in work_dir/transcript.json."""
    work_dir.mkdir(parents=True, exist_ok=True)
    wav = work_dir / "audio16k.wav"
    if force or not wav.exists():
        media.extract_audio(src, wav, on_progress=(lambda p: on_progress(p * 0.1)) if on_progress else None,
                            cancel=cancel)
    key = f"{_hash_file(wav)}-{engine}-{model}-{language or 'auto'}"
    cache = work_dir / "transcript.json"
    if cache.exists() and not force:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("cache_key") == key:
            if on_progress:
                on_progress(1.0)
            return cached
    sub = (lambda p: on_progress(0.1 + 0.9 * p)) if on_progress else None
    if engine == "groq":
        result = transcribe_groq(wav, language=language, on_progress=sub)
    elif engine == "local":
        result = transcribe_local(wav, model=model, language=language, vocabulary=vocabulary,
                                  on_progress=sub, cancel=cancel)
    else:
        raise TranscriptionError(f"Unknown transcription engine: {engine}")
    if not result["words"]:
        raise TranscriptionError("No speech was detected in this recording.")
    result["cache_key"] = key
    result["source"] = str(src)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=1), encoding="utf-8")
    tmp.replace(cache)
    return result


def apply_vocabulary(transcript: dict, vocabulary: list[str], threshold: float = 0.8) -> list[dict]:
    """Fix the spelling of brand names / jargon ("book Solid" -> "Booked Solid").
    Only word text changes; timing and word count stay the same. Returns the fixes."""
    from difflib import SequenceMatcher
    import re
    words = transcript["words"]
    fixes = []
    strip = lambda w: re.sub(r"[^\w']", "", w.lower())
    for phrase in vocabulary or []:
        target = phrase.split()
        n = len(target)
        tl = [t.lower() for t in target]
        for i in range(len(words) - n + 1):
            window = [strip(w["word"]) for w in words[i:i + n]]
            if window == tl and [w["word"].strip(",.?!") for w in words[i:i + n]] == target:
                continue
            ratio = SequenceMatcher(None, " ".join(window), " ".join(tl)).ratio()
            if ratio >= threshold:
                before = " ".join(w["word"] for w in words[i:i + n])
                for k, w in enumerate(words[i:i + n]):
                    trail = re.search(r"[,.?!]*$", w["word"]).group(0)
                    w["word"] = target[k] + trail
                    w["corrected"] = True
                fixes.append({"index": i, "before": before, "after": phrase})
    return fixes


def apply_corrections(transcript: dict, corrections: dict[int, str]) -> dict:
    """Manual word fixes ({word_index: new_text}) without changing any timing."""
    for idx, text in corrections.items():
        idx = int(idx)
        if 0 <= idx < len(transcript["words"]):
            transcript["words"][idx]["word"] = text
            transcript["words"][idx]["corrected"] = True
    return transcript
