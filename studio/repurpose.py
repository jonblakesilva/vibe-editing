"""Publishing pack: titles, description, thumbnail concepts, social captions, hooks
and follow-up video ideas. Built only from what was actually said. These are
drafts for review; Claude Code refines them and nothing is ever published
automatically."""
from __future__ import annotations

from . import plan as plan_mod


def generate(plan: dict, transcript: dict, brand: dict) -> dict:
    s = plan["summary"]
    topic = s["topic"]
    kw = s["keywords"]
    hook = (s.get("suggested_hook") or {}).get("text", "")
    cta = brand.get("cta", {}) or {}
    chapters = plan.get("chapters", [])
    tl = plan_mod.timeline(plan)
    titles = [
        topic,
        f"How to {kw[0]} (step by step)" if kw else topic,
        hook.rstrip(".!?")[:70] if hook else topic,
        f"The {topic} Most People Get Wrong",
        f"{topic}: What I Wish I Knew Sooner",
    ]
    chapter_lines = [f"{plan_mod.fmt_time(tl.to_edit_nearest(c['start'])).split('.')[0]} {c['title']}" for c in chapters]
    desc = [hook, "", f"In this video: {topic.lower()}.",
            *([""] + ["Chapters:"] + chapter_lines if len(chapter_lines) >= 3 else []),
            *(["", f"{cta.get('text')}"] if cta.get("text") else []),
            *([cta["url"]] if cta.get("url") else [])]
    clips = plan.get("clips", [])
    return {
        "titles": list(dict.fromkeys(t for t in titles if t)),
        "description": "\n".join(desc).strip(),
        "thumbnail_concepts": [
            f'Close-up, confident expression; 3-4 word text: "{" ".join(topic.upper().split()[:4])}"; brand color '
            f'{brand.get("colors", {}).get("primary", "")} accent behind text.',
            f'Split frame: problem vs result; text "{(kw[0] if kw else topic).upper()}?"',
            "Pointing at a large number or checklist from the video; minimal text, high contrast.",
        ],
        "social_captions": [
            f"{hook}\n\nFull video on the channel." if hook else f"New video: {topic}",
            *[f"{c['hook']}\n\n#{(kw[0] if kw else 'tips').replace(' ', '')}" for c in clips[:5]],
        ],
        "hooks": [h["text"] for h in [s.get("suggested_hook")] + s.get("alternative_hooks", []) if h],
        "video_ideas": [f"Deep dive: {c['title']}" for c in chapters[1:4]] +
                       [f"Common mistakes with {k}" for k in kw[:2]] +
                       [f"Q&A: your questions about {topic.lower()}"],
        "short_titles": [c.get("title") for c in clips],
        "note": "Drafts generated from your transcript. Review before use; publishing always needs your approval.",
    }


def to_markdown(pack: dict) -> str:
    if not pack:
        return "# Publishing pack\n\n(not generated)\n"
    out = ["# Publishing pack", "", f"_{pack.get('note', '')}_", "", "## Title options"]
    out += [f"- {t}" for t in pack["titles"]]
    out += ["", "## Description", "", pack["description"], "", "## Thumbnail concepts"]
    out += [f"- {t}" for t in pack["thumbnail_concepts"]]
    out += ["", "## Hooks"] + [f"- {h}" for h in pack["hooks"]]
    out += ["", "## Social captions"] + [f"\n```\n{c}\n```" for c in pack["social_captions"]]
    if pack.get("short_titles"):
        out += ["", "## Short titles"] + [f"- {t}" for t in pack["short_titles"]]
    out += ["", "## More video ideas"] + [f"- {i}" for i in pack["video_ideas"]]
    return "\n".join(out) + "\n"
