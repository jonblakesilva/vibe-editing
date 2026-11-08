"""Frame.io-style review: versions are kept on re-render, statuses, threaded comments with drawings."""
import json

import pytest

from studio import comments, config, media, render, review


def _clip(path, color):
    media.run_ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=1", "-f", "lavfi", "-i",
                      "sine=d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])


@pytest.fixture
def proj():
    pid = "p-review"
    d = config.PROJECTS_DIR / pid
    (d / "exports" / "shorts").mkdir(parents=True)
    (d / "work").mkdir()
    (d / "project.json").write_text(json.dumps({"id": pid, "source": {"duration": 1}}), encoding="utf-8")
    return pid, d / "exports"


def test_rerender_keeps_versions(proj):
    pid, ex = proj
    out = ex / "Topic_youtube.mp4"
    _clip(out, "red")
    assert render.archive_previous(out, {"plan_version": 1}) == 1
    _clip(out, "blue")
    assert render.archive_previous(out, {"plan_version": 2}) == 2
    _clip(out, "green")
    a = review.assets(pid)
    assert len(a) == 1 and a[0]["name"] == "Full video - YouTube 16:9"
    assert [v["v"] for v in a[0]["versions"]] == [1, 2, 3] and a[0]["versions"][-1]["current"]
    assert (ex / a[0]["versions"][0]["file"]).exists()


def test_status_and_short_names(proj):
    pid, ex = proj
    _clip(ex / "shorts" / "short01_Attention_is_half_the_battle_shorts.mp4", "red")
    _clip(ex / "shorts" / "short01_Attention_is_half_the_battle_shorts_clean.mp4", "red")
    names = [x["name"] for x in review.assets(pid)]
    assert "Short 1: Attention is half the battle" in names
    assert "Short 1: Attention is half the battle - no captions" in names
    review.set_status(pid, "shorts/short01_Attention_is_half_the_battle_shorts.mp4", "approved", "Jon")
    st = {x["file"]: x["status"]["status"] for x in review.assets(pid)}
    assert st["shorts/short01_Attention_is_half_the_battle_shorts.mp4"] == "approved"
    with pytest.raises(ValueError):
        review.set_status(pid, "x.mp4", "published")


def test_threaded_comments_with_drawing_and_range(proj):
    pid, ex = proj
    _clip(ex / "Topic_youtube.mp4", "red")
    c = comments.add(pid, "Logo too small", at=0.4, end=0.9, file="Topic_youtube.mp4", author="Jon",
                     annotation=[{"type": "rect", "color": "#F97316", "points": [[0.1, 0.1], [1.4, -2]]},
                                 {"type": "laser", "points": [[0, 0], [1, 1]]}])
    assert c["end"] == 0.9 and len(c["annotation"]) == 1
    assert c["annotation"][0]["points"][1] == [1, 0]  # clamped into the frame
    r = comments.add(pid, "Fixed in v2", at=0.4, file="Topic_youtube.mp4", author="Claude (editor)", parent=c["id"])
    assert r["parent"] == c["id"]
    with pytest.raises(KeyError):
        comments.add(pid, "orphan", at=0, parent="nope")
    assert review.assets(pid)[0]["open_comments"] == 1  # replies are not counted separately
    comments.delete(pid, c["id"])
    assert comments.load(pid) == []  # deleting a comment removes its replies
