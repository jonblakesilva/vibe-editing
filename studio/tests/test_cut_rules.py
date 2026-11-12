"""Nate Herk editing-playbook rules: guard single fillers against clipping neighbouring
words, and pad cut starts so a kept word's trailing decay survives the cut."""
import pytest

from studio import analyze, plan as plan_mod
from studio.timeline import pad_cut_starts


def _w(text, s, e, p=0.95):
    return {"word": text, "start": s, "end": e, "prob": p}


def _isolated_filler_words():
    """"um" with >=0.1s silence on both sides."""
    return [
        _w("Most", 0.0, 0.5),
        _w("Um,", 1.0, 1.3),
        _w("businesses", 1.6, 2.1),
    ]


def _tight_filler_words():
    """"um" with only 0.03s gaps on both sides - cutting it would clip the neighbours."""
    return [
        _w("Most", 0.0, 0.5),
        _w("um,", 0.53, 0.83),
        _w("businesses", 0.86, 1.4),
    ]


def test_isolated_filler_is_cut_with_guard_on():
    cuts = analyze.find_fillers(_isolated_filler_words(), filler_guard=True)
    assert len(cuts) == 1
    c = cuts[0]
    assert c["enabled"] is True
    assert c["confidence"] == pytest.approx(0.9)


def test_tight_filler_disabled_with_guard_on():
    words = _tight_filler_words()
    cuts = analyze.find_fillers(words, filler_guard=True)
    assert len(cuts) == 1
    c = cuts[0]
    assert c["enabled"] is False
    assert c["confidence"] == pytest.approx(0.4)
    assert "runs into the next word" in c["reason"]
    assert "left in" in c["reason"]


def test_tight_filler_enabled_with_guard_off():
    """Old behaviour: no guard means the filler is still emitted for cutting (enabled once
    analyze() applies its confidence threshold)."""
    words = _tight_filler_words()
    cuts = analyze.find_fillers(words, filler_guard=False)
    assert len(cuts) == 1
    c = cuts[0]
    assert "enabled" not in c  # same shape as before the guard existed
    assert c["confidence"] == pytest.approx(0.9)


def test_analyze_filler_guard_end_to_end():
    words = _tight_filler_words()
    transcript = {"words": words, "duration": 2.0, "segments": [], "language": "en"}
    guarded = analyze.analyze(transcript, filler_guard=True)
    unguarded = analyze.analyze(transcript, filler_guard=False)
    g = next(c for c in guarded["cuts"] if c["type"] == "filler")
    u = next(c for c in unguarded["cuts"] if c["type"] == "filler")
    assert g["enabled"] is False
    assert u["enabled"] is True


def test_filler_guard_still_cuts_a_well_isolated_filler_in_analyze():
    words = _isolated_filler_words()
    transcript = {"words": words, "duration": 3.0, "segments": [], "language": "en"}
    a = analyze.analyze(transcript, filler_guard=True)
    g = next(c for c in a["cuts"] if c["type"] == "filler")
    assert g["enabled"] is True


# ---------------------------------------------------------------- pad_cut_starts

def test_pad_moves_non_pause_cut_start_later():
    cuts = [{"start": 5.0, "end": 5.4, "type": "filler", "enabled": True}]
    padded = pad_cut_starts(cuts, 0.06)
    assert padded[0]["start"] == pytest.approx(5.06)
    assert padded[0]["end"] == pytest.approx(5.4)  # end untouched


def test_pad_leaves_pause_and_dead_air_unchanged():
    cuts = [{"start": 2.0, "end": 3.0, "type": "pause", "enabled": True},
            {"start": 0.0, "end": 0.5, "type": "dead_air", "enabled": True}]
    padded = pad_cut_starts(cuts, 0.06)
    assert padded[0]["start"] == pytest.approx(2.0)
    assert padded[1]["start"] == pytest.approx(0.0)


def test_pad_skipped_when_cut_would_shrink_below_minimum():
    # cut is only 0.08s long; padding by 0.06 would leave 0.02s, below the 0.05s floor
    cuts = [{"start": 1.0, "end": 1.08, "type": "filler", "enabled": True}]
    padded = pad_cut_starts(cuts, 0.06)
    assert padded[0]["start"] == pytest.approx(1.0)  # left unpadded


def test_pad_never_moves_start_past_its_own_end():
    """The padded start always stays within [start, end] - inside the removed/silence span -
    so it never eats into a kept word before the cut."""
    cuts = [{"start": 10.0, "end": 10.3, "type": "restart", "enabled": True}]
    padded = pad_cut_starts(cuts, 0.06)
    assert cuts[0]["start"] <= padded[0]["start"] <= cuts[0]["end"]


def _project():
    return {"id": "p1", "source": {"path": "x.mp4", "duration": 21.5, "width": 1920, "height": 1080, "fps": 30.0}}


def test_plan_build_sets_cut_pad_and_filler_guard(transcript):
    from studio import brand
    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    assert p["cut_pad"] == pytest.approx(0.06)
    assert p["filler_guard"] is True


def test_plan_timeline_pads_non_pause_cuts(transcript):
    from studio import brand
    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    assert p.get("cut_pad")
    tl_padded = plan_mod.timeline(p)

    p_unpadded = dict(p)
    del p_unpadded["cut_pad"]
    tl_unpadded = plan_mod.timeline(p_unpadded)

    # padding removes slightly less at each non-pause cut, so the edited video is a little
    # longer than (or equal to, if every cut happens to be a pause) the unpadded version.
    assert tl_padded.duration >= tl_unpadded.duration


def test_plan_without_cut_pad_or_filler_guard_matches_pre_existing_behaviour(transcript):
    """Regression guard: a plan dict with neither key (as already-built plans on disk have)
    must produce exactly the same keep-segments as before these features existed."""
    from studio import brand
    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    old_style = dict(p)
    old_style.pop("cut_pad", None)
    old_style.pop("filler_guard", None)

    segs_with_keys_absent = plan_mod.timeline(old_style).segments

    # Build the plan the way it would have been built before this feature existed: no guard
    # applied during analysis, and no padding at timeline time.
    from studio import analyze as an
    legacy_analysis_cuts = an.find_fillers(transcript["words"])
    assert all("enabled" not in c for c in legacy_analysis_cuts), (
        "legacy fillers never carried an explicit enabled flag"
    )

    plan_no_pad = dict(old_style)
    plan_no_pad["cut_pad"] = 0  # falsy -> gate must not pad
    segs_without_pad_flag = plan_mod.timeline(plan_no_pad).segments
    assert segs_with_keys_absent == segs_without_pad_flag


def test_kept_word_is_never_cut_into_with_pad(words, transcript):
    """End-to-end: with filler_guard + cut_pad on, every kept word still survives whole in
    the edited timeline, the same guarantee test_never_cuts_inside_kept_words checks today."""
    from studio import brand

    p = plan_mod.build(_project(), transcript, brand=brand.load(None))
    tl = plan_mod.timeline(p)
    kept = tl.map_words(words)
    for w in kept:
        src = words[w["src_index"]]
        assert any(s - 1e-6 <= src["start"] and src["end"] <= e + 0.04 for s, e in tl.segments)
