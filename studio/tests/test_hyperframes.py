"""HyperFrames card staging/rendering: brand tokens applied, slots filled and
escaped, no network references left in the staged files, deterministic card
picks, and a slow real-render smoke test."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from studio import config, hyperframes as hf

TLV_BRAND = {
    "slug": "tlv-test",
    "colors": {
        "primary": "#0D5DCB",
        "accent": "#F97316",
        "text": "#FFFFFF",
        "background": "#0F1E4A",
        "highlight": "#F97316",
        "navy": "#0F1E4A",
    },
    "fonts": {"title": "Outfit", "captions": "Outfit Bold", "body": "Inter"},
}

LOWER_THIRD_ID = "kallaway.t2.lower-third.minimal"


def _stage(tmp_path, slots=None, duration=3.0):
    slots = slots if slots is not None else {"name": "Ronny Mitchell", "role": "Head of Content Strategy"}
    path = hf.stage(LOWER_THIRD_ID, slots, TLV_BRAND, duration, tmp_path)
    return path, path.read_text(encoding="utf-8"), (path.parent / "tokens.css").read_text(encoding="utf-8")


# ---------------------------------------------------------------- registry / picking

def test_lower_third_purpose_exists_in_both_styles():
    # The taxonomy Agent 3 queries by (see library/GUIDE.md): confirm "lower-third"
    # is a real purpose, present for both vendored styles.
    purposes = {c["purpose"] for c in hf.cards()}
    assert "lower-third" in purposes
    styles_with_lower_third = {c["style"] for c in hf.cards(tier="tier2", purpose="lower-third")}
    assert {"kallaway", "vox-explainer"} <= styles_with_lower_third


def test_pick_card_lower_third_is_found_and_deterministic():
    a = hf.pick_card("tier2", "lower-third", seed="episode-1-beat-3")
    b = hf.pick_card("tier2", "lower-third", seed="episode-1-beat-3")
    assert a is not None
    assert a["id"] == b["id"]
    assert a["tier"] == "tier2" and a["purpose"] == "lower-third"
    # a different seed is free to (but need not) pick a different card; just prove
    # the function is a function of the seed, not of call order.
    c = hf.pick_card("tier2", "lower-third", seed="episode-9-beat-1")
    assert c is not None


def test_pick_card_falls_back_to_another_style_when_none_match():
    # no style in the library has this purpose; a made-up style name must fail
    # to match and fall through to whatever style actually has the purpose.
    card = hf.pick_card("tier2", "lower-third", style="not-a-real-style", seed="x")
    assert card is not None
    assert card["style"] in {"kallaway", "vox-explainer"}


# ---------------------------------------------------------------- staging

def test_stage_has_no_http_references_except_svg_xmlns(tmp_path):
    _, index_html, tokens_css = _stage(tmp_path)
    for label, text in (("index.html", index_html), ("tokens.css", tokens_css)):
        for line in text.splitlines():
            if "http" in line:
                assert "xmlns" in line, f"unexpected network reference in {label}: {line}"


def test_stage_sets_override_block_and_data_duration(tmp_path):
    _, index_html, tokens_css = _stage(tmp_path, duration=2.0)
    assert ":root {" in tokens_css
    assert "#0F1E4A" in tokens_css  # brand navy mapped onto the canvas/bg tokens
    assert "#F97316" in tokens_css  # brand accent mapped onto the accent token
    assert 'data-duration="2.0"' in index_html
    assert 'data-width="1920"' in index_html
    assert 'data-height="1080"' in index_html


def test_stage_fills_and_escapes_slots(tmp_path):
    _, index_html, _ = _stage(tmp_path, slots={"name": "<b>Jon</b>", "role": "Owner"})
    assert "&lt;b&gt;Jon&lt;/b&gt;" in index_html
    assert "<b>Jon</b>" not in index_html


def test_stage_unknown_slot_raises(tmp_path):
    with pytest.raises(ValueError):
        hf.stage(LOWER_THIRD_ID, {"not_a_real_slot": "x"}, TLV_BRAND, 3.0, tmp_path)


def test_stage_embeds_brand_font_file(tmp_path):
    # config.FONTS_DIR (unaffected by the isolated_home fixture) has Outfit*.ttf.
    _, _, tokens_css = _stage(tmp_path)
    assert "@font-face" in tokens_css
    assert "Outfit" in tokens_css
    fonts_dir = tmp_path / "_stage"
    staged_fonts = list(fonts_dir.rglob("fonts/*.ttf"))
    assert staged_fonts, "no font files were staged alongside the card"


def test_stage_is_cached_by_content_key(tmp_path):
    p1 = hf.stage(LOWER_THIRD_ID, {"name": "A", "role": "B"}, TLV_BRAND, 3.0, tmp_path)
    p2 = hf.stage(LOWER_THIRD_ID, {"name": "A", "role": "B"}, TLV_BRAND, 3.0, tmp_path)
    p3 = hf.stage(LOWER_THIRD_ID, {"name": "C", "role": "B"}, TLV_BRAND, 3.0, tmp_path)
    assert p1 == p2
    assert p1 != p3


# ---------------------------------------------------------------- check_slot_text

def test_check_slot_text_flags_percent_missing_from_transcript():
    warnings = hf.check_slot_text({"stat": "47%"}, transcript_text="We grew a lot this year.")
    assert any("47%" in w for w in warnings)


def test_check_slot_text_allows_percent_present_in_transcript():
    warnings = hf.check_slot_text({"stat": "47%"}, transcript_text="Conversion jumped 47% in Q2.")
    assert warnings == []


def test_check_slot_text_normalizes_dollar_k_against_plain_number():
    warnings = hf.check_slot_text({"stat": "$30K"}, transcript_text="", knowledge_text="We closed at 30,000 total.")
    assert warnings == []


def test_check_slot_text_still_flags_a_genuinely_unsupported_number():
    warnings = hf.check_slot_text({"stat": "$30K"}, transcript_text="We closed a small deal.")
    assert any("30K" in w for w in warnings)


# ---------------------------------------------------------------- tier_allowed

def test_tier1_not_allowed_in_vertical_frame():
    assert hf.tier_allowed("tier1", 1920, 1080) is True
    assert hf.tier_allowed("tier1", 1080, 1920) is False


def test_tier2_allowed_in_vertical_frame():
    assert hf.tier_allowed("tier2", 1080, 1920) is True


# ---------------------------------------------------------------- real render (slow)

@pytest.mark.slow
def test_render_tier2_lower_third_has_alpha(tmp_path):
    assert hf.available(), "HyperFrames is not installed; this probe PC has it under studio/motion/hyperframes"
    out_dir = tmp_path / "out"
    out = hf.render_card(
        LOWER_THIRD_ID,
        {"name": "Jon Silva", "role": "Owner, The Lead Venture"},
        TLV_BRAND,
        duration=2.0,
        out_dir=out_dir,
        fps=30,
        quality="standard",
    )
    assert out is not None and out.is_file(), "render_card returned no file; HyperFrames render failed"

    ffprobe = shutil.which("ffprobe")
    assert ffprobe, "ffprobe not found on PATH"
    res = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    pix_fmt = res.stdout.strip()
    assert "a" in pix_fmt, f"expected an alpha pixel format, got {pix_fmt!r}"
