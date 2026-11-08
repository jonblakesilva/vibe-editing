import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: real transcription/render tests (seconds to minutes)")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own studio data folder; nothing touches ~/VibeStudio."""
    from studio import config
    home = tmp_path / "home"
    monkeypatch.setattr(config, "DATA_HOME", home)
    monkeypatch.setattr(config, "PROJECTS_DIR", home / "projects")
    monkeypatch.setattr(config, "BRANDS_DIR", home / "brands")
    monkeypatch.setattr(config, "MUSIC_DIR", home / "music")
    monkeypatch.setattr(config, "BROLL_DIR", home / "broll")
    return home


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """A 47 s talking-head test recording with deliberate mistakes (built locally)."""
    mp4 = FIXTURES / "sample_talking_head.mp4"
    wav = FIXTURES / "sample_speech.wav"
    if not mp4.exists():
        if not wav.exists():
            if platform.system() != "Windows":
                pytest.skip("sample speech generator needs Windows System.Speech")
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(FIXTURES / "make_sample.ps1")], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1b2a3a:s=1920x1080:r=30",
                        "-i", str(wav), "-filter_complex",
                        "[0]drawbox=x=760+100*sin(t):y=300:w=400:h=480:color=0xd9a77f@1:t=fill[v]",
                        "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "aac", "-shortest", str(mp4)], check=True)
    return mp4


@pytest.fixture
def words():
    """Synthetic word-level transcript with known mistakes."""
    def w(text, s, e, p=0.95):
        return {"word": text, "start": s, "end": e, "prob": p}
    return [
        w("Most", 0.0, 0.3), w("businesses", 0.3, 0.9), w("lose", 0.9, 1.2), w("half", 1.2, 1.5),
        w("their", 1.5, 1.7), w("leads.", 1.7, 2.2),
        # 3 s pause
        w("Um,", 5.2, 5.5), w("today", 5.6, 6.0), w("I'll", 6.0, 6.2), w("show", 6.2, 6.5), w("you", 6.5, 6.7),
        w("the", 6.7, 6.8), w("system.", 6.8, 7.4),
        w("So", 8.0, 8.2), w("the", 8.2, 8.3), w("first", 8.3, 8.6), w("step", 8.6, 8.9), w("is.", 8.9, 9.2),
        w("Sorry,", 9.8, 10.2), w("let", 10.2, 10.4), w("me", 10.4, 10.5), w("start", 10.5, 10.8),
        w("that", 10.8, 11.0), w("again.", 11.0, 11.4),
        w("The", 12.0, 12.2), w("first", 12.2, 12.5), w("step", 12.5, 12.8), w("is", 12.8, 12.9),
        w("to", 12.9, 13.0), w("answer", 13.0, 13.4), w("every", 13.4, 13.7), w("lead.", 13.7, 14.2),
        w("The", 14.8, 15.0), w("first", 15.0, 15.3), w("step", 15.3, 15.6), w("is", 15.6, 15.7),
        w("to", 15.7, 15.8), w("answer", 15.8, 16.2), w("every", 16.2, 16.5), w("lead.", 16.5, 17.0),
        w("units.", 17.1, 17.3, 0.05),
        # 2 s pause
        w("Click", 19.4, 19.7), w("the", 19.7, 19.8), w("link", 19.8, 20.1), w("below.", 20.1, 20.6),
    ]


@pytest.fixture
def transcript(words):
    return {"words": words, "duration": 21.5, "segments": [], "language": "en"}
