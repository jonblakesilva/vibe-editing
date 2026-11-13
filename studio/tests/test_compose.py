import numpy as np
import pytest

from studio import compose, pipeline
from studio import plan as plan_mod


def test_screencam_zooms_only_on_full_camera():
    src = {"layout": "screencam", "cam_ranges": [[0, 10], [50, 60]]}
    zooms = [{"start": 2, "end": 5}, {"start": 20, "end": 25}, {"start": 55, "end": 58}, {"start": 8, "end": 12}]
    assert plan_mod._zooms_for_layout(zooms, src) == [zooms[0], zooms[2]]
    assert plan_mod._zooms_for_layout(zooms, {}) == zooms


def test_short_graphics_includes_hypercard():
    # a tier2 HyperFrames label/lower-third card (e.g. the "add a label card" revision op)
    # must reach a Short's render just like the Remotion templates do - it was previously
    # left out of the template whitelist and silently dropped from every Short.
    clip = {"start": 100.0, "end": 130.0}
    plan = {"graphics": [
        {"id": "g1", "template": "HyperCard", "start": 110.0, "enabled": True, "props": {}},
        {"id": "g2", "template": "KineticTitle", "start": 101.0, "enabled": True, "props": {}},
        {"id": "g3", "template": "HyperCard", "start": 200.0, "enabled": True, "props": {}},  # outside the clip
    ]}
    out = pipeline._short_graphics(plan, clip)
    assert {g["id"] for g in out} == {"g1", "g2"}


def test_vertical_outputs_use_vertical_master(tmp_path):
    v = tmp_path / "layout_vertical.mp4"
    v.write_bytes(b"x")
    plan = {"source": {"path": "land.mp4", "vertical_path": str(v)}, "captions": {"position": "auto"}}
    assert pipeline._source_for(plan, {"width": 1080, "height": 1920}) == (str(v), True)
    assert pipeline._source_for(plan, {"width": 1920, "height": 1080}) == ("land.mp4", False)
    assert pipeline._layout_plan(plan)["captions"]["position"] == "middle"
    assert plan["captions"]["position"] == "auto"  # original plan untouched


def test_between_expr():
    assert compose._between([(0, 1.5), (3, 4)]) == "between(t,0.000,1.500)+between(t,3.000,4.000)"
    assert compose._between([]) == "0"


def test_find_takes_orders_clips_numerically(tmp_path):
    for name in ("Clip 10", "Clip 2", "Clip 4"):
        d = tmp_path / name
        d.mkdir()
        (d / "Camera.mp4").write_bytes(b"")
        (d / "Screen.mp4").write_bytes(b"")
    (tmp_path / "Clip 5").mkdir()  # no files: skipped
    assert [c.parent.name for c, _ in compose.find_takes(tmp_path)] == ["Clip 2", "Clip 4", "Clip 10"]


def _words(spec):
    out = []
    for start, text in spec:
        t = start
        for w in text.split():
            out.append({"word": w, "start": t, "end": t + 0.25, "prob": 0.99})
            t += 0.3
    return out


def test_retakes_keep_only_the_last_attempt():
    from studio import analyze as an
    words = _words([(0.0, "Hi, everyone."), (1.0, "My name is Jonathan and this is my tool."),
                    (10.0, "Hey guys, I'm Jonathan, I built a tool."),
                    (20.0, "Hey guys, my name is Jonathan and I built this tool."),
                    (24.0, "You put your business info in here."), (27.0, "We've got local service pages."),
                    (29.0, "We've got location pages.")])
    sents = an.sentences(words)
    cuts = an.find_retakes(sents)
    # everything before the last attempt (20 s) is removed, nothing after it
    assert min(c["start"] for c in cuts) == 0.0 and max(round(c["end"], 2) for c in cuts) == 19.95
    covered = sorted((c["start"], c["end"]) for c in cuts)
    assert all(b[0] <= a[1] + 0.1 for a, b in zip(covered, covered[1:]))  # no gaps between removed takes
    # "We've got local service pages / We've got location pages": similar openings without a
    # reset pause are normal speech, not retakes
    assert all(c["end"] < 20 for c in cuts)


