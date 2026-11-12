"""The editing plan: a reviewable, editable JSON document that drives every render.

Flow: build (draft) -> review/revise -> approve -> preview render -> final render.
Revisions modify this plan in place (versioned), so a change like "make the captions
smaller" re-renders from the existing project instead of starting over."""
from __future__ import annotations

import copy
import json
import re
import time
from collections import Counter
from pathlib import Path

from . import analyze as an
from . import captions
from .timeline import Timeline, keep_segments, pad_cut_starts

STOPWORDS = set("""a an the and or but so to of in on for with at by from is are was were be been it this that
these those i you we they he she my your our their me us them not no yes do does did have has had will
would can could should just very really going gonna get got im i'm it's dont don't let's lets about
into out up down over then than there here what when where which who how why all any each every more most
some such only own same too also one two three first second third step thing things like know mean okay
right now today want show"""
                .split())

CAPTION_STYLES = {
    "clean_shadow": {"font": "Outfit SemiBold", "size": 58, "primary": "#FFFFFF", "highlight": None, "outline": 0,
                     "shadow": 3, "box": False, "uppercase": False, "max_words": 7, "lines": 2, "animation": "fade",
                     "desc": "Clean white sentence captions with a soft shadow, no box (talking-head favourite)"},
    "punch": {"font": "Outfit ExtraBold", "size": 84, "primary": "#FFFFFF", "highlight": "brand", "outline": 7,
              "shadow": 2, "box": False, "uppercase": True, "max_words": 3, "lines": 1, "animation": "pop",
              "desc": "Punchy 2-3 word captions with brand-color keyword, Hormozi-style energy"},
    "premium": {"font": "Outfit Bold", "size": 50, "primary": "#FFFFFF", "highlight": "brand", "outline": 0,
                "shadow": 0, "box": "rounded", "box_color": "brand", "box_opacity": 0.82, "uppercase": False,
                "max_words": 6, "lines": 1, "animation": "highlight",
                "desc": "Premium: one clean line on a rounded brand panel, spoken word highlighted"},
    "clean": {"font": "Montserrat ExtraBold", "size": 64, "primary": "#FFFFFF", "highlight": None,
              "outline": 4, "shadow": 2, "box": False, "uppercase": False, "max_words": 7, "lines": 2,
              "animation": "fade", "desc": "Clean sentence captions for educational videos"},
    "minimal": {"font": "Inter", "size": 54, "primary": "#FFFFFF", "highlight": None, "outline": 0,
                "shadow": 0, "box": True, "uppercase": False, "max_words": 8, "lines": 2,
                "animation": "none", "desc": "Small boxed captions that stay out of the way"},
    "karaoke": {"font": "Montserrat ExtraBold", "size": 72, "primary": "#FFFFFF", "highlight": "brand",
                "outline": 5, "shadow": 3, "box": False, "uppercase": True, "max_words": 4, "lines": 2,
                "animation": "highlight", "desc": "Word-by-word highlight, great for Shorts"},
    "bold": {"font": "Montserrat ExtraBold", "size": 92, "primary": "#FFFFFF", "highlight": "brand",
             "outline": 6, "shadow": 4, "box": False, "uppercase": True, "max_words": 3, "lines": 1,
             "animation": "pop", "desc": "Big punchy pop-in words for high-energy Shorts"},
}

# PLAYBOOK_STYLE is added to captions.py by a parallel task; guard the lookup so plan.py still
# imports (and every other caption style still works) if that landed after this module did.
_playbook_style = getattr(captions, "PLAYBOOK_STYLE", None)
if _playbook_style:
    CAPTION_STYLES["playbook"] = dict(_playbook_style)

# HyperFrames card types a plain-English "add a ... card saying ..." request can name, and
# the (tier, purpose) each one maps to (see hyperframes.py cards()/pick_card()).
CARD_TYPE_PURPOSE = {
    "lower third": ("tier2", "lower-third"),
    "label": ("tier2", "label"),
    "list": ("tier2", "list"),
    "definition": ("tier2", "definition"),
    "section": ("tier1", "section"),
    "stat": ("tier1", "stat"),
    "quote": ("tier1", "quote"),
}

PLATFORM_OUTPUTS = {
    "youtube": {"aspect": "16:9", "width": 1920, "height": 1080},
    "youtube_4k": {"aspect": "16:9", "width": 3840, "height": 2160},
    "shorts": {"aspect": "9:16", "width": 1080, "height": 1920},
    "tiktok": {"aspect": "9:16", "width": 1080, "height": 1920},
    "reels": {"aspect": "9:16", "width": 1080, "height": 1920},
    "square": {"aspect": "1:1", "width": 1080, "height": 1080},
    "linkedin": {"aspect": "1:1", "width": 1080, "height": 1080},
}


