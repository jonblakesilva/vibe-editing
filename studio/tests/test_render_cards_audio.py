"""T4b (HyperCard overlays) + T10b (music/SFX mastering per Nate Herk's playbook).

Real ffmpeg encoding is never exercised here: `media.run_ffmpeg` is monkeypatched to a stub
that just drops a placeholder file where the encode would have gone, so these tests stay fast
while still exercising render.finish()'s real filter-graph construction (what actually decides
the overlay/audio behaviour)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio import config, hyperframes, media, render
from studio import sfx as sfx_mod
from studio.timeline import Timeline


# ---------------------------------------------------------------- helpers

def _plan(**audio_overrides) -> dict:
    audio = {"clean": False, "normalize": False}
    audio.update(audio_overrides)
    return {"source": {"fps": 30}, "captions": {"style": "clean"}, "graphics": [], "zooms": [],
            "broll": [], "audio": audio}


def _run_finish(monkeypatch, *, cut: Path, plan: dict, tl: Timeline, out_spec: dict, work: Path,
                out_path: Path, graphics: list[dict] | None = None, words: list | None = None):
    """Runs render.finish() with the actual encode stubbed out, returning
    (info, filter_script_text, captured_ffmpeg_args)."""
    captured = {}

    def fake_run_ffmpeg(args, **kwargs):
        captured["args"] = args
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"\x00")

    monkeypatch.setattr(media, "run_ffmpeg", fake_run_ffmpeg)
    work.mkdir(parents=True, exist_ok=True)
    info = render.finish(cut, plan, tl, words or [], out_spec, out_path, work, graphics=graphics)
    script = next(work.glob(f"{out_path.stem}.filter.txt"))
    return info, script.read_text(encoding="utf-8"), captured["args"]


# ---------------------------------------------------------------- zone_for

def test_zone_for_hypercard_tier1_is_full_frame():
    g = {"template": "HyperCard", "props": {"tier": "tier1", "purpose": "section"}}
    assert render.zone_for(g) == {"full"}


def test_zone_for_hypercard_lower_third_is_bottom_left():
    g = {"template": "HyperCard", "props": {"tier": "tier2", "purpose": "lower-third"}}
    assert render.zone_for(g) == {"bottom-left"}


def test_zone_for_hypercard_label_and_definition_are_top_right():
    for purpose in ("label", "definition"):
        g = {"template": "HyperCard", "props": {"tier": "tier2", "purpose": purpose}}
        assert render.zone_for(g) == {"top-right"}


def test_zone_for_hypercard_list_and_equation_are_sides():
    for purpose in ("list", "equation"):
        g = {"template": "HyperCard", "props": {"tier": "tier2", "purpose": purpose}}
        assert render.zone_for(g) == {"sides"}


def test_zone_for_non_hypercard_template_unchanged():
    assert render.zone_for({"template": "LowerThird"}) == {"bottom-left"}
    assert render.zone_for({"template": "SomethingUnknown"}) == {"full"}


# ---------------------------------------------------------------- tier1 skip on vertical

def test_tier1_hypercard_skipped_on_vertical_output_with_note(tmp_path, monkeypatch):
    monkeypatch.setattr(hyperframes, "available", lambda: True)
    monkeypatch.setattr(hyperframes, "render_card", lambda *a, **k: pytest.fail("tier1 must not be rendered for a vertical output"))
    plan = _plan()
    plan["graphics"] = [{"id": "g_hero", "template": "HyperCard", "start": 2.0, "duration": 3.0, "enabled": True,
                         "props": {"card": "x", "tier": "tier1", "purpose": "section", "slots": {}}}]
    tl = Timeline([(0.0, 30.0)])
    notes: list[str] = []
    items = render.graphics_for_output(plan, tl, {"width": 1080, "height": 1920}, tmp_path / "motion", notes=notes)
    assert items == []
    assert notes and "tier1" in notes[0] and "g_hero" in notes[0]


def test_tier2_hypercard_allowed_on_vertical_output(tmp_path, monkeypatch):
    dummy = tmp_path / "card.mov"
    dummy.write_bytes(b"\x00")
    monkeypatch.setattr(hyperframes, "available", lambda: True)
    monkeypatch.setattr(hyperframes, "render_card", lambda *a, **k: dummy)
    plan = _plan()
    plan["graphics"] = [{"id": "g_lt", "template": "HyperCard", "start": 2.0, "duration": 3.0, "enabled": True,
                         "props": {"card": "x", "tier": "tier2", "purpose": "lower-third", "slots": {}}}]
    tl = Timeline([(0.0, 30.0)])
    items = render.graphics_for_output(plan, tl, {"width": 1080, "height": 1920}, tmp_path / "motion")
    assert len(items) == 1
    assert items[0]["path"] == dummy


# ---------------------------------------------------------------- HyperCard dispatch -> overlay in ffmpeg

def test_hypercard_graphic_produces_overlay_input_at_right_edited_time(tmp_path, monkeypatch, sample_video):
    dummy = tmp_path / "dummy_card.mov"
    dummy.write_bytes(b"\x00")
    monkeypatch.setattr(hyperframes, "available", lambda: True)
    monkeypatch.setattr(hyperframes, "render_card", lambda *a, **k: dummy)

    plan = _plan()
    plan["graphics"] = [{"id": "g_card1", "template": "HyperCard", "start": 12.0, "duration": 3.5, "enabled": True,
                         "props": {"card": "kallaway.t2.lower-third.minimal", "tier": "tier2",
                                   "purpose": "lower-third", "slots": {"name": "Jon"}}}]
    # a cut from 5s to 10s: source time 12 lands at edited time 5 + (12 - 10) = 7.0
    tl = Timeline([(0.0, 5.0), (10.0, 50.0)])
    out_spec = {"width": 1920, "height": 1080}
    items = render.graphics_for_output(plan, tl, out_spec, tmp_path / "motion")
    assert len(items) == 1
    assert items[0]["start"] == pytest.approx(7.0)
    assert items[0]["path"] == dummy

    info, script, args = _run_finish(monkeypatch, cut=sample_video, plan=plan, tl=tl, out_spec=out_spec,
                                     work=tmp_path / "work", out_path=tmp_path / "out" / "video.mp4",
                                     graphics=items)
    assert str(dummy) in args or str(dummy).replace("\\", "/") in script
    assert "between(t,7.000," in script
    assert info["notes"] == []  # landscape output: nothing skipped


def test_tier2_lower_third_on_vertical_output_scales_to_width_and_avoids_caption_band(tmp_path, monkeypatch, sample_video):
    dummy = tmp_path / "dummy_card.mov"
    dummy.write_bytes(b"\x00")
    monkeypatch.setattr(hyperframes, "available", lambda: True)
    monkeypatch.setattr(hyperframes, "render_card", lambda *a, **k: dummy)

    plan = _plan()
    plan["graphics"] = [{"id": "g_lt", "template": "HyperCard", "start": 1.0, "duration": 3.0, "enabled": True,
                         "props": {"card": "x", "tier": "tier2", "purpose": "lower-third", "slots": {}}}]
    tl = Timeline([(0.0, 30.0)])
    out_spec = {"width": 1080, "height": 1920}
    items = render.graphics_for_output(plan, tl, out_spec, tmp_path / "motion")
    assert len(items) == 1

    info, script, args = _run_finish(monkeypatch, cut=sample_video, plan=plan, tl=tl, out_spec=out_spec,
                                     work=tmp_path / "work", out_path=tmp_path / "out" / "video.mp4",
                                     graphics=items)
    assert info["notes"] == []
    assert "scale=1080:608" in script  # width-matched, 1920x1080 aspect preserved (1080*1080/1920=607.5 -> 608)
    assert "overlay=x=0:y=" in script


# ---------------------------------------------------------------- sfx_events

def test_sfx_events_one_punch_zoom_gives_one_whoosh_at_minus_6db(isolated_home):
    sfx_mod.generate()
    zooms = [{"id": "z1", "kind": "punch", "start": 3.2, "end": 3.6, "enabled": True}]
    events = render.sfx_events([], zooms)
    assert len(events) == 1
    assert events[0]["category"] == "whoosh"
    assert events[0]["gain_db"] == -6.0
    assert events[0]["t"] == pytest.approx(3.2)


def test_sfx_events_two_lower_thirds_use_different_files(isolated_home):
    sfx_mod.generate()
    g1 = {"id": "g_lower2", "template": "LowerThird", "start": 1.0, "duration": 4.0, "enabled": True}
    g2 = {"id": "g_lower3", "template": "LowerThird", "start": 10.0, "duration": 4.0, "enabled": True}
    events = render.sfx_events([g1, g2], [])
    entrances = [e for e in events if e["gain_db"] == 0.0]
    assert len(entrances) == 2
    assert entrances[0]["file"] != entrances[1]["file"]


def test_sfx_events_never_picks_a_banned_category(isolated_home):
    sfx_mod.generate()
    sfx_dir = config.DATA_HOME / "sfx"
    manifest_path = sfx_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for cat in ("riser", "laser", "zap"):
        fname = f"{cat}_01.wav"
        (sfx_dir / fname).write_bytes(b"\x00")
        data.append({"file": fname, "category": cat, "lufs": -14.0})
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    for cat in ("riser", "laser", "zap"):
        assert render._sfx_candidates(cat) == []

    graphics = [
        {"id": "g1", "template": "HyperCard", "start": 0.0, "duration": 3.0, "enabled": True,
         "props": {"tier": "tier1", "purpose": "section"}},
        {"id": "g2", "template": "LowerThird", "start": 5.0, "duration": 3.0, "enabled": True},
        {"id": "g3", "template": "EndCard", "start": 20.0, "duration": 4.0, "enabled": True},
    ]
    zooms = [{"id": "z1", "kind": "punch", "start": 2.0, "end": 2.4, "enabled": True}]
    events = render.sfx_events(graphics, zooms)
    assert events  # sanity: something was actually produced
    for ev in events:
        assert ev["category"] not in ("riser", "laser", "zap")
        assert not any(b in ev["file"].lower() for b in ("riser", "laser", "zap"))


def test_sfx_events_disabled_graphic_or_zoom_gives_no_events(isolated_home):
    sfx_mod.generate()
    g = {"id": "g1", "template": "LowerThird", "start": 1.0, "duration": 2.0, "enabled": False}
    assert render.sfx_events([g], []) == []
    z = {"id": "z1", "kind": "punch", "start": 1.0, "end": 1.4, "enabled": False}
    assert render.sfx_events([], [z]) == []


# ---------------------------------------------------------------- music bed: gain, ramp, duck

def test_music_filter_has_default_gain_ramp_and_sidechain(tmp_path, monkeypatch, sample_video):
    music_file = tmp_path / "bed.wav"
    music_file.write_bytes(b"\x00")
    plan = _plan(music={"path": str(music_file), "lufs": -14.0})  # bed_db omitted -> default -11
    tl = Timeline([(0.0, 50.0)])
    out_spec = {"width": 1920, "height": 1080}

    info, script, args = _run_finish(monkeypatch, cut=sample_video, plan=plan, tl=tl, out_spec=out_spec,
                                     work=tmp_path / "work", out_path=tmp_path / "out" / "video.mp4",
                                     graphics=[])
    # target(-14 default) + bed_db(-11 default) - lufs(-14) == -11.00 dB
    assert "volume=-11.00dB" in script
    assert "0.5+0.5*t/1.5" in script
    assert "sidechaincompress" in script


def test_music_only_present_when_plan_has_music(tmp_path, monkeypatch, sample_video):
    plan = _plan()  # no audio.music
    tl = Timeline([(0.0, 50.0)])
    out_spec = {"width": 1920, "height": 1080}
    info, script, args = _run_finish(monkeypatch, cut=sample_video, plan=plan, tl=tl, out_spec=out_spec,
                                     work=tmp_path / "work", out_path=tmp_path / "out" / "video.mp4",
                                     graphics=[])
    assert "sidechaincompress" not in script
    assert "0.5+0.5*t/1.5" not in script


# ---------------------------------------------------------------- mastering: no afade on voice

def test_audio_chain_never_fades_the_voice(sample_video):
    achain = render.audio_chain({"clean": True, "normalize": False}, sample_video)
    assert "afade" not in achain


def test_audio_chain_adds_limiter_after_loudnorm(sample_video):
    achain = render.audio_chain({"clean": False, "normalize": True, "target_lufs": -14}, sample_video)
    assert "loudnorm" in achain
    assert "alimiter=limit=0.84" in achain
    assert "afade" not in achain


# ---------------------------------------------------------------- final-file loudness report (warning only)

def test_measure_final_loudness_ok_flag(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            stderr = '{"input_i" : "-14.0", "input_tp" : "-1.6"}'
            returncode = 0
        return R()
    monkeypatch.setattr(render.subprocess, "run", fake_run)
    loud = render.measure_final_loudness(tmp_path / "whatever.mp4")
    assert loud == {"lufs": -14.0, "tp": -1.6, "ok": True}


def test_measure_final_loudness_flags_out_of_range(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            stderr = '{"input_i" : "-20.0", "input_tp" : "-1.6"}'
            returncode = 0
        return R()
    monkeypatch.setattr(render.subprocess, "run", fake_run)
    loud = render.measure_final_loudness(tmp_path / "whatever.mp4")
    assert loud["ok"] is False


def test_verify_report_includes_loudness_without_changing_checks(monkeypatch, sample_video):
    import subprocess as real_subprocess
    real_run = real_subprocess.run

    def fake_run(cmd, **kwargs):
        # only the loudnorm measurement pass is faked; ffprobe/decode/silencedetect calls
        # (also made through this same `subprocess` module, e.g. by media.probe) go through.
        if isinstance(cmd, list) and any("loudnorm=print_format=json" in str(c) for c in cmd):
            class R:
                stderr = '{"input_i" : "-14.0", "input_tp" : "-1.6"}'
                returncode = 0
            return R()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    info = media.probe(sample_video)
    report = render.verify(sample_video, expect_w=info.width, expect_h=info.height, full_decode=False)
    assert "loudness" in report
    assert "loudness" not in report["checks"]
    assert report["loudness"]["ok"] is True


def test_map_faces_into_vertical_crop():
    """Faces are tracked in the 16:9 source; the mouth check needs them where the viewer sees them."""
    from studio import render
    face = {"t": 1.0, "cx": 0.5, "cy": 0.5, "w": 0.1, "h": 0.2}
    # 1080-wide crop of a 1920x1080 source starting at x=420 (face centred), shown 1080x1920 full height
    out = render._map_faces([face], [(0.0, 420.0)], 1080, 1920, 1080, 1080, 1920)[0]
    assert abs(out["cx"] - 0.5) < 1e-6 and abs(out["cy"] - 0.5) < 1e-6
    assert abs(out["w"] - 0.1 * 1920 / 1080) < 1e-6
    # zoomed-out vertical: the picture is a band 1350 px tall placed 228 px down
    out2 = render._map_faces([face], [(0.0, 420.0)], 1080, 1920, 1080, 1080, 1920, fg_h=1350, top=228)[0]
    assert abs(out2["cy"] - (228 + 0.5 * 1350) / 1920) < 1e-6
    assert abs(out2["h"] - 0.2 * 1350 / 1920) < 1e-6
