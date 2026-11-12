"""The "playbook" caption style (Nate Herk's editing playbook): punchy 1-3 word
chunks, one dark box with a light edge, whole-chunk red/green/teal colour, captions
that move with a cut, and the rendered-video contrast check that backs it all up."""
from __future__ import annotations

import hashlib
import subprocess

import pytest

from studio import captions, plan, qa


def _w(text, s, e):
    return {"word": text, "start": s, "end": e}


def _timed_words(text: str) -> list[dict]:
    """A realistic word-timed transcript: ~0.1-0.4s per word, a small gap after commas
    and a bigger one after sentence-enders, like a real transcription would hand back."""
    words, t = [], 0.0
    for raw in text.split():
        dur = len(raw) * 0.035 + 0.12
        words.append(_w(raw, round(t, 3), round(t + dur, 3)))
        t += dur + (0.3 if raw.endswith((".", "?", "!")) else 0.05)
    return words


# A realistic ~85-word sales-education transcript, deliberately full of the playbook's
# loss/action/key-concept vocabulary so the colour-share logic has real work to do.
TRANSCRIPT_80 = (
    "Most businesses lose half their leads because they wait too long to follow up and "
    "that costly mistake wastes real money every single month. The fix is simple once "
    "you see it. You can book more calls, close more deals, and get real results fast "
    "when you stop wasting time on manual follow up. Build an automated system that "
    "never misses a lead again so nothing falls through the cracks. Our playbook helps "
    "you double your pipeline and grow revenue without working more hours. Clients save "
    "thousands of dollars and win more contracts than they ever thought possible before "
    "this. Click the link below to start your free trial today and watch your numbers "
    "grow this very week."
)


def _line_times(line: str) -> tuple[float, float]:
    f = line.split(",", 9)
    return captions._parse_ass_time(f[1]), captions._parse_ass_time(f[2])


# ---------------------------------------------------------------- chunk_playbook


def test_chunks_never_exceed_three_words():
    words = _timed_words(TRANSCRIPT_80)
    chunks = captions.chunk_playbook(words)
    assert chunks  # sanity: the transcript actually produced chunks
    assert all(1 <= len(c) <= 3 for c in chunks)


def test_chunk_playbook_avoids_stranding_a_leading_small_word():
    # "to" would land alone at the end of a 3-word chunk; it should carry into the next
    words = [_w("answer", 0.0, 0.3), _w("every", 0.3, 0.6), _w("lead", 0.6, 0.9),
             _w("to", 0.9, 1.0), _w("win", 1.0, 1.3), _w("more.", 1.3, 1.6)]
    chunks = captions.chunk_playbook(words)
    assert not any(len(c) > 1 and captions._bare(c[-1]["word"]) in captions._NO_SPLIT_AFTER for c in chunks)


# ---------------------------------------------------------------- colour_chunks


def test_coloured_share_within_25_to_45_percent_on_realistic_transcript():
    words = _timed_words(TRANSCRIPT_80)
    chunks = captions.chunk_playbook(words)
    colours = captions.colour_chunks(chunks)
    share = sum(1 for c in colours if c) / len(colours)
    assert 0.25 - 1e-9 <= share <= 0.45 + 1e-9


def test_red_has_priority_over_green():
    # "lose" is a loss word (red); "money" is also a green payoff word -- red must win
    chunks = [[_w("Lose", 0.0, 0.3), _w("money.", 0.3, 0.6)]]
    chunks += [[_w(f"word{i}a", 0.0, 0.1), _w(f"word{i}b", 0.1, 0.2)] for i in range(9)]
    colours = captions.colour_chunks(chunks)
    assert colours[0] == "red"


def test_colour_chunks_adds_teal_up_to_25_percent_when_nothing_else_qualifies():
    chunks = [[_w(f"plain{i}", 0.0, 0.3)] for i in range(12)]  # no red/green/keyword hits
    colours = captions.colour_chunks(chunks)
    assert sum(1 for c in colours if c) >= 3  # ceil(12 * 0.25)
    assert all(c in (None, "teal") for c in colours)


def test_colour_chunks_keywords_tag_teal():
    chunks = [[_w("Our", 0.0, 0.2), _w("playbook.", 0.2, 0.5)]]
    chunks += [[_w(f"plain{i}", 0.0, 0.3)] for i in range(9)]
    colours = captions.colour_chunks(chunks, keywords=["playbook"])
    assert colours[0] == "teal"


# ---------------------------------------------------------------- build_playbook / build_ass


def test_playbook_style_is_exposed_for_plan_wiring():
    assert captions.PLAYBOOK_STYLE["style"] == "playbook"
    assert captions.PLAYBOOK_STYLE.get("box") == "dark"