def topic_keywords(words: list[dict], n: int = 6) -> list[str]:
    toks = [an.norm(w["word"]) for w in words]
    toks = [t for t in toks if t and t not in STOPWORDS and len(t) > 2 and not t.isdigit()]
    bigrams = Counter(f"{a} {b}" for a, b in zip(toks, toks[1:]))
    uni = Counter(toks)
    out: list[str] = []
    used: set[str] = set()
    for b, c in bigrams.most_common(n * 3):
        a, z = b.split()
        if c > 1 and a != z and a not in used and z not in used:
            out.append(b)
            used.update((a, z))
    out += [u for u, _ in uni.most_common(n * 2) if u not in used]
    return out[:n]


def _brand_music(brand: dict, mood: str | None = None, seed: str = "") -> dict | None:
    """Pick a licensed bed track for `mood` from the music library (studio/music.py).
    Music is opt-in: this is only called with a mood when the caller has already decided
    the brand wants music (options["music_mood"] was given, or the brand enables it) - a
    brand with music disabled and no explicit mood never reaches here with a mood at all,
    so it never gets a track. bed_db is how far under the voice the bed sits; the playbook
    default is -11 dB, overridable per brand (brand.json music.bed_db, or the older
    music.volume_db field render.py's audio_chain predates)."""
    if not mood:
        return None
    from . import music as music_mod
    track = music_mod.pick(mood, seed=seed)
    if not track:
        return None
    m = brand.get("music") or {}
    bed_db = float(m.get("bed_db", m.get("volume_db", -11)))
    return {"path": track["path"], "bed_db": bed_db, "volume_db": bed_db,
            "lufs": track.get("lufs"), "mood": mood, "title": track.get("title")}


def _infer_music_mood(category: str, topic: str) -> str:
    """"claims/news/results" -> confident; "how-to/method/tutorial" -> chill. Anything else
    still gets a mood (confident) because this is only called once the brand has already
    opted into music; it just has no specific cue to go on."""
    text = f"{category} {topic}".lower()
    if any(k in text for k in ("how-to", "how to", "method", "tutorial")):
        return "chill"
    if any(k in text for k in ("claim", "news", "result")):
        return "confident"
    return "confident"


def _resolve_music_mood(options: dict, brand: dict, category: str, topic: str) -> str | None:
    """None means "don't turn music on": no explicit request, and the brand hasn't opted
    in either. An explicit options["music_mood"] always wins, even for a brand that has
    music disabled - asking for music is the opt-in."""
    explicit = options.get("music_mood")
    if explicit:
        return explicit
    if not (brand.get("music") or {}).get("enabled"):
        return None
    return _infer_music_mood(category, topic)


def default_zooms(analysis: dict, vtype: str, mode: str) -> list[dict]:
    if vtype == "tutorial" and mode == "longform":
        return []  # keep screen content readable; add zooms by revision
    zooms, n = [], 0
    every = 2 if mode != "longform" else 3
    for k, s in enumerate(analysis["sentences"]):
        if s["end"] - s["start"] < 1.5:
            continue
        hooky = an.score_hook({"tokens": [an.norm(t) for t in s["text"].split()], "text": s["text"]}, 0.5) >= 3
        if k % every == 0 or hooky:
            n += 1
            zooms.append({"id": f"z{n}", "start": round(s["start"], 3), "end": round(s["end"], 3),
                          "scale": 1.15 if mode != "longform" else 1.10,
                          "kind": "punch" if mode != "longform" else "ease", "enabled": True,
                          "reason": "Emphasis" if hooky else "Pacing variety"})
    return zooms


def _zooms_for_layout(zooms: list[dict], src: dict) -> list[dict]:
    """Screen + camera layouts: punch-ins would crop the screen, so keep only the zooms that
    fall where the camera is full-screen."""
    if src.get("layout") != "screencam":
        return zooms
    rs = src.get("cam_ranges") or []
    return [z for z in zooms if any(a <= z["start"] and z["end"] <= b for a, b in rs)]


