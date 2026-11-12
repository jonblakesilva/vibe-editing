import pytest

from studio import thumbnail


def _set_project(home, pid, *, topic="A Great Video", brand="default", source_path="clip.mp4"):
    """Minimal project + plan on disk, enough for thumbnail.make()'s validation and (when
    `photos` is used) its no-video-needed path."""
    d = home / "projects" / pid
    (d / "work").mkdir(parents=True)
    (d / "exports").mkdir()
    (d / "project.json").write_text('{"id": "%s", "name": "%s"}' % (pid, topic), encoding="utf-8")
    (d / "plan.json").write_text(
        '{"source": {"path": "%s"}, "summary": {"topic": "%s"}, "brand": "%s"}' % (source_path, topic, brand),
        encoding="utf-8",
    )
    return d


# --- layout parameter validation -------------------------------------------------------

def test_unknown_layout_is_rejected(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="layout"):
        thumbnail.make("p1", layout="bogus", photos=["x.jpg"])


def test_payment_layout_requires_amount(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="amount"):
        thumbnail.make("p1", layout="payment", photos=["x.jpg"])


def test_checklist_layout_requires_items(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="items"):
        thumbnail.make("p1", layout="checklist", photos=["x.jpg"])


def test_two_person_layout_requires_photo2(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="photo2"):
        thumbnail.make("p1", layout="two-person", photos=["x.jpg"])


def test_screenshot_layout_requires_screenshot(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="screenshot"):
        thumbnail.make("p1", layout="screenshot", photos=["x.jpg"])


def test_unknown_chip_is_rejected(isolated_home):
    _set_project(isolated_home, "p1")
    with pytest.raises(ValueError, match="chip"):
        thumbnail.make("p1", chip="bogus_pin", photos=["x.jpg"])


def test_validation_happens_before_touching_the_filesystem():
    """An invalid layout is rejected even for a project that doesn't exist -- validation
    doesn't need to load the project first."""
    with pytest.raises(ValueError, match="layout"):
        thumbnail.make("no-such-project", layout="bogus")


def test_valid_layouts_cover_the_documented_set():
    assert thumbnail.LAYOUTS == (
        "face-number", "payment", "checklist", "screenshot", "two-person", "clean-white", "shorts-cover",
    )


# --- text auto-fit helper ---------------------------------------------------------------

def test_fit_title_uses_max_size_for_a_short_title():
    # the same column width/height make() uses for a single-person layout (560 x out_h-200)
    fit = thumbnail.fit_title("25,000 DOORS", max_width=560, max_height=520, max_size=150, min_size=40)
    assert fit["size"] == 150
    assert " ".join(fit["lines"]).split() == "25,000 DOORS".split()


def test_fit_title_shrinks_and_wraps_a_long_title():
    short = thumbnail.fit_title("360 OLD LEADS", max_width=560, max_height=200, max_size=150, min_size=40)
    long = thumbnail.fit_title(
        "Why More Leads Won't Fix Your Contractor Business", max_width=560, max_height=200, max_size=150, min_size=40,
    )
    assert long["size"] < short["size"]
    assert len(long["lines"]) > 1


def test_fit_title_never_drops_or_duplicates_words():
    text = "Why More Leads Won't Fix Your Contractor Business"
    fit = thumbnail.fit_title(text, max_width=560, max_height=200, max_size=150, min_size=40)
    rewrapped = " ".join(fit["lines"]).split()
    assert rewrapped == text.upper().split()


def test_fit_title_respects_the_height_budget_when_it_can():
    fit = thumbnail.fit_title("A FAIRLY LONG TITLE WITH SEVERAL WORDS", max_width=500, max_height=260,
                               max_size=160, min_size=40, line_height=1.08)
    assert len(fit["lines"]) * fit["size"] * 1.08 <= 260 + 1e-6


def test_fit_title_floors_at_min_size_when_nothing_else_fits():
    fit = thumbnail.fit_title("AN EXTREMELY LONG TITLE THAT WILL NEVER FIT NO MATTER HOW SMALL",
                               max_width=200, max_height=60, max_size=160, min_size=40)
    assert fit["size"] == 40


