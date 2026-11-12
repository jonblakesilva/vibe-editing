"""Playbook pace (T8): Nate Herk's measured house-reel pause rules and punch-in zooms.
Synthetic word lists only - no transcript fixtures needed."""
import pytest

from studio import analyze


def _w(text, s, e, p=0.95):
    return {"word": text, "start": s, "end": e, "prob": p}


def _kept_gap(words: list[dict], idx: int, cuts: list[dict]) -> float:
    """Silence still left between words[idx-1] and words[idx] after the cuts touching that
    gap are applied (0 if a cut removes the whole gap, the full original gap if none do)."""
    gap = words[idx]["start"] - words[idx - 1]["end"]
    removed = sum(c["end"] - c["start"] for c in cuts
                  if c["start"] >= words[idx - 1]["end"] - 1e-6 and c["end"] <= words[idx]["start"] + 1e-6)
    return gap - removed


# ---------------------------------------------------------------------------
# find_pauses: playbook's tight default + natural-beat exception
# ---------------------------------------------------------------------------

def test_long_gap_between_sentences_is_shortened_to_about_015s():
    words = [_w("Hello", 0.0, 0.5), _w("everyone.", 0.5, 1.0),
             _w("Today", 4.0, 4.4), _w("we", 4.4, 4.6)]  # 3.0s gap, no beat
    cuts = analyze.find_pauses(words, max_pause=0.2, keep_pause=0.15, beat_max=0.4, beat_keep=0.35)
    assert len(cuts) == 1
    assert _kept_gap(words, 2, cuts) == pytest.approx(0.15, abs=1e-6)


def test_natural_beat_gap_under_threshold_is_kept_untouched():
    words = [_w("First,", 0.0, 0.4), _w("open", 0.75, 1.1)]  # 0.35s gap after "First,"
    cuts = analyze.find_pauses(words, max_pause=0.2, keep_pause=0.15, beat_max=0.4, beat_keep=0.35)
    assert cuts == []
    assert _kept_gap(words, 1, cuts) == pytest.approx(0.35, abs=1e-6)


def test_long_comma_gap_shortened_to_035s():
    words = [_w("Well,", 0.0, 0.4), _w("let's", 1.0, 1.3)]  # 0.6s gap after the comma
    cuts = analyze.find_pauses(words, max_pause=0.2, keep_pause=0.15, beat_max=0.4, beat_keep=0.35)
    assert len(cuts) == 1
    assert _kept_gap(words, 1, cuts) == pytest.approx(0.35, abs=1e-6)


def test_list_marker_without_comma_also_counts_as_a_beat():
    words = [_w("Next", 0.0, 0.4), _w("step", 0.75, 1.1)]  # 0.35s gap, no comma but a list marker
    cuts = analyze.find_pauses(words, max_pause=0.2, keep_pause=0.15, beat_max=0.4, beat_keep=0.35)
    assert cuts == []


# ---------------------------------------------------------------------------
# analyze(): full playbook pace - leading dead air and no cuts into a word
# ---------------------------------------------------------------------------

def _playbook_transcript():
    words = [
        _w("Well,", 0.3, 0.6),
        _w("today", 1.0, 1.4),       # 0.4s gap after the comma: a beat, kept
        _w("we", 1.4, 1.6),
        _w("will", 1.6, 1.8),
        _w("learn", 1.8, 2.2),
        _w("something.", 2.2, 2.7),
        _w("First,", 6.0, 6.4),      # 3.3s gap, no beat: shortened to 0.15
        _w("open", 6.75, 7.1),       # 0.35s gap after "First,": a beat, kept
        _w("settings.", 7.1, 7.6),
    ]
    return {"words": words, "duration": 9.0}


def test_speech_starts_within_01s_of_cut_start():
    t = _playbook_transcript()
    result = analyze.analyze(t, pace="playbook")
    lead_cuts = [c for c in result["cuts"] if c["type"] == "dead_air" and c["start"] == 0]
    assert len(lead_cuts) == 1
    assert t["words"][0]["start"] - lead_cuts[0]["end"] <= 0.1 + 1e-6


def test_no_cut_overlaps_any_word():
    t = _playbook_transcript()
    result = analyze.analyze(t, pace="playbook")
    for c in result["cuts"]:
        for w in t["words"]:
            overlaps = c["start"] < w["end"] - 1e-6 and c["end"] > w["start"] + 1e-6
            assert not overlaps, f"cut {c} overlaps word {w}"


# ---------------------------------------------------------------------------
# first_punch_in / punch_ins
# ---------------------------------------------------------------------------

