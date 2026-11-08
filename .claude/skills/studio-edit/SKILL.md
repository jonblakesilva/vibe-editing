---
name: studio-edit
description: Edit a recording end to end with Vibe Studio - long-form YouTube edits, Shorts, or long-form-to-Shorts. Use when the user asks to edit a video or Tella recording, remove mistakes, add captions/motion graphics, clean audio, make Shorts/Reels/TikToks, set up a brand, or revise an edit ("make the captions smaller", "remove that zoom", "add a title behind me").
---

# Vibe Studio editing workflow

You run the studio for the user. They should never need a terminal. Explain in plain English.
All commands run from the repo root with the project venv:

```
.venv\Scripts\python -m studio <command>
```

## Hard rules
- Never modify, move or delete the user's original recording (the studio only reads it).
- Never render a FINAL until the user approves the plan. Previews are fine without approval.
- Never invent or reword what the user said. Captions and Shorts use only spoken words.
- Shorts scores are editorial judgements, never promised performance.
- Never publish or upload anywhere. Publishing always needs the user's explicit approval.
- Never paste API keys into chat, commands or files. `python -m studio keys set NAME` prompts privately.
- Do not claim something works until a render passes `verify` (the CLI prints PASS/FAIL per file).
- Tella: only use supported Tella connector tools. Exports and reads only; never edit or delete Tella videos.

## 1. Get the recording
- Local file or folder (Tella export folder, separate camera + screen files):
  `studio import "<path>" --brand <slug> --mode longform|repurpose|shorts`
  A folder picks the largest video as main and a file named like camera/cam/webcam as the camera track.
- From Tella (connector tools `mcp__tella__*`):
  1. `list_videos` / `search_videos` to find it; confirm the title with the user.
  2. `export_video` with `granularity: "raw"` (original, uncut) - or `"tracks"` for separate camera and
     screen files. Use `resolution: "4k"` only if they asked for 4K (their plan supports it).
  3. Poll `get_export_status` until `completed`, then
     `studio fetch "<downloadUrl>" --name "<title>" --brand <slug> --mode <mode>`.
- A URL the user owns or has permission to use: `studio download "<url>" --import`.

Mode: "edit this" = `longform`; "edit + make N Shorts" = `repurpose` (pass `--shorts N` to plan);
"make a Short/Reel/TikTok" = `shorts`.

## 2. Plan
`studio plan <project> [--mode repurpose --shorts 5 --short-min 20 --short-max 60] [--outputs youtube,shorts]
 [--caption-style clean|minimal|karaoke|bold] [--pace relaxed|natural|tight] [--type tutorial|sales|talking_head|promo|interview]`

`<project>` accepts any unique part of the project id, or `latest`.

Then act as the editor. Read `plan.md` (`studio show <project>`) AND the transcript
(`studio words <project>`), and improve the draft with your judgement:
- Check every cut. Restore any cut that removes teaching content, a step, proof or a needed
  qualifier: `studio revise <p> --ops '[{"op":"toggle","id":"c7","enabled":false}]'`.
- Add cuts the detector missed (rambling, off-topic tangents, a weaker duplicate explanation):
  `--ops '[{"op":"cut","start":61.2,"end":74.8,"reason":"Tangent about weather"}]'`.
- Set a real topic: `studio set <p> summary.topic '"How to book 20 more jobs a month"'`.
- Video-type rules: tutorials keep every step and readable screens (no zooms over UI);
  sales videos protect hook, objections, proof, benefits and the CTA; Shorts need a strong
  opening line, tight pacing and one clear takeaway.
- Review the hook and intro suggestions; for Shorts, review each clip's opening line and reorder,
  disable or adjust clips (`{"op":"set","path":"clips.0.end","value":83.5}`).
- Fix mis-heard names: `studio correct <p> <word_index> "Booked"` (timing unchanged), or add the
  term to the brand's vocabulary.
- Add notes for the user: `{"op":"note","text":"..."}`.

Show the user a short summary: length before/after, what you cut and why (with timestamps),
the hook, chapters, captions, graphics, audio and outputs. Ask them to approve or change it.

## 3. Revisions (any time)
Plain requests: `studio revise <p> "make the captions smaller"`. Supported phrases include captions
smaller/bigger/off/top/bottom, "<style> captions", "remove that zoom" (+ `--at <source seconds>`),
"keep that section" (+ `--at`), `add a title behind me saying "TEXT"`, "make the opening more exciting",
"no music". If the CLI says it couldn't map the request, express it as `--ops` (see `studio/plan.py`
`revise()` docstring: set, toggle, keep, cut, add_graphic, add_zoom, remove, note).
Revisions edit the existing plan (versioned in `plan_history/`); nothing is re-transcribed.

Motion graphic templates (Remotion): KineticTitle, LowerThird, ChapterCard, CallToAction, Callout,
BrandIntro. Example: `{"op":"add_graphic","template":"Callout","start":95,"duration":3,
"props":{"text":"Reply in 5 minutes","label":"Key point"}}`.
"Title behind me" (placement "behind") cuts the speaker out with MediaPipe (local) for the seconds the
title is on screen. Works best with one person and a clean background; hair edges are soft. If the
speaker fills most of the title area (tight 9:16 crops) the title is put in front and the render prints a
note - pass that note on to the user.

## Review comments
The user can pin comments to moments in any video from the dashboard. When they say "work through my
comments" (or after they review a preview), run `studio comments <p>` to list open comments. For each:
turn it into revision ops (comments on exports also show the matching original-recording time), apply
them, then `studio comments <p> --resolve <id> --note "what you changed"`. Ask the user if a comment is
ambiguous. Re-run the preview afterwards.

## 4. Preview, approve, render
- `studio preview <p> [--shorts]` - half-resolution, fast. Show the files (exports folder).
- `studio approve <p>` only after the user says yes.
- `studio render <p> [--shorts]` - final 1080p/4K + Shorts (captioned and clean copies), each
  verified with ffprobe and a full decode. Report PASS/FAIL honestly.
Exports land in `~/VibeStudio/projects/<id>/exports/` with .srt/.vtt captions, `chapters.txt`
and `publishing_pack.md` (titles, description, thumbnail ideas, social captions - drafts to refine).

## Framing
`reframe.mode` in the plan: `auto` (default: follows the speaker; if two people are on screen most of
the time, vertical versions use a stacked interview layout), `largest`, `split`, or `center` (screen
recordings). Example: `studio set <p> reframe.mode '"center"'`.

## Brands
`studio brand list|new "Name"|next <slug>|answer <slug> <key> <value>|set <slug> <path> <json>|add-reference <slug> <file>`
Interview one question at a time (`brand next`). Multiple brands are expected (e.g. The Lead
Venture, Booked Solid, Integrity Commercial Solutions). Add `vocabulary` (names, jargon) and
`lower_third.name/title`. Style references are for guidance only; never copy copyrighted media.

## Dashboard
`studio serve` -> http://127.0.0.1:8765 (local only). Same projects, plans and jobs as the CLI.

## Health
`studio doctor` (real tests; 30-60 s). Run it first if anything fails.