def default_graphics(analysis: dict, brand: dict, title: str, mode: str) -> list[dict]:
    g = []
    if brand.get("intro_style") == "title" and mode == "longform":
        g.append({"id": "g_title", "template": "KineticTitle", "start": 0.0, "duration": 3.0,
                  "props": {"text": title.upper()}, "placement": "overlay", "enabled": True})
    lt = brand.get("lower_third", {})
    bad = [c for c in analysis.get("cuts", []) if c["type"] in ("retake", "restart", "repeat", "false_start", "dead_air")]
    kept = [s for s in analysis["sentences"] if not an._inside(s, bad)] or analysis["sentences"]
    if lt.get("name") and mode == "longform" and kept:
        s = kept[min(1, len(kept) - 1)]  # on the second kept sentence, never on a removed take
        g.append({"id": "g_lower", "template": "LowerThird", "start": s["start"], "duration": 4.5,
                  "props": {"name": lt["name"], "title": lt.get("title", "")}, "placement": "overlay",
                  "enabled": True})
    if mode == "longform":
        for i, ch in enumerate(analysis["chapters"][1:], start=1):
            g.append({"id": f"g_ch{i}", "template": "ChapterCard", "start": ch["start"], "duration": 2.5,
                      "props": {"number": i, "title": ch["title"]}, "placement": "overlay", "enabled": True})
    rec = brand.get("recurring", {})
    sents = analysis["sentences"]
    if rec.get("outro", {}).get("enabled") and sents:
        end_t = sents[-1]["end"]
        d = float(rec["outro"].get("duration", 4.5))
        g.append({"id": "g_outro", "template": rec["outro"].get("template", "EndCard"), "start": round(max(0, end_t - d + 0.6), 2),
                  "duration": d, "props": {"text": brand.get("cta", {}).get("text") or "Learn more",
                                           "url": brand.get("cta", {}).get("url", ""), "tagline": brand.get("tagline", "")},
                  "placement": "overlay", "enabled": True})
        return g  # the end card carries the call to action
    for i, cta in enumerate(analysis["cta"][-1:]):
        text = brand.get("cta", {}).get("text") or cta["text"]
        g.append({"id": f"g_cta{i + 1}", "template": "CallToAction", "start": cta["start"],
                  "duration": round(max(3.0, min(6.0, cta["end"] - cta["start"] + 1.5)), 1),
                  "props": {"text": _short(text, 8), "url": brand.get("cta", {}).get("url", "")},
                  "placement": "overlay", "enabled": True})
    return g


def _short(text: str, n: int) -> str:
    w = text.split()
    return " ".join(w[:n]) + ("..." if len(w) > n else "")


def build(project: dict, transcript: dict, *, brand: dict, mode: str = "longform",
          outputs: list[str] | None = None, options: dict | None = None) -> dict:
    options = options or {}
    pace = options.get("pace") or ("shorts" if mode == "shorts" else brand.get("pace", "natural"))
    analysis = an.analyze(transcript, pace=pace, aggressive_fillers=options.get("aggressive_fillers", False),
                          duration=project["source"]["duration"], filler_guard=True)
    vtype = options.get("video_type") or analysis["classification"]["type"]
    words = transcript["words"]
    keywords = topic_keywords(words)
    hooks = analysis["hooks"]
    best = hooks[0] if hooks else None
    style_name = options.get("caption_style") or brand.get("caption_style") or (
        "karaoke" if mode != "longform" else "clean")
    cap = copy.deepcopy(CAPTION_STYLES.get(style_name, CAPTION_STYLES["clean"]))
    cap.update({"style": style_name, "enabled": options.get("captions", True),
                "position": brand.get("caption", {}).get("position", "auto"),
                "size_scale": brand.get("caption", {}).get("size", 1.0),
                "highlight": brand["colors"]["highlight"] if cap.get("highlight") == "brand" else cap.get("highlight"),
                "box_color": (brand["colors"].get("navy") or brand["colors"].get("background", "#0F1E4A"))
                if cap.get("box_color") == "brand" else cap.get("box_color"),
                "font": brand.get("fonts", {}).get("captions") or cap["font"]})
    title_guess = " ".join(k.title() for k in keywords[:3]) or "Untitled"
    topic = options.get("topic") or title_guess
    music_mood = _resolve_music_mood(options, brand, vtype, topic)
    music = _brand_music(brand, mood=music_mood, seed=project["id"])
    src = project["source"]
    plan = {
        "schema": "vibe-studio.plan/v1",
        "project_id": project["id"],
        "mode": mode,
        "status": "draft",
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "brand": brand.get("slug", "default"),
        "source": {k: src.get(k) for k in ("path", "duration", "width", "height", "fps", "vertical_path", "layout", "cam_ranges")
                   if k in src},
        "summary": {
            "video_type": vtype,
            "topic": topic,
            "keywords": keywords,
            "audience": brand.get("audience") or "",
            "suggested_hook": best,
            "alternative_hooks": hooks[1:],
            "intro_suggestions": intro_suggestions(analysis, best),
            "editor_notes": [],
        },
        "hook": {"cold_open": bool(options.get("cold_open", brand.get("intro_style") == "cold_open")),
                 "start": best["start"] if best else None, "end": best["end"] if best else None},
        "cuts": analysis["cuts"],
        "keep_overrides": [],
        "chapters": analysis["chapters"],
        "zooms": _zooms_for_layout(default_zooms(analysis, vtype, mode), src) if options.get("zooms", True) else [],
        "captions": cap,
        "graphics": default_graphics(analysis, brand, title_guess, mode) if options.get("graphics", True) else [],
        "broll": [],
        "reframe": {"mode": "auto", "vertical_zoom": brand.get("recurring", {}).get("vertical_zoom", "medium")},
        "logo_bug": dict(brand.get("recurring", {}).get("logo_bug") or {"enabled": False}),  # auto | largest | split | center (vertical/square crops)
        "audio": {"clean": True, "denoise": options.get("denoise") or brand.get("denoise") or "studio", "normalize": True, "target_lufs": -14.0,
                  "music": music,
                  "sfx": {"enabled": bool(brand.get("recurring", {}).get("sound_effects")), "level_db": -18}},
        "outputs": [dict(PLATFORM_OUTPUTS[o], name=o) for o in (outputs or (
            ["youtube"] if mode == "longform" else ["shorts"]))],
        "sentences": analysis["sentences"],
        "revisions": [],
        "cut_pad": 0.06,
        "filler_guard": True,
        # New plans default to the playbook Shorts pace; plans already on disk keep their own
        # (pipeline.render_shorts falls back to "shorts" when this key is missing entirely).
        "shorts_settings": {"pace": "playbook"},
    }
    if music_mood and not music:
        plan["summary"]["editor_notes"].append(
            f"No music track matched mood '{music_mood}' in ~/VibeStudio/music")
    plan["stats"] = stats(plan)
    return plan