def test_fit_title_uppercases_the_result():
    fit = thumbnail.fit_title("get more calls", max_width=600, max_height=500)
    assert all(line == line.upper() for line in fit["lines"])


def test_fit_title_handles_empty_text():
    fit = thumbnail.fit_title("", max_width=600, max_height=500, max_size=150)
    assert fit["size"] == 150
    assert fit["lines"] == [""]


# --- checklist item normalisation --------------------------------------------------------

def test_normalize_items_reads_trailing_check_and_cross_marks():
    items = thumbnail._normalize_items(["More leads ✗", "Follow-up ✓", "Reviews"])
    assert items == [
        {"text": "More leads", "done": False},
        {"text": "Follow-up", "done": True},
        {"text": "Reviews", "done": False},
    ]


def test_normalize_items_accepts_explicit_dicts():
    items = thumbnail._normalize_items([{"text": "Reviews", "done": True}])
    assert items == [{"text": "Reviews", "done": True}]


# --- face box placement math -------------------------------------------------------------

def test_face_crop_touches_the_bottom_edge():
    img_w, img_h = 1280, 720
    face = (500.0, 70.0, 300.0, 320.0)  # a close, big face near the top third of the frame
    left, top, right, bottom = thumbnail._face_crop_box(face, img_w, img_h)
    assert bottom == img_h


def test_face_crop_keeps_the_face_at_least_40_percent_of_the_crop_height():
    img_w, img_h = 1280, 720
    face = (500.0, 70.0, 300.0, 320.0)
    fx, fy, fw, fh = face
    left, top, right, bottom = thumbnail._face_crop_box(face, img_w, img_h)
    crop_h = bottom - top
    assert crop_h > 0
    assert fh / crop_h >= 0.4


def test_face_crop_keeps_some_headroom_above_the_face():
    img_w, img_h = 1280, 720
    face = (500.0, 300.0, 280.0, 200.0)  # face positioned well down the frame
    fx, fy, fw, fh = face
    left, top, right, bottom = thumbnail._face_crop_box(face, img_w, img_h)
    assert top <= fy - fh * 0.4  # the hair above the face is never cropped away
    assert top >= 0


def test_face_crop_mask_top_can_pull_the_crop_down_further():
    img_w, img_h = 1280, 720
    face = (500.0, 70.0, 300.0, 320.0)
    _, top_no_mask, _, _ = thumbnail._face_crop_box(face, img_w, img_h)
    _, top_with_mask, _, _ = thumbnail._face_crop_box(face, img_w, img_h, mask_top=300.0)
    assert top_with_mask >= top_no_mask


def test_face_crop_is_horizontally_centred_on_the_face():
    img_w, img_h = 1280, 720
    face = (500.0, 70.0, 300.0, 320.0)
    fx, fy, fw, fh = face
    left, top, right, bottom = thumbnail._face_crop_box(face, img_w, img_h)
    cx = fx + fw / 2
    assert abs((left + right) / 2 - cx) < 1.5  # rounding only


# --- _polish: no thick white outline by default -------------------------------------------

def test_polish_default_has_no_opaque_white_ring():
    import numpy as np
    from PIL import Image

    size = (120, 160)
    arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    arr[20:140, 20:100, 0:3] = 180  # a solid, roughly centred "person" blob
    arr[20:140, 20:100, 3] = 255
    im = Image.fromarray(arr, "RGBA")
    polished = thumbnail._polish(im)
    px = np.asarray(polished)
    # just outside the person's original silhouette: not opaque white (no white sticker ring)
    edge_region = px[0:18, 0:18]
    assert not ((edge_region[..., 0] > 240) & (edge_region[..., 1] > 240) & (edge_region[..., 2] > 240)
                & (edge_region[..., 3] > 200)).any()


def test_polish_outline_true_keeps_the_legacy_white_ring():
    import numpy as np
    from PIL import Image

    size = (120, 160)
    arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    arr[20:140, 20:100, 0:3] = 180
    arr[20:140, 20:100, 3] = 255
    im = Image.fromarray(arr, "RGBA")
    polished = thumbnail._polish(im, outline=True)
    px = np.asarray(polished)
    assert ((px[..., 0] > 240) & (px[..., 1] > 240) & (px[..., 2] > 240) & (px[..., 3] > 200)).any()