def test_premium_captions_sit_on_the_seam_only_while_split():
    from studio import captions
    style = {"box": "rounded", "size": 50, "font": "Outfit Bold", "split_windows": [(2.0, 4.0)]}
    words = [{"word": "Full", "start": 0.0, "end": 0.4}, {"word": "camera.", "start": 0.4, "end": 0.8},
             {"word": "Split", "start": 2.5, "end": 2.9}, {"word": "screen.", "start": 2.9, "end": 3.3}]
    ass = captions.build_premium(words, style, width=1080, height=1920)
    ys = [float(line.split("\pos(")[1].split(",")[1].split(")")[0]) for line in ass.splitlines()
          if line.startswith("Dialogue: 1")]
    assert ys[0] > 1300 and ys[-1] == 960.0


# ---------------------------------------------------------------- smart screen focus (compose)

def test_frame_hotspot_finds_a_concentrated_feature_on_the_left():
    frame = np.full((200, 400), 40.0)
    frame[60:140, 10:90] = 220.0  # a bright "keyword list" block near the left edge
    spot = compose.frame_hotspot(frame)
    assert spot["cx"] < 0.35  # centred over the block, not the frame midpoint
    assert spot["spread"] < 0.5  # a concentrated feature gives a narrow span, not the whole frame


def test_frame_hotspot_ignores_top_chrome_band():
    frame = np.full((200, 400), 40.0)
    frame[0:16, :] = 255.0  # "browser chrome" strip in the ignored top 8%
    frame[150:190, 150:250] = 220.0  # the only other content, lower middle
    spot = compose.frame_hotspot(frame, ignore_top=0.08)
    assert spot["cy"] > 0.5  # pulled toward the real content, not the ignored chrome band


def test_frame_hotspot_blank_frame_defaults_to_centre():
    spot = compose.frame_hotspot(np.full((100, 100), 50.0))
    assert spot["cx"] == 0.5 and spot["spread"] == 1.0


def test_zoom_for_spread_clamped_and_monotonic():
    tight = compose._zoom_for_spread(0.05)
    wide = compose._zoom_for_spread(1.0)
    assert tight > wide >= 1.0  # a concentrated hot spot zooms in more than a spread-out one
    assert tight <= compose.SCREEN_FOCUS_MAX_WIDTH / compose.SCREEN_FOCUS_MIN_WIDTH + 1e-6


def test_smooth_focus_path_dead_zone_suppresses_jitter():
    samples = [{"t": t, "cx": 0.5 + (0.01 if t % 2 else -0.01), "cy": 0.5, "zoom": 1.0}
               for t in range(0, 10)]
    keys = compose.smooth_focus_path(samples, duration=10, dead_zone=0.05, hold=1.5)
    assert all(abs(k["cx"] - 0.5) < 0.02 for k in keys)  # tiny back-and-forth never adopted


def test_smooth_focus_path_holds_before_following_a_real_move():
    samples = ([{"t": 0.0, "cx": 0.2, "cy": 0.5, "zoom": 1.0}] +
               [{"t": t, "cx": 0.8, "cy": 0.5, "zoom": 1.0} for t in np.arange(0.2, 6.0, 0.2)])
    keys = compose.smooth_focus_path(samples, duration=6.0, dead_zone=0.05, hold=1.5, ease=0.3)
    early = [k for k in keys if k["t"] < 1.5]
    assert all(k["cx"] < 0.5 for k in early)  # held at the first position for >= hold seconds
    assert keys[-1]["cx"] > 0.6  # eventually eases over to the new target


def test_smooth_focus_path_empty_falls_back_to_default():
    keys = compose.smooth_focus_path([], duration=5.0)
    assert keys == [{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}]


