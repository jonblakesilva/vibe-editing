"""Cut accuracy, mistake detection, timeline mapping and the plan/approval flow."""
import pytest

from studio import analyze, plan as plan_mod
from studio.timeline import Timeline, keep_segments, snap


def cuts_of(a, kind):
    return [c for c in a["cuts"] if c["type"] == kind]


def test_detects_pause_filler_restart_repeat_noise(transcript):
    a = analyze.analyze(transcript)
    assert cuts_of(a, "pause"), "long pauses should be shortened"
    assert any(c["text"].lower().startswith("um") for c in cuts_of(a, "filler"))
    restart = cuts_of(a, "restart")
    assert restart and restart[0]["start"] == pytest.approx(8.0) and 11.4 <= restart[0]["end"] < 12.0
    rep = cuts_of(a, "repeat")
    assert rep and rep[0]["start"] == pytest.approx(12.0), "earlier take removed, last take kept"
    assert cuts_of(a, "noise") and cuts_of(a, "noise")[0]["text"] == "units."
    assert a["cta"] and "link below" in a["cta"][0]["text"].lower()


def test_pause_keeps_breathing_room(transcript):
    a = analyze.analyze(transcript, pace="natural")
    p = cuts_of(a, "pause")[0]
    remaining = (p["start"] - 2.2) + (5.2 - p["end"])
    assert remaining == pytest.approx(0.4, abs=0.01)


def test_never_cuts_inside_kept_words(transcript, words):
    a = analyze.analyze(transcript)
    segs = keep_segments(transcript["duration"], a["cuts"], fps=30)
    tl = Timeline(segs)
    kept = tl.map_words(words)
    texts = " ".join(w["word"] for w in kept)
    # the final good take and the CTA survive intact
    assert "The first step is to answer every lead." in texts
    assert "Click the link below." in texts
    assert "units." not in texts and "Sorry," not in texts
    for w in kept:  # every kept word lies wholly inside one kept segment
        src = words[w["src_index"]]
        assert any(s - 1e-6 <= src["start"] and src["end"] <= e + 0.04 for s, e in segs)


def test_timeline_mapping_roundtrip():
    tl = Timeline([(1.0, 3.0), (5.0, 6.0)])
    assert tl.duration == pytest.approx(3.0)
    assert tl.to_edit(2.0) == pytest.approx(1.0)
    assert tl.to_edit(4.0) is None
    assert tl.to_edit_nearest(4.0) == pytest.approx(2.0)
    assert tl.to_source(2.5) == pytest.approx(5.5)


def test_segments_are_frame_snapped():
    segs = keep_segments(10.0, [{"start": 1.013, "end": 2.517, "enabled": True}], fps=30)
    for s, e in segs:
        assert abs(s * 30 - round(s * 30)) < 1e-4 and abs(e * 30 - round(e * 30)) < 1e-4


def test_disabled_cut_is_kept():
    segs = keep_segments(10.0, [{"start": 2, "end": 4, "enabled": False}], fps=30)
    assert segs == [(0.0, 10.0)]


def _project():
    return {"id": "p1", "source": {"path": "x.mp4", "duration": 21.5, "width": 1920, "height": 1080, "fps": 30.0}}


def test_plan_build_markdown_and_revisions(transcript):
    from studio import brand
    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    md = plan_mod.to_markdown(p)
    for section in ("Mistakes and dead air", "Sections kept", "Captions", "Audio", "Outputs", "Suggested hook"):
        assert section in md
    size = p["captions"]["size_scale"]
    ops = plan_mod.parse_request(p, "Make the captions smaller.")
    p2 = plan_mod.revise(p, ops, "Make the captions smaller.")
    assert p2["captions"]["size_scale"] < size and p2["version"] == 2
    ops = plan_mod.parse_request(p2, 'Add a title behind me saying "THE BOOKED SOLID SYSTEM"', at=6.0)
    p3 = plan_mod.revise(p2, ops)
    g = p3["graphics"][-1]
    assert g["template"] == "KineticTitle" and g["placement"] == "behind" and g["props"]["text"] == "THE BOOKED SOLID SYSTEM"
    restart = next(c for c in p3["cuts"] if c["type"] == "restart")
    p4 = plan_mod.revise(p3, [{"op": "toggle", "id": restart["id"], "enabled": False}], "Keep that section")
    assert plan_mod.stats(p4)["edited_duration"] > plan_mod.stats(p3)["edited_duration"]
    assert p4["revisions"][-1]["request"] == "Keep that section"


def test_unknown_request_returns_no_ops(transcript):
    from studio import brand
    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    assert plan_mod.parse_request(p, "make it feel like a summer evening") == []


def test_final_render_requires_approval(transcript, tmp_path):
    from studio import pipeline
    with pytest.raises(PermissionError):
        pipeline._require_approved({"status": "draft"}, "final")
    pipeline._require_approved({"status": "draft"}, "preview")  # previews are allowed


def test_shorts_scoring_prefers_standalone(transcript):
    from studio import shorts
    a = analyze.analyze(transcript, pace="shorts")
    clips = shorts.find_clips(transcript, a, count=3, min_len=3, max_len=12)
    assert clips
    for c in clips:
        assert set(c["scores"]) == {"hook", "value", "clarity", "relevance", "standalone", "retention", "cta"}
        assert all(0 <= v <= 10 for v in c["scores"].values())
        assert not c["hook"].lower().startswith(("sorry", "units"))
    starts = sorted((c["start"], c["end"]) for c in clips)
    assert all(a[1] <= b[0] for a, b in zip(starts, starts[1:])), "clips must not overlap"