def test_first_punch_in_lands_06_to_10s_after_first_word():
    words = [
        _w("Hey", 0.0, 0.3),
        _w("so", 0.3, 0.45),
        _w("today", 0.5, 0.75),      # dt=0.5, outside the 0.6-1.0s window
        _w("million", 0.8, 1.3),     # dt=0.8, a number word - charged
    ]
    first = analyze.first_punch_in(words)
    assert first is not None
    assert 0.6 <= first["time"] - words[0]["start"] <= 1.0
    assert first["scale"] == pytest.approx(1.12)
    assert first["word"] == "million"


def test_first_punch_in_falls_back_to_nearest_08s_when_nothing_charged():
    words = [
        _w("Hey", 0.0, 0.3),
        _w("and", 0.62, 0.75),  # dt=0.62, |0.62-0.8|=0.18 - not charged
        _w("the", 0.97, 1.05),  # dt=0.97, |0.97-0.8|=0.17 - not charged, nearest to 0.8
    ]
    first = analyze.first_punch_in(words)
    assert first is not None
    assert first["word"] == "the"  # |0.97-0.8| < |0.62-0.8|


def test_punch_ins_coverage_is_between_5_and_15_percent_of_duration():
    words = [
        _w("Hey", 0.0, 0.2),
        _w("friends,", 0.2, 0.6),
        _w("amazing", 0.8, 1.3),     # first punch-in: charged, dt=0.8
        _w("news", 1.3, 1.7),
        _w("today.", 1.7, 2.0),
        _w("Revenue", 5.0, 5.5),     # next sentence's first word: charged
        _w("grew", 5.5, 5.8),
        _w("fast.", 5.8, 6.1),
        _w("Customers", 10.0, 10.6),  # should not be needed once 5% is covered
        _w("loved", 10.6, 10.9),
        _w("it.", 10.9, 11.1),
    ]
    duration = 40.0
    punches = analyze.punch_ins(words, duration)
    total = sum(p["end"] - p["start"] for p in punches)
    assert 0.05 * duration <= total <= 0.15 * duration
    for p in punches:
        assert 1.2 <= p["end"] - p["start"] <= 2.0
        assert p["scale"] == pytest.approx(1.12)
        assert p.get("kind") == "punch"
    # none overlap
    ordered = sorted(punches, key=lambda p: p["start"])
    for a, b in zip(ordered, ordered[1:]):
        assert a["end"] <= b["start"]


def test_punch_ins_empty_for_zero_duration_or_no_words():
    assert analyze.punch_ins([], 40.0) == []
    assert analyze.punch_ins([_w("Hey", 0.0, 0.3)], 0.0) == []


# ---------------------------------------------------------------------------
# Regression: pace="shorts" is unchanged by the playbook additions
# ---------------------------------------------------------------------------

def test_shorts_pace_cuts_match_the_pre_playbook_code_path():
    """find_pauses(..., beat_max=None) (the default) is exactly the old, unconditional
    "shorten every gap over max_pause" rule; pace="shorts" never passes beat kwargs, so its
    pause cuts must match that reference call exactly, and the leading dead-air cut must still
    use the old 0.5s gate / 0.2s pad."""
    words = [_w("Hello", 0.8, 1.1), _w("there.", 1.1, 1.5),
             _w("Second", 2.5, 2.9), _w("sentence", 2.9, 3.3), _w("here.", 3.3, 3.6)]
    transcript = {"words": words, "duration": 4.0}

    result = analyze.analyze(transcript, pace="shorts")
    pause_cuts = [c for c in result["cuts"] if c["type"] == "pause"]
    expected_pause_cuts = analyze.find_pauses(words, max_pause=0.35, keep_pause=0.15)
    assert len(pause_cuts) == len(expected_pause_cuts) == 1
    for got, exp in zip(pause_cuts, expected_pause_cuts):
        assert got["start"] == pytest.approx(exp["start"])
        assert got["end"] == pytest.approx(exp["end"])

    lead_cuts = [c for c in result["cuts"] if c["type"] == "dead_air" and c["start"] == 0]
    assert len(lead_cuts) == 1
    assert lead_cuts[0]["end"] == pytest.approx(words[0]["start"] - 0.2)


def test_shorts_pace_unaffected_when_words_contain_playbook_beat_markers():
    """A comma/list-marker gap that WOULD be treated specially under pace="playbook" is cut
    the plain old way under pace="shorts" (beat rules only apply when pace == "playbook")."""
    words = [_w("First,", 0.8, 1.1), _w("open", 1.45, 1.8)]  # 0.35s gap after "First,"
    transcript = {"words": words, "duration": 3.0}
    result = analyze.analyze(transcript, pace="shorts")
    pause_cuts = [c for c in result["cuts"] if c["type"] == "pause"]
    # Under "shorts" (max_pause=0.35, keep_pause=0.15) a 0.35s gap is not > max_pause, so it's
    # left alone either way here - the real check is that no beat-only cut sneaks in.
    expected = analyze.find_pauses(words, max_pause=0.35, keep_pause=0.15)
    assert pause_cuts == expected
