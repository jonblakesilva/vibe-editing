"""Full workflow on the sample recording: import -> transcribe -> plan -> approve ->
render 16:9 + 9:16 + Shorts -> verify with ffprobe, re-transcribe the output to
confirm captions are in sync with the speech. Marked slow."""
import json
from pathlib import Path

import pytest

from conftest import sha

pytestmark = pytest.mark.slow


@pytest.fixture
def planned(sample_video):
    from studio import brand, pipeline, project
    brand.create("Booked Solid", vocabulary=["Booked Solid System"])
    original = sha(sample_video)
    proj = project.create(sample_video, name="E2E", brand="booked-solid", mode="repurpose")
    plan = pipeline.make_plan(proj["id"], mode="repurpose", shorts_count=2, short_min=8, short_max=25)
    return proj, plan, original


def test_plan_finds_the_mistakes(planned):
    _, plan, _ = planned
    types = {c["type"] for c in plan["cuts"]}
    assert {"pause", "filler", "restart", "repeat"} <= types
    assert plan["stats"]["edited_duration"] < plan["stats"]["source_duration"] * 0.7
    assert plan["clips"] and all(c["est_duration"] <= 25 for c in plan["clips"])
    assert "Booked Solid System" in json.dumps(plan["sentences"])  # vocabulary fix applied


def test_render_verify_and_preserve_original(planned, sample_video):
    from studio import pipeline, transcribe
    proj, plan, original = planned
    pipeline.revise(proj["id"], ops=[{"op": "set", "path": "outputs",
                                      "value": [{"name": "youtube", "aspect": "16:9", "width": 1920, "height": 1080},
                                                {"name": "shorts", "aspect": "9:16", "width": 1080, "height": 1920}]}])
    with pytest.raises(PermissionError):
        pipeline.render_main(proj["id"], quality="final")
    pipeline.approve(proj["id"])
    results = pipeline.render_main(proj["id"], quality="final")
    assert len(results) == 2 and all(r["ok"] for r in results), [r["checks"] for r in results]
    assert {(r["width"], r["height"]) for r in results} == {(1920, 1080), (1080, 1920)}
    # caption timing vs the speech actually in the rendered file
    out = Path(results[0]["path"])
    heard = transcribe.transcribe(out, out.parent / "_verify", model="small")
    ass = Path(results[0]["captions"]["ass"]).read_text(encoding="utf-8")
    from studio import captions
    rep = captions.check_sync(heard["words"], ass, tolerance=0.25)
    assert rep["out_of_sync"] <= 1, rep
    shorts = pipeline.render_shorts(proj["id"], quality="final")
    assert shorts and all(r["ok"] for r in shorts)
    assert any(r["path"].endswith("_clean.mp4") for r in shorts)
    assert all((r["width"], r["height"]) == (1080, 1920) for r in shorts)
    exports = Path(results[0]["path"]).parent
    assert (exports / "chapters.txt").exists() and (exports / "publishing_pack.md").exists()
    assert sha(sample_video) == original, "original recording must never change"
