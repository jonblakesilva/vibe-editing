"""T9 plan/CLI wiring: the playbook Shorts pace default, the opt-in music-library hookup
(studio/music.py via plan._brand_music), playbook captions, and the add_card revision op.
Builder-level unit tests only (plan.build()/parse_request()/revise()); no transcription or
rendering. `transcript`/`words` fixtures and the autouse `isolated_home` fixture (which
monkeypatches config.MUSIC_DIR etc. to a tmp folder) come from conftest.py."""
from __future__ import annotations

import json

import pytest

from studio import brand as brand_mod
from studio import config
from studio import hyperframes as hf
from studio import plan as plan_mod


def _project(duration: float = 21.5) -> dict:
    return {"id": "p1", "source": {"path": "x.mp4", "duration": duration, "width": 1920, "height": 1080, "fps": 30.0}}


# ---------------------------------------------------------------- shorts_settings.pace

def test_build_sets_playbook_shorts_pace(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    assert p["shorts_settings"]["pace"] == "playbook"


def test_old_format_plan_without_shorts_settings_still_loads_and_renders_markdown(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    raw = json.dumps(p)
    loaded = json.loads(raw)
    del loaded["shorts_settings"]  # simulate a plan saved before this field existed
    md = plan_mod.to_markdown(loaded)  # must not raise
    assert "Shorts pace: shorts" in md  # falls back to the pre-playbook default


# ---------------------------------------------------------------- music (opt-in, via studio/music.py)

def test_no_music_when_brand_disabled_and_no_mood_requested(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))  # music disabled by default
    assert p["audio"]["music"] is None
    assert not any("music" in n.lower() for n in p["summary"]["editor_notes"])


def test_music_none_with_note_when_library_is_empty(transcript):
    # The isolated_home fixture points config.MUSIC_DIR at an empty tmp folder; a brand that
    # has opted into music (TLV-style) still gets told why, not just silently skipped.
    br = brand_mod.load(None)
    br["music"]["enabled"] = True
    p = plan_mod.build(_project(), transcript, brand=br)
    assert p["audio"]["music"] is None
    notes = p["summary"]["editor_notes"]
    assert any("No music track matched mood" in n and "~/VibeStudio/music" in n for n in notes)


def test_explicit_music_mood_is_picked_with_bed_minus_11_default(transcript):
    config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (config.MUSIC_DIR / "track.mp3").write_bytes(b"not really audio, pick() never opens it")
    manifest = [{"file": "track.mp3", "title": "Test Track", "mood": ["confident"], "lufs": -10.0,
                "attribution_required": False}]
    (config.MUSIC_DIR / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    br = brand_mod.load(None)
    br["music"] = {}  # no brand-level bed_db/volume_db override: the -11 default should apply
    p = plan_mod.build(_project(), transcript, brand=br, options={"music_mood": "confident"})
    music = p["audio"]["music"]
    assert music is not None
    assert music["path"].endswith("track.mp3")
    assert music["bed_db"] == pytest.approx(-11)
    assert not p["summary"]["editor_notes"]


def test_music_mood_option_enables_music_even_for_a_disabled_brand(transcript):
    """Music is opt-in via options["music_mood"] OR the brand - either is enough."""
    config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (config.MUSIC_DIR / "track.mp3").write_bytes(b"x")
    manifest = [{"file": "track.mp3", "title": "Test Track", "mood": ["chill"], "attribution_required": False}]
    (config.MUSIC_DIR / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    br = brand_mod.load(None)
    assert br["music"]["enabled"] is False
    p = plan_mod.build(_project(), transcript, brand=br, options={"music_mood": "chill"})
    assert p["audio"]["music"] is not None
    assert p["audio"]["music"]["mood"] == "chill"


# ---------------------------------------------------------------- caption styles

def test_playbook_caption_style_is_registered_when_captions_has_it():
    from studio import captions
    if getattr(captions, "PLAYBOOK_STYLE", None):
        assert "playbook" in plan_mod.CAPTION_STYLES
        assert plan_mod.CAPTION_STYLES["playbook"]["style"] == "playbook"


def test_parse_request_playbook_captions_sets_the_style(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    if "playbook" not in plan_mod.CAPTION_STYLES:
        pytest.skip("captions.PLAYBOOK_STYLE not landed yet")
    ops = plan_mod.parse_request(p, "playbook captions")
    style_ops = [o for o in ops if o["op"] == "set" and o["path"] == "captions.style"]
    assert style_ops and style_ops[-1]["value"] == "playbook"
    p2 = plan_mod.revise(p, ops, "playbook captions")
    assert p2["captions"]["style"] == "playbook"


# ---------------------------------------------------------------- add_card

def test_parse_request_add_lower_third_card_adds_a_hypercard_graphic(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    before = len(p["graphics"])
    ops = plan_mod.parse_request(p, 'Add a lower third card saying "Jonathan Blake"')
    assert any(o["op"] == "add_card" and o["purpose"] == "lower-third" for o in ops)

    p2 = plan_mod.revise(p, ops, 'Add a lower third card saying "Jonathan Blake"')
    cards = [g for g in p2["graphics"] if g["template"] == "HyperCard"]
    assert len(cards) == 1
    assert len(p2["graphics"]) == before + 1
    valid_ids = {c["id"] for c in hf.cards()}
    assert cards[0]["props"]["card"] in valid_ids
    assert "Jonathan Blake" in cards[0]["props"]["slots"].values()


def test_add_card_lower_third_fills_remaining_slot_from_brand_lower_third(transcript):
    br = brand_mod.create("Test Co For Cards", lower_third={"name": "Jonathan Blake",
                                                             "title": "Founder, The Lead Venture"})
    p = plan_mod.build(_project(), transcript, brand=br)
    ops = plan_mod.parse_request(p, 'Add a lower third card saying "Jonathan Blake"')
    p2 = plan_mod.revise(p, ops, 'Add a lower third card saying "Jonathan Blake"')
    card = next(g for g in p2["graphics"] if g["template"] == "HyperCard")
    slots = card["props"]["slots"]
    if len(slots) > 1:  # the picked card has a slot beyond the quoted text
        assert "Founder, The Lead Venture" in slots.values()


def test_add_card_check_slot_text_warns_about_an_invented_number(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    ops = plan_mod.parse_request(p, 'Add a stat card saying "47%"')
    assert ops and any(o["op"] == "add_card" for o in ops)
    p2 = plan_mod.revise(p, ops, 'Add a stat card saying "47%"')
    assert any("47%" in n for n in p2["summary"]["editor_notes"]), p2["summary"]["editor_notes"]


def test_add_card_with_unknown_purpose_adds_a_note_instead_of_crashing(transcript):
    p = plan_mod.build(_project(), transcript, brand=brand_mod.load(None))
    before = len(p["graphics"])
    p2 = plan_mod.revise(p, [{"op": "add_card", "tier": "tier1", "purpose": "not-a-real-purpose",
                              "text": "x", "start": 1.0}], "test")
    assert len(p2["graphics"]) == before  # nothing added
    assert any("No HyperFrames card found" in n for n in p2["summary"]["editor_notes"])