def test_ass_contains_both_edge_rect_and_dark_box_rect():
    words = [_w("Book", 1.0, 1.3), _w("more", 1.3, 1.6), _w("calls.", 1.6, 1.9)]
    ass = captions.build_ass(words, dict(captions.PLAYBOOK_STYLE), width=1080, height=1920)
    assert "Style: BoxEdge," in ass and "Style: Box," in ass
    edge_lines = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")]
    box_lines = [l for l in ass.splitlines() if l.startswith("Dialogue: 1,")]
    assert edge_lines and box_lines
    # the edge rect is drawn larger than the box rect it sits behind
    import re
    edge_coords = [float(x) for x in re.findall(r"-?\d+\.\d+", edge_lines[0].split(",", 9)[-1])]
    box_coords = [float(x) for x in re.findall(r"-?\d+\.\d+", box_lines[0].split(",", 9)[-1])]
    assert min(edge_coords[0::2]) < min(box_coords[0::2])  # edge's left edge is further left


def test_no_fade_in_playbook_events_and_two_frame_lead_in():
    words = [_w("Book", 1.000, 1.300), _w("more", 1.300, 1.600), _w("calls.", 1.600, 1.900)]
    style = dict(captions.PLAYBOOK_STYLE, fps=30)
    ass = captions.build_ass(words, style, width=1080, height=1920)
    assert r"\fad" not in ass
    cap_lines = [l for l in ass.splitlines() if l.startswith("Dialogue: 2,")]
    assert len(cap_lines) == 1
    start, _end = _line_times(cap_lines[0])
    assert start == pytest.approx(1.0 - 2 / 30, abs=0.011)


def test_chunk_spanning_a_join_splits_into_two_events_at_the_join():
    words = [_w("Book", 10.0, 10.3), _w("calls.", 10.3, 10.6)]
    style = dict(captions.PLAYBOOK_STYLE, anchors=[10.45])
    ass = captions.build_ass(words, style, width=1080, height=1920)
    cap_lines = [l for l in ass.splitlines() if l.startswith("Dialogue: 2,")]
    assert len(cap_lines) == 2
    spans = sorted(_line_times(l) for l in cap_lines)
    assert spans[0][1] == pytest.approx(10.45, abs=0.02)
    assert spans[1][0] == pytest.approx(10.45, abs=0.02)


def test_position_override_moves_the_box_for_that_segment():
    words = [_w("Low", 1.0, 1.3), _w("shot.", 1.3, 1.6)]
    base = dict(captions.PLAYBOOK_STYLE)
    ass_default = captions.build_ass(words, base, width=1080, height=1920)
    moved = dict(captions.PLAYBOOK_STYLE, position_overrides=[{"start": 0.0, "end": 5.0, "cy": 1500.0}])
    ass_moved = captions.build_ass(words, moved, width=1080, height=1920)
    box_default = [l for l in ass_default.splitlines() if l.startswith("Dialogue: 1,")][0]
    box_moved = [l for l in ass_moved.splitlines() if l.startswith("Dialogue: 1,")][0]
    assert box_default != box_moved


# ---------------------------------------------------------------- qa.check_contrast


def _make_lavfi_video(path, *, dark_box=None, w=640, h=360, dur=1.5):
    bg = f"color=c=white:s={w}x{h}:d={dur}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", bg]
    vf = []
    if dark_box:
        x, y, bw, bh = dark_box
        vf.append(f"drawbox=x={x}:y={y}:w={bw}:h={bh}:color=0x0B0B0F@0.86:t=fill")
    vf.append("format=yuv420p")
    cmd += ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def test_contrast_check_flags_a_box_region_that_isnt_dark(tmp_path):
    video = _make_lavfi_video(tmp_path / "white.mp4")
    boxes = [{"start": 0.2, "end": 1.0, "x": 100, "y": 100, "w": 200, "h": 80}]
    report = qa.check_contrast(video, boxes, samples=10)
    assert any(i["type"] == "box_not_dark" for i in report["issues"])


def test_contrast_check_passes_when_a_dark_box_is_drawn_there(tmp_path):
    video = _make_lavfi_video(tmp_path / "dark_box.mp4", dark_box=(100, 100, 200, 80))
    boxes = [{"start": 0.2, "end": 1.0, "x": 100, "y": 100, "w": 200, "h": 80}]
    report = qa.check_contrast(video, boxes, samples=10)
    assert not any(i["type"] == "box_not_dark" for i in report["issues"])


# ---------------------------------------------------------------- regression: other styles unchanged

