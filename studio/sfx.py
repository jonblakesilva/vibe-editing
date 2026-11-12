"""Synthesized sound-effect palette: no licensed SFX files exist, so a small, tasteful set
is generated deterministically instead (Nate Herk's playbook -- soft, premium hits, never
sci-fi). Five categories, 4 variants each, written as 48 kHz stereo 16-bit WAVs plus a
manifest.json that render.py's `_library("sfx")` reads.

Nothing here is random across runs: every variant is seeded from its own name, so the same
bytes come out every time `generate()` is asked to rebuild a file."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import config

SAMPLE_RATE = 48000
PEAK_DBFS = -6.0  # target peak after normalization
EDGE_FADE_MS = 3.0  # short fade at both ends so no file clicks on cut-in/cut-out

# Slightly different pitch, length and filter per variant -- never identical copies.
_WHOOSH_VARIANTS = [
    dict(f0=300, f1=1150, dur=0.33, q=1.6),
    dict(f0=330, f1=1200, dur=0.35, q=1.4),
    dict(f0=280, f1=1100, dur=0.37, q=1.8),
    dict(f0=320, f1=1250, dur=0.34, q=1.5),
]
_TAP_VARIANTS = [
    dict(f0=175, dur=0.110, decay=0.045, harm=0.28),
    dict(f0=180, dur=0.120, decay=0.050, harm=0.30),
    dict(f0=185, dur=0.115, decay=0.047, harm=0.26),
    dict(f0=190, dur=0.125, decay=0.052, harm=0.32),
]
_CLICK_VARIANTS = [
    dict(dur=0.008, hp=3200, tone=2200),
    dict(dur=0.010, hp=3600, tone=2500),
    dict(dur=0.012, hp=4000, tone=2800),
    dict(dur=0.015, hp=3800, tone=2400),
]
_PAPER_VARIANTS = [
    dict(dur=0.140, hp=900, density=180),
    dict(dur=0.150, hp=1000, density=200),
    dict(dur=0.155, hp=850, density=160),
    dict(dur=0.160, hp=1050, density=220),
]
# Warm two-note "check" dings, each well inside the 250 ms ceiling.
_CHECK_VARIANTS = [
    dict(n1=523.25, n2=659.25, note_dur=0.085, gap=0.020),  # C5 -> E5
    dict(n1=587.33, n2=698.46, note_dur=0.080, gap=0.018),  # D5 -> F5
    dict(n1=493.88, n2=622.25, note_dur=0.090, gap=0.022),  # B4 -> D#5
    dict(n1=523.25, n2=698.46, note_dur=0.080, gap=0.020),  # C5 -> F5
]

_VARIANTS = {"whoosh": _WHOOSH_VARIANTS, "tap": _TAP_VARIANTS, "click": _CLICK_VARIANTS,
             "paper": _PAPER_VARIANTS, "check": _CHECK_VARIANTS}
CATEGORIES = tuple(_VARIANTS)


# ---------------------------------------------------------------- tiny DSP helpers

def _seed(category: str, variant: int) -> int:
    return int(hashlib.sha256(f"sfx:{category}:{variant}".encode()).hexdigest()[:8], 16)


def _bandpass_coeffs(freq: float, q: float, fs: int) -> tuple[float, float, float, float, float]:
    """RBJ cookbook constant-skirt-gain bandpass biquad."""
    w0 = 2 * np.pi * freq / fs
    alpha = np.sin(w0) / (2 * q)
    a0 = 1 + alpha
    return alpha / a0, 0.0, -alpha / a0, (-2 * np.cos(w0)) / a0, (1 - alpha) / a0


def _apply_bandpass_sweep(x: np.ndarray, freqs: np.ndarray, q: float, fs: int, block: int = 64) -> np.ndarray:
    """Time-varying bandpass: coefficients are refreshed every `block` samples as the centre
    frequency sweeps, with the biquad's recursive state carried across blocks."""
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    n = len(x)
    i = 0
    while i < n:
        j = min(i + block, n)
        b0, b1, b2, a1, a2 = _bandpass_coeffs(float(freqs[i:j].mean()), q, fs)
        for k in range(i, j):
            xn = x[k]
            yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, xn
            y2, y1 = y1, yn
            y[k] = yn
        i = j
    return y


