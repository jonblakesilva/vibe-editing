"""Nate Herk editing-playbook checks: B3 "every word whole" and B4 "mouth check"."""
from __future__ import annotations

import inspect

from studio import pipeline, qa


def _w(text, s, e):
    return {"word": text, "start": s, "end": e}


# ---------------------------------------------------------------- B3: word_whole_check

def test_clipped_word_near_join_is_flagged():
    # the edit kept "first", but the cut right after it clipped the trailing consonant
    expected = [_w("Let's", 4.6, 4.8), _w("talk", 4.8, 4.95), _w("first", 4.95, 5.2), _w("about", 5.25, 5.5)]
    heard = [_w("Let's", 4.6, 4.8), _w("talk", 4.8, 4.95), _w("firs", 4.95, 5.15), _w("about", 5.2, 5.5)]
    issues = qa.word_whole_check(expected, heard, joins=[5.0])
    assert any(i["expected"] == "first" and i["heard"] == "firs" for i in issues)


def test_identical_words_at_join_not_flagged():
    expected = [_w("Let's", 4.6, 4.8), _w("talk", 4.8, 4.95), _w("first", 4.95, 5.2), _w("about", 5.25, 5.5)]
    heard = [_w(w["word"], w["start"], w["end"]) for w in expected]
    issues = qa.word_whole_check(expected, heard, joins=[5.0])
    assert issues == []


def test_missing_word_at_join_is_flagged():
    expected = [_w("Let's", 4.6, 4.8), _w("talk", 4.8, 4.95), _w("first", 4.95, 5.2), _w("about", 5.25, 5.5)]
    # the whole word "first" was swallowed by the cut; the listen-back never heard it
    heard = [_w("Let's", 4.6, 4.8), _w("talk", 4.8, 4.95), _w("about", 5.0, 5.3)]
    issues = qa.word_whole_check(expected, heard, joins=[5.0])
    assert any(i["expected"] == "first" and i["heard"] == "" for i in issues)


# ---------------------------------------------------------------- B4: mouth_check

W, H = 1920, 1080


def _face(y0, y1, t=0.0, cx=0.5, w=0.25):
    """A face box spanning pixel rows y0..y1 in a WxH frame, as pipeline._faces_on_timeline
    would hand it to mouth_check (normalized cx/cy/w/h, edited-time t)."""
    return {"t": t, "cx": cx, "cy": (y0 + y1) / 2 / H, "w": w, "h": (y1 - y0) / H}


def test_caption_over_mouth_in_opening_is_flagged():
    face = _face(300, 780)  # mouth band ends up around y 564-828
    caption = {"start": 0.0, "end": 2.5, "x": 0, "y": 700, "w": W, "h": 100}
    issues = qa.mouth_check([face], [caption], [], W, H, joins=[], duration=10.0)
    assert any(i["type"] == "caption_over_mouth" for i in issues)


def test_caption_at_very_bottom_not_flagged():
    face = _face(300, 780)
    caption = {"start": 0.0, "end": 2.5, "x": 0, "y": 960, "w": W, "h": 80}
    issues = qa.mouth_check([face], [caption], [], W, H, joins=[], duration=10.0)
    assert issues == []


def test_graphic_over_mouth_at_join_plus_frame_is_flagged():
    face = _face(300, 780, t=5.0)
    graphic = {"start": 4.9, "end": 5.5, "x": 0, "y": 700, "w": W, "h": 100}
    issues = qa.mouth_check([face], [], [graphic], W, H, joins=[5.0], duration=10.0)
    assert any(i["type"] == "graphic_over_mouth" for i in issues)


# ---------------------------------------------------------------- signature compatibility

def test_listen_check_still_accepts_two_positional_paths():
    """No in-flight caller of listen_check(out_path, work) should break: the new
    expected_path/joins params must be optional and come after the original two."""
    sig = inspect.signature(pipeline.listen_check)
    params = list(sig.parameters.values())
    assert [p.name for p in params[:2]] == ["out_path", "work"]
    assert params[0].default is inspect.Parameter.empty
    assert params[1].default is inspect.Parameter.empty
    assert params[2].name == "expected_path" and params[2].default is None
