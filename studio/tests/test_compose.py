from studio import compose, pipeline
from studio import plan as plan_mod


def test_screencam_zooms_only_on_full_camera():
    src = {"layout": "screencam", "cam_ranges": [[0, 10], [50, 60]]}
    zooms = [{"start": 2, "end": 5}, {"start": 20, "end": 25}, {"start": 55, "end": 58}, {"start": 8, "end": 12}]
    assert plan_mod._zooms_for_layout(zooms, src) == [zooms[0], zooms[2]]
    assert plan_mod._zooms_for_layout(zooms, {}) == zooms


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


def test_phrase_retakes_inside_one_sentence():
    from studio import analyze as an
    words = _words([(0.0, "Or you finished a great project and you never asked, or you finished a great project "
                          "and you forgot to ask, or you finished a great project and you forgot to ask for a review."),
                    (12.0, "We've got local service pages. We've got location pages.")])
    cuts = an.find_phrase_retakes(words)
    assert len(cuts) == 1 and cuts[0]["start"] == 0.0
    last_try = [w for w in words if w["start"] >= cuts[0]["end"]][0]
    assert last_try["word"].lower().startswith("or") and last_try["start"] > 6  # the third try is kept