_REGRESSION_WORDS = [
    _w("Most", 0.0, 0.3), _w("businesses", 0.3, 0.9), _w("lose", 0.9, 1.2), _w("half", 1.2, 1.5),
    _w("their", 1.5, 1.7), _w("leads.", 1.7, 2.2),
    _w("Um,", 5.2, 5.5), _w("today", 5.6, 6.0), _w("I'll", 6.0, 6.2), _w("show", 6.2, 6.5), _w("you", 6.5, 6.7),
    _w("the", 6.7, 6.8), _w("system.", 6.8, 7.4),
    _w("So", 8.0, 8.2), _w("the", 8.2, 8.3), _w("first", 8.3, 8.6), _w("step", 8.6, 8.9), _w("is.", 8.9, 9.2),
    _w("Sorry,", 9.8, 10.2), _w("let", 10.2, 10.4), _w("me", 10.4, 10.5), _w("start", 10.5, 10.8),
    _w("that", 10.8, 11.0), _w("again.", 11.0, 11.4),
    _w("The", 12.0, 12.2), _w("first", 12.2, 12.5), _w("step", 12.5, 12.8), _w("is", 12.8, 12.9),
    _w("to", 12.9, 13.0), _w("answer", 13.0, 13.4), _w("every", 13.4, 13.7), _w("lead.", 13.7, 14.2),
    _w("The", 14.8, 15.0), _w("first", 15.0, 15.3), _w("step", 15.3, 15.6), _w("is", 15.6, 15.7),
    _w("to", 15.7, 15.8), _w("answer", 15.8, 16.2), _w("every", 16.2, 16.5), _w("lead.", 16.5, 17.0),
    _w("units.", 17.1, 17.3),
    _w("Click", 19.4, 19.7), _w("the", 19.7, 19.8), _w("link", 19.8, 20.1), _w("below.", 20.1, 20.6),
]

# Captured from captions.build_ass() for every studio.plan.CAPTION_STYLES entry, before the
# playbook style was added, over the transcript above. If any of these change, an existing
# (non-playbook) caption style rendered differently -- the playbook work must not do that.
_EXPECTED_HASHES = {
    "clean_shadow_1080x1920": "9e3e30608e34eb6f79f1cdd331a55f597ff2f70bd970cff55378cf9b766ad696",
    "clean_shadow_1920x1080": "4749cee89dd7182ea198826e40ee658053fd608611c5e02caef105cb7cd22bcf",
    "punch_1080x1920": "6abda26b78f2852264b42a3627fe65acc07daf556f2b0b9b6170bec5abc5205b",
    "punch_1920x1080": "c58c872e91f9d37e74c50d5b44204dc61e567d8096215aac2d7d06f502c97f04",
    "premium_1080x1920": "5e7fa733a2e5c5fdc341a200ccbad5348c37273c995c422d4e85e56c8f9736d4",
    "premium_1920x1080": "920156b4876c981a1047d6c6e3c06bd73111a625584dd89a886ce5f5a2066475",
    "clean_1080x1920": "4c57dd9df06ded593e3ec98e18a06b5b56573a6a483eb78a78f52988389f1a8d",
    "clean_1920x1080": "de175ab53def040086b2b9db3649d29be6c573e65732797d053c6d8cd23c2d40",
    "minimal_1080x1920": "ce80f2a435d83e856b75d803107199b8abd36ecb23384b483c5db0b656dcd6f0",
    "minimal_1920x1080": "1a0ff2b65cbba21e37cab02b6c94855e46bc5ad5870ccc38173b59fc71768209",
    "karaoke_1080x1920": "13fd64a2cf06dad3db0b265dc775d83e7442a01ef4f917d427e6337c5995866a",
    "karaoke_1920x1080": "9e5ae7e158e318af87d7dbcfd06eaf6b5e74c2fc347e8aa8364debf6636dcbd3",
    "bold_1080x1920": "ba66d809466dcdde63b63894cb332142f47bbbce253c7d089681cc790d882955",
    "bold_1920x1080": "899a17d964aa925688094ca2ce41f7af7ee3c9c92ed49fdcbdfed795627364df",
}


@pytest.mark.parametrize("style_name", [s for s in plan.CAPTION_STYLES if s != "playbook"])
@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_existing_caption_styles_unchanged_by_playbook_work(style_name, size):
    W, H = size
    ass = captions.build_ass(_REGRESSION_WORDS, dict(plan.CAPTION_STYLES[style_name]), width=W, height=H)
    got = hashlib.sha256(ass.encode()).hexdigest()
    assert got == _EXPECTED_HASHES[f"{style_name}_{W}x{H}"]