def intro_suggestions(analysis: dict, best: dict | None) -> list[str]:
    tips = []
    sents = analysis["sentences"]
    if best and sents and best["start"] > sents[0]["start"] + 0.5:
        tips.append(f'Open with your strongest line ({fmt_time(best["start"])}): "{best["text"]}". '
                    "Enable hook.cold_open to tease it before the intro.")
    if sents:
        first = sents[0]["text"].lower()
        if re.match(r"^(hey|hi|hello|what'?s up|welcome)", first):
            tips.append("The video opens with a greeting. Viewers decide in the first seconds; lead with the payoff, greet after.")
        if sents[0]["end"] - sents[0]["start"] > 12:
            tips.append("The first sentence is long. Consider a shorter, punchier opening line.")
    if not tips:
        tips.append("The opening already leads with a strong statement.")
    return tips


def timeline(plan: dict) -> Timeline:
    fps = plan["source"].get("fps") or 30.0
    cuts = [c for c in plan["cuts"] if c.get("enabled", True)]
    # keep overrides restore ranges the user wants to keep
    for k in plan.get("keep_overrides", []):
        cuts = _subtract(cuts, k["start"], k["end"])
    if plan.get("cut_pad"):
        cuts = pad_cut_starts(cuts, plan["cut_pad"])
    segs = keep_segments(plan["source"]["duration"], cuts, fps=fps)
    if plan["hook"].get("cold_open") and plan["hook"].get("start") is not None:
        segs = [(plan["hook"]["start"], plan["hook"]["end"] + 0.25)] + segs
    return Timeline(segs)


def _subtract(cuts: list[dict], s: float, e: float) -> list[dict]:
    out = []
    for c in cuts:
        if c["end"] <= s or c["start"] >= e:
            out.append(c)
            continue
        if c["start"] < s:
            out.append({**c, "end": s})
        if c["end"] > e:
            out.append({**c, "start": e})
    return out


def stats(plan: dict) -> dict:
    tl = timeline(plan)
    src = plan["source"]["duration"]
    by_type = Counter(c["type"] for c in plan["cuts"] if c.get("enabled", True))
    return {"source_duration": round(src, 2), "edited_duration": round(tl.duration, 2),
            "removed_seconds": round(src - tl.duration, 2), "segments": len(tl.segments),
            "cuts_by_type": dict(by_type)}


