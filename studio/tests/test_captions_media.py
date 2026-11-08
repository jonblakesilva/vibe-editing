"""Caption timing/placement, media helpers, missing dependencies, cancellation,
render recovery and API key handling."""
import subprocess
import threading
from pathlib import Path

import pytest

from studio import captions, config, media, render


def test_caption_sync_and_formats(words):
    style = {"style": "karaoke", "font": "Montserrat ExtraBold", "size": 72, "primary": "#FFFFFF",
             "highlight": "#FFD400", "outline": 5, "shadow": 3, "uppercase": True, "max_words": 4, "lines": 2,
             "animation": "highlight"}
    ass = captions.build_ass(words, style, width=1080, height=1920)
    rep = captions.check_sync(words, ass)
    assert rep["ok"] and rep["events"] >= len(words) - 2
    assert "&H0000D4FF" in ass  # brand highlight in ASS BGR order
    srt = captions.to_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert captions.to_vtt(words).startswith("WEBVTT")


def test_caption_safe_zones_and_face_avoidance():
    v = captions.layout(1080, 1920, "auto")
    assert v["alignment"] == 2 and v["margin_v"] >= 1920 * 0.25  # above TikTok/Reels UI
    h = captions.layout(1920, 1080, "auto")
    assert h["margin_v"] < 1080 * 0.1
    face_low = [{"x": 0.4, "y": 0.55, "w": 0.2, "h": 0.35}]
    assert captions.layout(1920, 1080, "auto", face_low)["position"] == "top"


def test_manual_correction_keeps_timing(words):
    from studio import transcribe
    t = {"words": [dict(w) for w in words]}
    before = (t["words"][3]["start"], t["words"][3]["end"])
    transcribe.apply_corrections(t, {3: "HALF"})
    assert t["words"][3]["word"] == "HALF" and (t["words"][3]["start"], t["words"][3]["end"]) == before


def test_vocabulary_fix():
    from studio import transcribe
    t = {"words": [{"word": "the", "start": 0, "end": .1}, {"word": "book", "start": .1, "end": .3},
                   {"word": "Solid", "start": .3, "end": .6}, {"word": "system.", "start": .6, "end": 1}]}
    fixes = transcribe.apply_vocabulary(t, ["Booked Solid"])
    assert fixes and t["words"][1]["word"] == "Booked" and t["words"][2]["start"] == .3


def test_missing_dependency_message(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(media.MediaError, match="doctor"):
        media.require("ffmpeg")


def test_probe_missing_file():
    with pytest.raises(media.MediaError, match="not found"):
        media.probe("does_not_exist.mp4")


def _make_clip(path: Path, dur=4, size="640x360"):
    media.run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={dur}", "-f", "lavfi", "-i",
                      f"sine=f=300:d={dur}:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                      "-c:a", "aac", "-shortest", str(path)])
    return path


def test_cancellation_stops_ffmpeg(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(media.Cancelled):
        media.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=600", "-c:v", "libx264",
                          str(tmp_path / "long.mp4")], duration=600, cancel=cancel)


def test_render_resumes_from_cached_sections(tmp_path):
    src = _make_clip(tmp_path / "src.mp4")
    segs = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0)]
    render.render_cut(str(src), segs, tmp_path / "w", fps=30, quality="preview")
    files = sorted((tmp_path / "w" / "segments_preview").glob("seg_*.mkv"))
    assert len(files) == 3
    stamps = {f.name: f.stat().st_mtime_ns for f in files}
    files[1].unlink()  # simulate a crash that lost one section
    for j in (tmp_path / "w").glob("cut_preview_*.mkv"):
        j.unlink()
    cut = render.render_cut(str(src), segs, tmp_path / "w", fps=30, quality="preview")
    after = {f.name: f.stat().st_mtime_ns for f in sorted((tmp_path / "w" / "segments_preview").glob("seg_*.mkv"))}
    assert after[files[0].name] == stamps[files[0].name] and after[files[2].name] == stamps[files[2].name]
    info = media.probe(cut)
    assert info.duration == pytest.approx(3.0, abs=0.05)


def test_av_durations_match_after_many_cuts(tmp_path):
    """Audio sync: 30 cuts must not accumulate drift."""
    src = _make_clip(tmp_path / "src.mp4", dur=20)
    segs = [(i * 0.6 + 0.013, i * 0.6 + 0.43) for i in range(30)]
    from studio.timeline import keep_segments
    cuts = [{"start": e, "end": segs[i + 1][0], "enabled": True} for i, (s, e) in enumerate(segs[:-1])]
    cuts = [{"start": 0, "end": segs[0][0], "enabled": True}] + cuts + [{"start": segs[-1][1], "end": 20, "enabled": True}]
    ks = keep_segments(20, cuts, fps=30, min_keep=0.1)
    cut = render.render_cut(str(src), ks, tmp_path / "w", fps=30, quality="preview")
    sd = media.stream_durations(cut)
    expected = sum(e - s for s, e in ks)
    assert sd["video"] == pytest.approx(expected, abs=0.034)
    assert sd["audio"] == pytest.approx(sd["video"], abs=0.02), "audio drifted from video"


def test_keys_load_from_private_file_and_redact(tmp_path, monkeypatch):
    f = tmp_path / "keys.env"
    f.write_text("GROQ_API_KEY=gsk_test_1234567890abcdef\n# comment\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    names = config.load_keys(f)
    assert names == ["GROQ_API_KEY"] and config.has_key("GROQ_API_KEY")
    assert "gsk_test" not in config.redact("error with gsk_test_1234567890abcdef inside")
    assert not str(config.KEYS_FILE.resolve()).startswith(str(config.REPO.resolve())), "keys must live outside the repo"


def test_no_secrets_committed():
    import re
    tracked = subprocess.run(["git", "ls-files", "studio"], cwd=config.REPO, capture_output=True, text=True).stdout.split()
    pat = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|AIza[0-9A-Za-z_-]{30,})")
    for rel in tracked:
        p = config.REPO / rel
        if p.suffix in (".py", ".md", ".json", ".ts", ".tsx", ".txt", ".html", ".js", ".css"):
            assert not pat.search(p.read_text(encoding="utf-8", errors="ignore")), f"possible secret in {rel}"