def _apply_highpass(x: np.ndarray, fc: float, fs: int) -> np.ndarray:
    """Simple one-pole RC highpass (no scipy dependency needed for a few hundred samples)."""
    rc = 1.0 / (2 * np.pi * fc)
    dt = 1.0 / fs
    alpha = rc / (rc + dt)
    y = np.zeros_like(x)
    y_prev = 0.0
    x_prev = x[0] if len(x) else 0.0
    for i, xn in enumerate(x):
        yn = alpha * (y_prev + xn - x_prev)
        y[i] = yn
        y_prev, x_prev = yn, xn
    return y


def _hann(n: int) -> np.ndarray:
    return 0.5 * (1 - np.cos(2 * np.pi * np.arange(n) / max(n, 1)))


def _edge_fade(y: np.ndarray, fs: int, ms: float = EDGE_FADE_MS) -> np.ndarray:
    n = len(y)
    k = max(1, int(fs * ms / 1000))
    k = min(k, n // 2) if n > 1 else 0
    if k <= 0:
        return y
    y = y.copy()
    fade = 0.5 * (1 - np.cos(np.linspace(0, np.pi, k)))
    y[:k] *= fade
    y[-k:] *= fade[::-1]
    return y


def _peak_normalize(y: np.ndarray, target_dbfs: float = PEAK_DBFS) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak <= 0:
        return y
    return y * (10 ** (target_dbfs / 20) / peak)


# ---------------------------------------------------------------- category synthesis

def _whoosh(rng: np.random.Generator, dur: float, fs: int, f0: float, f1: float, q: float) -> np.ndarray:
    """Soft air whoosh: band-passed noise, the centre sweeping f0 -> f1, raised-cosine envelope."""
    n = int(dur * fs)
    noise = rng.standard_normal(n)
    freqs = np.linspace(f0, f1, n)
    y = _apply_bandpass_sweep(noise, freqs, q, fs)
    return y * _hann(n)


def _tap(rng: np.random.Generator, dur: float, fs: int, f0: float, decay: float, harm: float) -> np.ndarray:
    """Damped logo-landing tap: fundamental sine + soft 2nd harmonic, fast attack, quick decay."""
    n = int(dur * fs)
    t = np.arange(n) / fs
    attack = 0.003
    env = np.minimum(t / attack, 1.0) * np.exp(-t / decay)
    y = np.sin(2 * np.pi * f0 * t) + harm * np.sin(2 * np.pi * 2 * f0 * t)
    jitter = 1.0 + 0.01 * rng.standard_normal()  # tiny deterministic per-variant detune
    return y * env * jitter


def _click(rng: np.random.Generator, dur: float, fs: int, hp: float, tone: float) -> np.ndarray:
    """Dry UI click: a short high-passed noise burst with a touch of tonal body."""
    n = int(dur * fs)
    t = np.arange(n) / fs
    noise = _apply_highpass(rng.standard_normal(n), hp, fs)
    body = np.sin(2 * np.pi * tone * t) * np.exp(-t / (dur * 0.3 + 1e-6))
    env = np.exp(-t / (dur * 0.35 + 1e-6))
    return (noise * 0.85 + body * 0.30) * env


def _paper(rng: np.random.Generator, dur: float, fs: int, hp: float, density: float) -> np.ndarray:
    """Paper rustle: crackly filtered noise -- a highpassed bed plus sparse filtered crackle hits."""
    n = int(dur * fs)
    bed = _apply_highpass(rng.standard_normal(n), hp, fs)
    n_crackles = max(1, int(dur * density))
    idx = rng.integers(0, n, size=n_crackles)
    amp = rng.uniform(0.3, 1.0, size=n_crackles)
    crackle = np.zeros(n)
    crackle[idx] += amp
    crackle = _apply_highpass(crackle, hp * 1.5, fs)
    return (bed * 0.5 + crackle * 0.6) * _hann(n)


def _check(rng: np.random.Generator, n1: float, n2: float, fs: int, note_dur: float, gap: float) -> np.ndarray:
    """Warm two-note "check" ding, each note a soft sine with a faint 2nd harmonic for warmth."""
    def note(freq: float) -> np.ndarray:
        n = int(note_dur * fs)
        t = np.arange(n) / fs
        detune = 1.0 + 0.002 * rng.standard_normal()
        y = np.sin(2 * np.pi * freq * detune * t) + 0.15 * np.sin(2 * np.pi * 2 * freq * detune * t)
        return y * _hann(n)

    silence = np.zeros(int(gap * fs))
    return np.concatenate([note(n1), silence, note(n2)])


def _synthesize(category: str, variant: int, fs: int = SAMPLE_RATE) -> np.ndarray:
    rng = np.random.default_rng(_seed(category, variant))
    p = _VARIANTS[category][variant]
    if category == "whoosh":
        y = _whoosh(rng, p["dur"], fs, p["f0"], p["f1"], p["q"])
    elif category == "tap":
        y = _tap(rng, p["dur"], fs, p["f0"], p["decay"], p["harm"])
    elif category == "click":
        y = _click(rng, p["dur"], fs, p["hp"], p["tone"])
    elif category == "paper":
        y = _paper(rng, p["dur"], fs, p["hp"], p["density"])
    elif category == "check":
        y = _check(rng, p["n1"], p["n2"], fs, p["note_dur"], p["gap"])
    else:
        raise ValueError(f"unknown sfx category: {category}")
    y = _edge_fade(y, fs)
    return _peak_normalize(y)


def _write_wav(path: Path, mono: np.ndarray, fs: int = SAMPLE_RATE) -> None:
    mono = np.clip(mono, -1.0, 1.0)
    pcm = (mono * 32767.0).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1).reshape(-1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(fs)
        wf.writeframes(stereo.tobytes())


# ---------------------------------------------------------------- loudness measurement

def _rms_dbfs(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if samples.size == 0:
        return -90.0
    rms = float(np.sqrt(np.mean(samples ** 2))) / 32768.0
    return round(20 * np.log10(rms), 2) if rms > 0 else -90.0


def _measure_lufs(path: Path) -> tuple[float, str]:
    """Integrated loudness via ffmpeg's loudnorm measurement pass. These clips are far shorter
    than EBU R128's measurement window, so a result pegged at the silence floor (~ -70 LUFS)
    is treated as unusable and RMS dBFS is reported instead."""
    if shutil.which("ffmpeg"):
        try:
            proc = subprocess.run(
                ["ffmpeg", "-nostats", "-hide_banner", "-i", str(path),
                 "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
            )
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
            if m:
                val = float(json.loads(m.group(0))["input_i"])
                if val == val and val > -69.0:  # not NaN and not stuck at the measurement floor
                    return round(val, 2), "ebur128"
        except Exception:
            pass
    return _rms_dbfs(path), "rms"


# ---------------------------------------------------------------- public API

def generate(out_dir: str | Path | None = None, force: bool = False) -> list[dict]:
    """Write the deterministic SFX palette (5 categories x 4 variants) plus manifest.json into
    `out_dir` (default: the sfx folder under config.DATA_HOME). Skips regeneration when every
    expected file and the manifest already exist, unless `force` is set.

    manifest.json can hold entries for other sound files too (e.g. a separately curated,
    licensed library living in the same folder), so only the entries for files this function
    owns (named "<category>_<NN>.wav" for one of CATEGORIES) are ever replaced -- every other
    entry already in the manifest is preserved untouched."""
    out_dir = Path(out_dir) if out_dir is not None else config.DATA_HOME / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    own_files = {f"{cat}_{i + 1:02d}.wav" for cat in CATEGORIES for i in range(len(_VARIANTS[cat]))}
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    other_entries = [e for e in existing if e.get("file") not in own_files]
    own_entries = [e for e in existing if e.get("file") in own_files]

    if not force and len(own_entries) == len(own_files) and all((out_dir / f).exists() for f in own_files):
        return other_entries + own_entries

    own_entries = []
    for cat in CATEGORIES:
        for i in range(len(_VARIANTS[cat])):
            fname = f"{cat}_{i + 1:02d}.wav"
            fpath = out_dir / fname
            _write_wav(fpath, _synthesize(cat, i))
            lufs, method = _measure_lufs(fpath)
            own_entries.append({"file": fname, "category": cat, "variant": i + 1, "lufs": lufs,
                                 "lufs_method": method})
    manifest_path.write_text(json.dumps(other_entries + own_entries, indent=2), encoding="utf-8")
    return other_entries + own_entries


if __name__ == "__main__":
    made = generate()
    print(f"wrote {len(made)} sfx files to {config.DATA_HOME / 'sfx'}")