def fmt_time(t: float | None) -> str:
    if t is None:
        return "-"
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def to_markdown(plan: dict) -> str:
    s, st = plan["summary"], stats(plan)
    lines = [f"# Editing plan - {s['topic']}", "",
             f"**Status:** {plan['status']} (version {plan['version']})  |  **Mode:** {plan['mode']}  |  "
             f"**Brand:** {plan['brand']}", "",
             "## Overview",
             f"- Duration: {fmt_time(st['source_duration'])} -> about {fmt_time(st['edited_duration'])} "
             f"({st['removed_seconds']:.1f}s removed in {sum(st['cuts_by_type'].values())} cuts)",
             f"- Video type: {s['video_type']}",
             f"- Main topic: {s['topic']}  (keywords: {', '.join(s['keywords'])})",
             f"- Target audience: {s['audience'] or 'not set - add it to the brand profile'}"]
    if s.get("suggested_hook"):
        h = s["suggested_hook"]
        lines += [f"- Suggested hook ({fmt_time(h['start'])}): \"{h['text']}\""]
    lines += ["", "## Introduction"] + [f"- {t}" for t in s["intro_suggestions"]]
    lines += ["", "## Mistakes and dead air to remove", "", "| ID | From | To | Type | What | On |",
              "|---|---|---|---|---|---|"]
    for c in plan["cuts"]:
        what = (c.get("text") or c["reason"]).replace("|", "/")
        lines.append(f"| {c['id']} | {fmt_time(c['start'])} | {fmt_time(c['end'])} | {c['type']} | "
                     f"{what[:70]} | {'yes' if c.get('enabled', True) else 'no (review)'} |")
    lines += ["", "## Sections kept", ""]
    tl = timeline(plan)
    for i, (a, b) in enumerate(tl.segments[:60]):
        lines.append(f"- {fmt_time(a)} - {fmt_time(b)}")
    if len(tl.segments) > 60:
        lines.append(f"- ... {len(tl.segments) - 60} more")
    if plan["mode"] == "longform" and plan["chapters"]:
        lines += ["", "## Chapters (edited timeline)", ""]
        for ch in plan["chapters"]:
            lines.append(f"- {fmt_time(tl.to_edit_nearest(ch['start']))} {ch['title']}")
    lines += ["", "## Visuals", "", f"- Zooms: {sum(z['enabled'] for z in plan['zooms'])} "
              f"({', '.join(z['id'] + '@' + fmt_time(z['start']) for z in plan['zooms'][:12])})"]
    for g in plan["graphics"]:
        lines.append(f"- {g['id']}: {g['template']} at {fmt_time(g['start'])} for {g['duration']}s "
                     f"{json.dumps(g['props'])}{'' if g.get('enabled', True) else ' (off)'}")
    lines.append(f"- B-roll: {len(plan['broll'])} approved clips" if plan["broll"]
                 else "- B-roll: none (add approved clips to ~/VibeStudio/broll)")
    c = plan["captions"]
    lines += ["", "## Captions", f"- Style: {c['style']} - {c.get('desc', '')}; font {c['font']}, "
              f"size x{c.get('size_scale', 1)}, position {c['position']}, {'on' if c['enabled'] else 'off'}"]
    a = plan["audio"]
    music_line = ("- Music: none" if not a.get("music") else
                  f"- Music: {a['music'].get('title') or Path(a['music']['path']).name} at "
                  f"{a['music'].get('bed_db', a['music'].get('volume_db', -11))} dB under the voice, with ducking")
    lines += ["", "## Audio", f"- Clean-up: {'high-pass + ' + a['denoise'] + ' noise reduction' if a['clean'] else 'off'}",
              f"- Loudness: {a['target_lufs']} LUFS" if a["normalize"] else "- Loudness: unchanged",
              music_line,
              f"- Caption style: {c['style']}",
              f"- Shorts pace: {plan.get('shorts_settings', {}).get('pace', 'shorts')}"]
    if plan.get("clips"):
        lines += ["", "## Shorts", "", "| # | From | To | Length | Score | Hook |", "|---|---|---|---|---|---|"]
        for i, cl in enumerate(plan["clips"], 1):
            lines.append(f"| {i} | {fmt_time(cl['start'])} | {fmt_time(cl['end'])} | {cl['end'] - cl['start']:.0f}s | "
                         f"{cl['total']:.1f} | {cl['hook'][:60]} |")
        lines.append("\nScores are editorial judgements (hook, value, clarity, relevance, stand-alone, "
                     "retention, CTA), not performance predictions.")
    lines += ["", "## Outputs", ""] + [f"- {o['name']}: {o['width']}x{o['height']} ({o['aspect']})"
                                       for o in plan["outputs"]]
    if plan["summary"].get("editor_notes"):
        lines += ["", "## Editor notes"] + [f"- {n}" for n in plan["summary"]["editor_notes"]]
    lines += ["", "---", "Approve with `python -m studio approve <project>` or ask Claude to change anything."]
    return "\n".join(lines)


# ---------------------------------------------------------------- revisions

