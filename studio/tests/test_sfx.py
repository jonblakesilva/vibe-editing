import hashlib
import json
import wave
from pathlib import Path

import numpy as np

from studio import sfx


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generate_writes_20_wavs_and_a_manifest(tmp_path):
    entries = sfx.generate(out_dir=tmp_path)
    wavs = sorted(tmp_path.glob("*.wav"))
    assert len(wavs) == 20
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 20
    categories = {e["category"] for e in manifest}
    assert categories == set(sfx.CATEGORIES) == {"whoosh", "tap", "click", "paper", "check"}
    for cat in categories:
        assert sum(1 for e in manifest if e["category"] == cat) == 4  # 5 categories x 4 variants


def test_no_sci_fi_sfx_names():
    banned = ("laser", "zap", "riser", "plop")
    for cat in sfx.CATEGORIES:
        assert not any(b in cat.lower() for b in banned)


def test_manifest_entries_have_numeric_lufs(tmp_path):
    entries = sfx.generate(out_dir=tmp_path)
    for e in entries:
        assert isinstance(e["lufs"], (int, float))
        assert e["lufs"] == e["lufs"]  # not NaN


def test_generate_is_deterministic_across_rebuilds(tmp_path):
    sfx.generate(out_dir=tmp_path)
    first = {p.name: _sha(p) for p in tmp_path.glob("*.wav")}
    sfx.generate(out_dir=tmp_path, force=True)  # force a full rebuild, not a no-op skip
    second = {p.name: _sha(p) for p in tmp_path.glob("*.wav")}
    assert first == second
    assert len(first) == 20


def test_skips_regeneration_unless_forced(tmp_path):
    sfx.generate(out_dir=tmp_path)
    wav = next(tmp_path.glob("*.wav"))
    before = wav.stat().st_mtime_ns
    sfx.generate(out_dir=tmp_path)  # no force: existing files must be left untouched
    assert wav.stat().st_mtime_ns == before


def test_every_file_is_short_48k_stereo_16bit_with_peak_in_range(tmp_path):
    sfx.generate(out_dir=tmp_path)
    for wav_path in tmp_path.glob("*.wav"):
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            n = wf.getnframes()
            raw = wf.readframes(n)
        duration = n / 48000
        assert duration <= 0.5
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
        peak = float(np.max(np.abs(samples)))
        peak_db = 20 * np.log10(peak) if peak > 0 else -999.0
        assert peak_db <= -5.0, f"{wav_path.name} peaks at {peak_db:.2f} dBFS"
        assert peak_db > -12.0, f"{wav_path.name} peaks at {peak_db:.2f} dBFS"


def test_default_out_dir_is_under_configured_data_home(isolated_home):
    # isolated_home (conftest, autouse) already points config.DATA_HOME at a throwaway folder.
    entries = sfx.generate()
    assert (isolated_home / "sfx" / "manifest.json").exists()
    assert len(entries) == 20


def test_check_tone_stays_at_or_under_250ms(tmp_path):
    sfx.generate(out_dir=tmp_path)
    for wav_path in sorted(tmp_path.glob("check_*.wav")):
        with wave.open(str(wav_path), "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        assert duration <= 0.25
