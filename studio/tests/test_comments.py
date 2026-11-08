"""Review comments: pinned to the right moment, mapped to the original, applied as revisions."""
import json

import pytest

from studio import brand, comments, config
from studio import plan as plan_mod


@pytest.fixture
def project(transcript):
    pid = "p-comments"
    d = config.PROJECTS_DIR / pid
    (d / "work").mkdir(parents=True)
    (d / "exports").mkdir()
    proj = {"id": pid, "name": "c", "source": {"path": "x.mp4", "duration": 21.5, "width": 1920, "height": 1080, "fps": 30.0}}
    (d / "project.json").write_text(json.dumps(proj), encoding="utf-8")
    plan = plan_mod.build(proj, transcript, brand=brand.load(None))
    plan_mod.save(plan, d / "plan.json")
    return pid, plan


def test_comment_on_export_maps_to_original_time(project):
    pid, plan = project
    tl = plan_mod.timeline(plan)
    c = comments.add(pid, "too fast here", at=3.0, file="Topic_youtube_preview.mp4")
    assert c["source_at"] == pytest.approx(tl.to_source(3.0), abs=0.01)
    assert comments.add(pid, "nice", at=7.5)["source_at"] == 7.5
    short = comments.add(pid, "cut this", at=2.0, file="shorts/short01_x_shorts.mp4")
    assert short["source_at"] is None  # Shorts are stitched from several places
    assert [x["status"] for x in comments.load(pid)] == ["open"] * 3


def test_apply_resolve_and_delete(project):
    pid, plan = project
    c = comments.add(pid, "Make the captions smaller", at=1.0)
    applied = comments.try_apply(pid, c["id"])
    assert applied["status"] == "applied"
    new_plan = json.loads((config.PROJECTS_DIR / pid / "plan.json").read_text(encoding="utf-8"))
    assert new_plan["captions"]["size_scale"] < plan["captions"]["size_scale"]
    vague = comments.add(pid, "this part feels off", at=2.0)
    assert comments.try_apply(pid, vague["id"])["status"] == "open"  # left for Claude
    comments.update(pid, vague["id"], status="resolved", resolution="Tightened pacing")
    comments.delete(pid, c["id"])
    left = comments.load(pid)
    assert len(left) == 1 and left[0]["status"] == "resolved"