def set_path(plan: dict, path: str, value) -> None:
    keys = path.split(".")
    node = plan
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node.setdefault(k, {})
    last = keys[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def find_item(plan: dict, item_id: str) -> tuple[str, dict] | None:
    for coll in ("cuts", "zooms", "graphics", "broll", "clips"):
        for it in plan.get(coll, []) or []:
            if it.get("id") == item_id:
                return coll, it
    return None


def revise(plan: dict, ops: list[dict], request: str = "") -> dict:
    """Apply structured revision ops. Supported ops:
      {"op":"set","path":"captions.size_scale","value":0.8}
      {"op":"toggle","id":"z3","enabled":false}
      {"op":"keep","start":12.0,"end":20.0}        restore a range (undo cuts)
      {"op":"cut","start":30.0,"end":34.5,"reason":"..."}
      {"op":"add_graphic","template":"KineticTitle","start":2.0,"duration":3,"props":{...},"placement":"behind"}
      {"op":"add_zoom","start":5,"end":8,"scale":1.15}
      {"op":"add_card","tier":"tier2","purpose":"lower-third","text":"Jonathan Blake","start":4.0}
      {"op":"remove","id":"g_cta1"}
      {"op":"props","id":"g_user4","value":{"layout":"sides"}}   merge graphic props by id
      {"op":"note","text":"..."}"""
    plan = copy.deepcopy(plan)
    applied = []
    for op in ops:
        kind = op["op"]
        if kind == "set":
            set_path(plan, op["path"], op["value"])
        elif kind == "toggle":
            hit = find_item(plan, op["id"])
            if not hit:
                raise KeyError(f"No plan item with id {op['id']}")
            hit[1]["enabled"] = bool(op.get("enabled", not hit[1].get("enabled", True)))
        elif kind == "keep":
            plan["keep_overrides"].append({"start": float(op["start"]), "end": float(op["end"])})
        elif kind == "cut":
            n = _next_num(plan["cuts"], "c")
            plan["cuts"].append({"id": f"c{n}u", "start": float(op["start"]), "end": float(op["end"]),
                                 "type": "manual", "reason": op.get("reason", "Requested cut"),
                                 "confidence": 1.0, "enabled": True})
            plan["cuts"].sort(key=lambda c: c["start"])
        elif kind == "add_graphic":
            n = _next_num(plan["graphics"], "g_user")
            plan["graphics"].append({"id": f"g_user{n}", "template": op["template"], "start": float(op["start"]),
                                     "duration": float(op.get("duration", 3)), "props": op.get("props", {}),
                                     "placement": op.get("placement", "overlay"), "enabled": True})
        elif kind == "add_zoom":
            n = _next_num(plan["zooms"], "z")
            plan["zooms"].append({"id": f"z{n}u", "start": float(op["start"]), "end": float(op["end"]),
                                  "scale": float(op.get("scale", 1.15)), "kind": op.get("kind", "punch"),
                                  "enabled": True, "reason": "Requested"})
        elif kind == "add_card":
            from . import hyperframes as hf
            card = hf.pick_card(op["tier"], op["purpose"], seed=plan.get("project_id", ""))
            if not card:
                plan["summary"]["editor_notes"].append(
                    f"No HyperFrames card found for {op['purpose']} ({op['tier']}); card not added.")
            else:
                slot_names = [s["name"] for s in card["slots"]]
                slots = {slot_names[0]: op["text"]} if slot_names else {}
                if op["purpose"] == "lower-third" and len(slot_names) > 1:
                    title = _brand_lower_third(plan).get("title")
                    if title:
                        slots[slot_names[1]] = title
                lo, hi = card.get("duration_range", (None, None))
                duration = round(((lo or 3.0) + (hi or lo or 3.0)) / 2, 2) if (lo or hi) else 3.5
                n = _next_num(plan["graphics"], "g_card")
                plan["graphics"].append({"id": f"g_card{n}", "template": "HyperCard", "start": float(op["start"]),
                                         "duration": duration,
                                         "props": {"card": card["id"], "tier": op["tier"], "purpose": op["purpose"],
                                                   "slots": slots},
                                         "placement": "overlay", "enabled": True})
                for w in hf.check_slot_text(slots, _plan_transcript_text(plan)):
                    plan["summary"]["editor_notes"].append(f"{card['id']}: {w} - never invent numbers, check the source.")
        elif kind == "pace":  # rebuild every pause cut at a new pace (keeps all other cuts and choices)
            pace_rules = {"relaxed": (1.2, 0.6), "natural": (0.8, 0.4), "tight": (0.5, 0.22), "snappy": (0.35, 0.15),
                         "playbook": (0.2, 0.15)}
            max_p, keep_p = pace_rules.get(op["value"], pace_rules["tight"])
            words = op.get("_words") or []
            plan["cuts"] = [c for c in plan["cuts"] if c["type"] != "pause"]
            n0 = _next_num(plan["cuts"], "c")
            for k, c in enumerate(an.find_pauses(words, max_pause=max_p, keep_pause=keep_p)):
                plan["cuts"].append({**c, "id": f"c{n0 + k}p", "enabled": True})
            plan["cuts"].sort(key=lambda c: c["start"])
            plan["pace"] = op["value"]
            op = {k: v for k, v in op.items() if k != "_words"}
        elif kind == "props":  # merge props into one item by id (safe even after removals)
            hit = find_item(plan, op["id"])
            if not hit:
                raise KeyError(f"No plan item with id {op['id']}")
            hit[1].setdefault("props", {}).update(op["value"])
        elif kind == "remove":
            hit = find_item(plan, op["id"])
            if hit:
                plan[hit[0]].remove(hit[1])
        elif kind == "note":
            plan["summary"]["editor_notes"].append(op["text"])
        else:
            raise ValueError(f"Unknown revision op: {kind}")
        applied.append(op)
    plan["version"] += 1
    if plan["status"] in ("approved", "rendered"):
        plan["status"] = "revised"
    plan["revisions"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "request": request, "ops": applied})
    plan["stats"] = stats(plan)
    return plan


