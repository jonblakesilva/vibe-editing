# Vibe Studio — a self-hosted AI video editing studio

Record in Tella (or anything else), tell Claude Code how you want it edited, approve the plan, and
get a finished long-form video plus Shorts. Runs on your own computer; your original recordings
are never changed.

This is a fork of **[Vibe Editing](https://github.com/maddexritter-rgb/vibe-editing)** by its
original authors (MIT license, kept unchanged in [LICENSE](LICENSE)). Vibe Studio lives in
[`studio/`](studio/) and adds long-form editing, Windows support, a reviewable editing plan, a
caption engine, Remotion motion graphics, a dashboard and a test suite. The original short-form kit
is still here and documented [below](#original-vibe-editing-kit).

## What it does

| Mode | You get |
|---|---|
| **Long-form** (5-90 min: YouTube, tutorials, Tella screen recordings, talking head, sales training, demos, VSLs, interviews) | Mistakes, restarts, repeated takes, filler words and long pauses removed (breathing room kept); hook and intro suggestions; chapters; zooms; branded captions; lower thirds, chapter cards, callouts and CTAs; optional approved B-roll and licensed music with ducking; cleaned, loudness-normalized audio; 1080p or 4K MP4 + SRT/VTT + chapter list |
| **Shorts** (TikTok, Reels, YouTube Shorts, Facebook, LinkedIn) | 9:16, 1:1 or 16:9; tight silence removal; speaker-tracked vertical crop; word-highlight or pop captions in platform-safe positions; punch-in zooms; titles and CTA endings |
| **Long-form → Shorts** | The strongest stand-alone clips (5 by default, any number, your chosen length), each scored 0-10 on hook, value, clarity, relevance, stands-alone, pacing and CTA. Scores are editorial judgements, not view predictions. Clips start and end on full sentences and only contain words you said. Captioned and caption-free copies. |

Every edit follows the same loop: **plan → review/revise → approve → preview → final render**.
Revisions ("make the captions smaller", "remove that zoom", "keep that section", "make the opening
more exciting", "add a title behind me") change the existing plan instead of starting over.
Each output is checked with FFprobe and a full decode, and the result is reported as PASS or FAIL.
Nothing is ever published automatically.

## Supported systems

| | Status |
|---|---|
| Windows 10/11 | Tested (this fork was built and tested on Windows 11, AMD Ryzen, no NVIDIA GPU) |
| macOS / Linux | The fast test suite runs on macOS and Ubuntu in GitHub Actions on every push (`.github/workflows/studio-tests.yml`); full renders have only been run on Windows |

Transcription uses an NVIDIA GPU automatically if one exists; otherwise the CPU (a 1-minute clip takes
about 10-20 s on a mid-range laptop with the `small` model). Hardware video encoders are detected
and can be enabled with `VIBE_HW_ENCODER` (e.g. `h264_amf`).

## Install

Needs: **Python 3.11-3.13**, **FFmpeg** (with libass), **Node.js 22+**, **Git**. On Windows:
`winget install Gyan.FFmpeg`, `winget install OpenJS.NodeJS.LTS`, `winget install Python.Python.3.13`.

```powershell
git clone https://github.com/jonblakesilva/vibe-editing.git
cd vibe-editing
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r studio/requirements.txt
cd studio\motion\remotion; npm install; cd ..\..\..
.venv\Scripts\python -m studio doctor
```

Or open the folder in VS Code and ask Claude Code to "set up Vibe Studio" — it does all of this.

`doctor` only says **READY** after real tests: it synthesizes speech and transcribes it, renders a
cut with zoom + captions + loudness to 16:9 and 9:16 and verifies both, and renders a transparent
Remotion graphic. It also reports GPU, hardware encoders and optional tools.

## Everyday use (in Claude Code)

> "Edit my latest Tella recording. Remove mistakes, add premium captions, clean the audio, add motion
> graphics, create a finished YouTube video, and make five Shorts."

Claude follows [`.claude/skills/studio-edit/SKILL.md`](.claude/skills/studio-edit/SKILL.md): fetch the
recording, build the plan, review the cuts as an editor, show you the plan, wait for your approval,
preview, then render. The same steps by hand:

```powershell
.venv\Scripts\python -m studio import "C:\Videos\my-recording.mp4" --brand booked-solid --mode repurpose
.venv\Scripts\python -m studio plan latest --shorts 5 --short-min 20 --short-max 60
.venv\Scripts\python -m studio revise latest "make the captions smaller"
.venv\Scripts\python -m studio preview latest --shorts
.venv\Scripts\python -m studio approve latest
.venv\Scripts\python -m studio render latest --shorts
```

Or use the dashboard: `.venv\Scripts\python -m studio serve` → http://127.0.0.1:8765 (local only).
It has upload/drag-and-drop, project library, brand selection, mode selection, the transcript (click
to jump, double-click to fix a word), the editing plan with a timeline of kept vs removed sections,
caption/graphics/audio/export settings, Shorts with scores, real job progress with cancel/retry,
exports, and dark/light mode. **Comments:** pause any video (original, preview or final), type a
note, and it is pinned to that moment (shown as a dot on the timeline). Simple requests ("remove that
zoom") can be applied with one click; for the rest, tell Claude "work through my comments".

**Review screen (like Frame.io):** click **Review videos** (or open
`http://127.0.0.1:8765/review/<project id>`). Every rendered video is listed with its versions — each
re-render keeps the previous one as v1, v2, v3 — and you can:
- watch with frame-accurate timecode, step frame by frame, change speed, go full screen;
- comment at a moment or over a range (press **I** and **O**), draw on the frame (pen, arrow, box);
- see every comment as an avatar on the scrub bar, click one to jump there with its drawing shown;
- reply in threads, tick comments **Done**, filter Open / All / Done;
- compare two versions side by side, in sync;
- set each video to Needs review / In progress / Changes requested / Approved (a sign-off only; nothing
  is published).

Keyboard: Space/K play-pause, J/L back/forward 1 s, arrows step one frame (Shift = 1 s), I/O range,
C comment, D draw, Esc clear. Then tell Claude "work through my comments": it applies each one,
replies in the thread when it needs a decision, marks the rest Done, and renders a new version.

Projects, brands and renders are stored in `%USERPROFILE%\VibeStudio` (override with
`VIBE_STUDIO_HOME`), never inside the repository.

## Formats

- **In:** MP4, MOV, MKV, WebM, M4V, AVI (any FFmpeg-readable video; variable frame rate is
  normalized). Audio-only files can be transcribed but not rendered as video.
- **Out:** H.264/AAC MP4 — YouTube 1920×1080 or 3840×2160 (16:9), vertical 1080×1920 (9:16), square
  1080×1080 (1:1); `.srt`, `.vtt` and `.ass` captions; `chapters.txt`; `publishing_pack.md`
  (title options, description, thumbnail concepts, social captions, hooks, next-video ideas).

## AI providers

| Job | Default (free, local) | Optional |
|---|---|---|
| Transcription | faster-whisper (`small`; set `VIBE_WHISPER_MODEL=medium` for more accuracy) | Groq Whisper large-v3 (`studio keys set GROQ_API_KEY`) |
| Editing decisions | Built-in analysis (pauses, fillers, restarts, repeats, false starts, misheard noise, hooks, chapters, CTAs, video type) **plus Claude Code itself** reviewing the transcript and plan | — |
| Motion graphics | Remotion templates (offline) | HyperFrames or any transparent MOV via the `File` graphic |
| Subject masking ("title behind me") | MediaPipe selfie segmenter (local) | — |

No paid API is required. Keys are stored only in `~/.config/vibe-editing/keys.env` (outside the repo),
entered through a hidden prompt, and redacted from errors and logs.

## Brand profiles

Several brands can live side by side (e.g. The Lead Venture, Booked Solid, Integrity Commercial
Solutions). Claude asks one question at a time — name, logo, colors, fonts, caption style, pace,
music, intro, outro, CTA, audience, topics — or use `studio brand new "Booked Solid"` then
`studio brand next booked-solid`. Add `vocabulary` (brand names, jargon) so names are spelled right in
captions (e.g. "book Solid" → "Booked Solid"). Example videos/screenshots can be stored with
`studio brand add-reference` as style guidance; copyrighted media is never copied into your videos.

## Tella workflow

Two supported routes, and neither ever edits or deletes anything in Tella:

1. **Tella connector in Claude Code** (official Tella MCP). Claude finds the video, starts an export
   with `granularity: raw` (original recording, uncut) or `tracks` (separate camera and screen files),
   waits for the download link, and runs `studio fetch "<link>"`.
2. **Exported files.** Export from Tella, then drag the file into the dashboard, or
   `studio import "<file or folder>"`. A folder with separate screen and camera files is detected
   (camera = filename containing camera/cam/webcam).

Original quality is kept: the studio reads the file directly and only writes new files.

## Motion graphics

Remotion templates in [`studio/motion/remotion/src/templates`](studio/motion/remotion/src/templates):
`KineticTitle` (words rise out of blur with 3D settle, layered depth shadow and light sweep),
`LowerThird`, `ChapterCard`, `CallToAction`, `Callout`, `BrandIntro`. They pick up brand colors, render
once per change as transparent ProRes 4444 overlays (cached), and work at any aspect ratio.
Preview and tweak them with `npm run studio` in that folder.

**Title behind the speaker:** the speaker is cut out of the finished frames with MediaPipe, for only the
seconds the title is on screen, and stacked back on top of the title. Works best with one person and a
background that differs from their clothes and hair; hair edges are soft; objects held away from the
body may be treated as background. If the speaker fills most of the title area (common in tight 9:16
crops) the title is placed in front and the render prints a note saying so.

**Remotion license:** free for individuals, for-profit companies with up to 3 employees, and
non-profits. Larger companies need a [Remotion company license](https://www.remotion.dev/license).
**HyperFrames** (HeyGen, Apache-2.0) was tested as a second engine and works; its templates load GSAP
from a CDN, so it needs internet while rendering.

## Tests

```powershell
.venv\Scripts\python -m pytest -m "not slow"   # ~10 s: cut accuracy, timeline mapping, A/V drift over 30 cuts,
                                               # caption sync and safe zones, render resume after a crash,
                                               # cancellation, missing tools, key handling, secret scan
.venv\Scripts\python -m pytest -m slow         # ~4 min: full import -> plan -> approve -> 16:9 + 9:16 + Shorts render,
                                               # re-transcribes the output to check captions match speech,
                                               # and confirms the original file is byte-for-byte unchanged
```

The sample recording (with deliberate mistakes) is generated locally by
`studio/tests/fixtures/make_sample.ps1`.

## Known limitations

- Full end-to-end renders have been verified on Windows; macOS/Linux run the fast tests in CI.
- The original kit's scripts were made Windows-compatible enough for all 35 of its tests to pass
  (portable file locking, UTF-8 reads, home-folder lookup), but its full `/edit` pipeline still assumes
  macOS tools in places and was not run end to end.
- The editing analysis is rule-based; Claude Code's review is what catches context ("this tangent can
  go"). Without Claude (dashboard only), review the cut list yourself before approving.
- Two-person interviews get a stacked vertical layout when both are on screen most of the time; there is
  no active-speaker switching yet (who is talking is not detected).
- B-roll is only inserted from clips you add yourself (no stock library is searched automatically).
  Music is only used from tracks you provide and have the rights to.
- Chapters need at least 3 sections of 10+ seconds (YouTube's rule); short videos get a note instead.
- Very long recordings are processed in streamed sections, but faster-whisper holds the 16 kHz audio
  in memory (about 115 MB per hour).

## Troubleshooting

| Problem | Fix |
|---|---|
| Anything fails | `python -m studio doctor` — it names the failing piece and the install command |
| "plan has not been approved" | Previews work any time; final renders need `studio approve <project>` |
| A render failed halfway | Run it again (or Retry in the dashboard); finished sections are reused |
| Wrong word in captions | Double-click it in the dashboard transcript, or `studio correct <project> <index> "word"` |
| Captions in the wrong font | Fonts come from `plugins/vibe-editing/skills/caption-clips/fonts`; brand fonts can go in the brand folder |
| Graphics missing | `cd studio/motion/remotion && npm install`, then `studio doctor` |
| Transcription slow | Use `VIBE_WHISPER_MODEL=base`, or Groq with `studio keys set GROQ_API_KEY` |

Security review notes for this fork are in [docs/STUDIO_SECURITY.md](docs/STUDIO_SECURITY.md).

---

## Original Vibe Editing kit

*(Unchanged from upstream. The short-form plugin under `plugins/vibe-editing` is macOS-first.)*

**Raw footage in → finished, captioned, self-audited vertical clips out, with one command.**

The full short-form pipeline as a Claude Code plugin: ingest → transcribe → mine the best
moments (with a real editorial rubric) → hand-cut → face-track to 9:16 → caption → mix music →
render → construction/file checks → deliver.

> **Start here:** open **`ONBOARDING.md`** and paste it into the **Claude Code** app — it installs
> everything for you and interviews you about your brand (logo, fonts, colors, style), then makes a
> test clip. No editing software, no terminal. `Vibe-Editing-Playbook.pdf` is the deeper walkthrough.

### Quickstart
```
./setup.sh                         # installs ffmpeg + deps, runs a health check
# then ask your agent: "Set up Vibe Editing for me" (ONBOARDING.md)
/edit <your youtube link>          # in Claude Code   — or:   ./bin/vibe-editing "<link>"
```
Check readiness any time: `python3 plugins/vibe-editing/doctor.py`

### What's INCLUDED — the full method
The complete editorial brain ships here (anonymized): the clip-selection rubric, the cut logic,
the spice caption styling, the audit rules, and the lift patterns. **Out of the box it cuts with
real editorial judgment, not a generic template** — the clips come out to a high bar, and the
active agent applies the editorial references and inspects the result; additional audits are opt-in.

### What YOU supply
| You bring | Where |
|---|---|
| Editing connections (AssemblyAI, Gemini, agent reads bundled editorial docs; optional audit/fallback keys) | Agent-guided [onboarding](ONBOARDING.md); secrets saved privately |
| Footage | the project's `00_SOURCE/` (or a URL / drive link) |
| Music | your royalty-free tracks → `VIBE_MUSIC=/your/music` |
| Font & brand | swap the bundled free font; set your cover logo / product name |

### What's deliberately NOT in here
Only the things that are pure liability and add nothing to clip quality:
- **API keys** — bring your own; [complete inventory and setup](docs/CONNECTIONS.md).
- **Licensed fonts** — free **Montserrat** ships instead (looks the same, legal to redistribute).
- **Personal / client data** — real names, revenue figures, and client footage were anonymized
  or removed. None of it is used to make a clip.

### First use and connections
The agent walks through [ONBOARDING.md](ONBOARDING.md) before the first production job and saves
progress. **AssemblyAI** is the primary transcription provider, matching the current `/edit`
pipeline. The active agent reads the bundled editorial documents without an Anthropic/OpenAI key.
Gemini and optional audit/fallback credentials have distinct roles in the
[connection inventory](docs/CONNECTIONS.md). Some current team-native integrations are companion
installations; the inventory names those prerequisites rather than treating keys as a full install.

### Deliver to Frame.io + Monday
Say **“push these clips to Frame and Monday.”** First use connects your own accounts and asks
which brands you edit for, your editor initials, and where each brand's clips should go.
Shorts are the default. The kit handles filenames, Frame uploads and linked Monday review cards.
[Delivery setup](plugins/vibe-editing/skills/monday/references/onboarding.md).