def test_merge_focus_keyframes_manual_overrides_nearby_auto():
    auto = [{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}, {"t": 5.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0},
            {"t": 10.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}]
    manual = [{"t": 5.1, "cx": 0.1, "cy": 0.2, "zoom": 1.8}]
    merged = compose.merge_focus_keyframes(auto, manual, window=0.4)
    ts = [k["t"] for k in merged]
    assert 5.0 not in ts and 5.1 in ts  # the nearby auto point was dropped for the manual one
    assert {0.0, 10.0}.issubset(ts)  # points elsewhere are untouched
    hit = next(k for k in merged if k["t"] == 5.1)
    assert hit["cx"] == 0.1 and hit["zoom"] == 1.8


def test_merge_focus_keyframes_no_manual_is_a_passthrough():
    auto = [{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}]
    assert compose.merge_focus_keyframes(auto, None) == auto


def test_offset_keyframes_shifts_time_only():
    keys = [{"t": 1.0, "cx": 0.3, "cy": 0.4, "zoom": 1.2}]
    out = compose.offset_keyframes(keys, 10.0)
    assert out == [{"t": 11.0, "cx": 0.3, "cy": 0.4, "zoom": 1.2}]


def test_focus_box_series_keeps_baseline_aspect_at_every_zoom():
    keyframes = [{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}, {"t": 5.0, "cx": 0.5, "cy": 0.5, "zoom": 2.0}]
    series = compose.focus_box_series(keyframes, 1920, 1080, base_width_frac=0.45)
    aspects = [w / h for w, h in zip((v for _, v in series["w"]), (v for _, v in series["h"]))]
    assert aspects[0] == pytest.approx(aspects[1])
    assert aspects[0] == pytest.approx(1920 * 0.45 / 1080)
    assert series["w"][1][1] < series["w"][0][1]  # zoom=2 crops narrower than zoom=1


def test_focus_box_series_clamps_zoom_and_stays_on_frame():
    keyframes = [{"t": 0.0, "cx": 0.02, "cy": 0.02, "zoom": 50.0}]  # near the corner, absurd zoom request
    series = compose.focus_box_series(keyframes, 1920, 1080, base_width_frac=0.45, min_zoom=1.0, max_zoom=2.0)
    w, h = series["w"][0][1], series["h"][0][1]
    x, y = series["x"][0][1], series["y"][0][1]
    assert w == pytest.approx(1920 * 0.45 / 2.0)  # zoom clamped to max_zoom, not 50
    assert 0.0 <= x <= 1920 - w + 1e-6  # box clamped fully on-frame, not running off the left edge
    assert 0.0 <= y <= 1080 - h + 1e-6


def test_thin_keyframes_caps_point_count_but_keeps_the_last_point():
    keys = [{"t": float(i), "cx": 0.5, "cy": 0.5, "zoom": 1.0} for i in range(500)]
    thinned = compose._thin_keyframes(keys, max_points=50)
    assert len(thinned) <= 51
    assert thinned[-1] == keys[-1]


def test_thin_keyframes_below_cap_is_a_passthrough():
    keys = [{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}, {"t": 1.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}]
    assert compose._thin_keyframes(keys, max_points=100) == keys


def test_focus_box_series_default_zoom_matches_old_fixed_centre_crop():
    series = compose.focus_box_series([{"t": 0.0, "cx": 0.5, "cy": 0.5, "zoom": 1.0}], 1920, 1080,
                                      base_width_frac=0.45)
    w, x = series["w"][0][1], series["x"][0][1]
    assert w == pytest.approx(1920 * 0.45)
    assert x == pytest.approx((1920 - 1920 * 0.45) / 2)  # still centred when zoom is 1 and cx is 0.5


def test_phrase_retakes_inside_one_sentence():
    from studio import analyze as an
    words = _words([(0.0, "Or you finished a great project and you never asked, or you finished a great project "
                          "and you forgot to ask, or you finished a great project and you forgot to ask for a review."),
                    (12.0, "We've got local service pages. We've got location pages.")])
    cuts = an.find_phrase_retakes(words)
    assert len(cuts) == 1 and cuts[0]["start"] == 0.0
    last_try = [w for w in words if w["start"] >= cuts[0]["end"]][0]
    assert last_try["word"].lower().startswith("or") and last_try["start"] > 6  # the third try is kept