def _brand_colors(plan: dict) -> dict:
    from . import brand as brand_mod
    try:
        return brand_mod.load(plan.get("brand") if plan.get("brand") not in (None, "default") else None)["colors"]
    except FileNotFoundError:
        return {}


def _brand_lower_third(plan: dict) -> dict:
    from . import brand as brand_mod
    try:
        br = brand_mod.load(plan.get("brand") if plan.get("brand") not in (None, "default") else None)
    except FileNotFoundError:
        return {}
    return br.get("lower_third") or {}


def _quoted_time(plan: dict, quote: str, at: float | None) -> float:
    """When a plain-English request quotes words for a card, time it to the moment those
    words are actually spoken if they're in the transcript; otherwise fall back to the
    current playhead, then the first sentence."""
    ql = quote.lower()
    hit = next((s for s in plan.get("sentences") or [] if ql in s.get("text", "").lower()), None)
    if hit:
        return hit["start"]
    if at is not None:
        return at
    sents = plan.get("sentences") or []
    return sents[0]["start"] if sents else 0.0


def _plan_transcript_text(plan: dict) -> str:
    """The closest thing to "the transcript" a plan carries on its own (sentence text with
    timing, no word-level corrections) - enough for check_slot_text's loose number matching."""
    return " ".join(s.get("text", "") for s in plan.get("sentences") or [])


def _next_num(items: list[dict], prefix: str) -> int:
    """Next free number for ids like g_user3 / c12u, so ids never repeat after removals."""
    import re as _re
    nums = [int(m.group(1)) for it in items if (m := _re.match(rf"{prefix}(\d+)", it.get("id", "")))]
    return max(nums, default=0) + 1


def parse_request(plan: dict, text: str, at: float | None = None) -> list[dict]:
    """Turn common plain-English revision requests into ops. Anything not understood
    returns [] so Claude (or the user) can express it as explicit ops instead."""
    t = text.lower().strip()
    ops: list[dict] = []
    scale = plan["captions"].get("size_scale", 1.0)
    if "caption" in t and any(w in t for w in ("smaller", "too big", "shrink")):
        ops.append({"op": "set", "path": "captions.size_scale", "value": round(scale * 0.8, 2)})
    elif "caption" in t and any(w in t for w in ("bigger", "larger", "too small")):
        ops.append({"op": "set", "path": "captions.size_scale", "value": round(scale * 1.25, 2)})
    elif "caption" in t and any(w in t for w in ("off", "remove", "no captions")):
        ops.append({"op": "set", "path": "captions.enabled", "value": False})
    aliases = {"hormozi": "punch", "punchy": "punch", "premium": "premium", "shadow": "clean_shadow", "boxed": "minimal"}
    for word, style in aliases.items():
        if f"{word} caption" in t or f"captions {word}" in t:
            t = t + f" {style} caption"
    for style in CAPTION_STYLES:
        if f"{style.replace('_', ' ')} caption" in t or f"{style} caption" in t or f"captions {style}" in t:
            colors = _brand_colors(plan)
            for k, v in CAPTION_STYLES[style].items():
                if k == "highlight":
                    continue
                if v == "brand":  # e.g. the premium panel takes the brand navy
                    v = colors.get("navy") or colors.get("background") or "#0F1E4A"
                ops.append({"op": "set", "path": f"captions.{k}", "value": v})
            if CAPTION_STYLES[style].get("highlight") == "brand" and not plan["captions"].get("highlight"):
                ops.append({"op": "set", "path": "captions.highlight", "value": colors.get("highlight", "#F97316")})
            ops.append({"op": "set", "path": "captions.style", "value": style})
    if "caption" in t and ("top" in t or "higher" in t):
        ops.append({"op": "set", "path": "captions.position", "value": "top"})
    if "caption" in t and ("bottom" in t or "lower" in t) and "lower third" not in t:
        ops.append({"op": "set", "path": "captions.position", "value": "bottom"})
    if "zoom" in t and any(w in t for w in ("remove", "no ", "delete", "kill")):
        zs = [z for z in plan["zooms"] if z.get("enabled", True)]
        if "all" in t or at is None:
            ops += [{"op": "toggle", "id": z["id"], "enabled": False} for z in (zs if "all" in t else zs[:0])]
        if at is not None:
            near = min(zs, key=lambda z: abs((z["start"] + z["end"]) / 2 - at), default=None)
            if near:
                ops.append({"op": "toggle", "id": near["id"], "enabled": False})
    m = re.search(r"keep (?:that|this|the) section", t)
    if m and at is not None:
        hits = [c for c in plan["cuts"] if c.get("enabled", True) and c["start"] - 1 <= at <= c["end"] + 1]
        ops += [{"op": "toggle", "id": c["id"], "enabled": False} for c in hits]
    m = re.search(r"title behind me(?: (?:saying|reading|that says))? ?\"?([^\"]+)?\"?", text, flags=re.I)
    if m:
        ops.append({"op": "add_graphic", "template": "KineticTitle", "start": at or 0.5, "duration": 3.5,
                    "props": {"text": (m.group(1) or plan["summary"]["topic"]).strip().upper()},
                    "placement": "behind"})
    card_types = "|".join(re.escape(k) for k in CARD_TYPE_PURPOSE)
    m = re.search(rf'add a ({card_types}) card saying\s*"([^"]+)"', text, flags=re.I)
    if m:
        tier, purpose = CARD_TYPE_PURPOSE[m.group(1).lower()]
        quote = m.group(2).strip()
        ops.append({"op": "add_card", "tier": tier, "purpose": purpose, "text": quote,
                    "start": _quoted_time(plan, quote, at)})
    mood_words = "confident|chill|claims|method|upbeat|lofi|calm|driving|hiphop|corporate|motivational"
    m = re.search(rf"\b({mood_words})\s+music\b", t)
    if m or re.search(r"\badd music\b", t):
        mood = m.group(1) if m else _infer_music_mood(plan["summary"].get("video_type", ""), plan["summary"].get("topic", ""))
        from . import music as music_mod
        track = music_mod.pick(mood, seed=plan.get("project_id", ""))
        if track:
            cur = plan.get("audio", {}).get("music") or {}
            bed_db = float(cur.get("bed_db", cur.get("volume_db", -11)))
            ops.append({"op": "set", "path": "audio.music",
                        "value": {"path": track["path"], "bed_db": bed_db, "volume_db": bed_db,
                                  "lufs": track.get("lufs"), "mood": mood, "title": track.get("title")}})
        else:
            ops.append({"op": "note", "text": f"No music track matched mood '{mood}' in ~/VibeStudio/music"})
    if "opening" in t and any(w in t for w in ("exciting", "stronger", "punchier", "better")):
        ops.append({"op": "set", "path": "hook.cold_open", "value": True})
        hook = plan["summary"].get("suggested_hook")
        if hook and not any(z["start"] == hook["start"] for z in plan["zooms"]):
            ops.append({"op": "add_zoom", "start": hook["start"], "end": hook["end"], "scale": 1.15})
    if any(k in t for k in ("dead air", "tighter", "too slow", "faster pace", "remove pauses", "cut the pauses",
                            "cut the silence", "remove silence", "less pause", "snappier", "speed it up")):
        ops.append({"op": "pace", "value": "snappy" if any(k in t for k in ("snappier", "very tight", "faster pace")) else "tight"})
    if "no music" in t or "remove music" in t:
        ops.append({"op": "set", "path": "audio.music", "value": None})
    return ops


def save(plan: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hist = path.parent / "plan_history"
    if path.exists():
        hist.mkdir(exist_ok=True)
        old = json.loads(path.read_text(encoding="utf-8"))
        (hist / f"plan_v{old.get('version', 0)}.json").write_text(json.dumps(old, indent=1), encoding="utf-8")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    tmp.replace(path)
    (path.parent / "plan.md").write_text(to_markdown(plan), encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
