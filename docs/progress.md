# Progress

## Shipped (2026-11-11)

**HyperFrames card engine** — 410 branded motion cards (tier1 overview/section/stat, tier2 lower-third) in two styles (kallaway, vox-explainer). Cards render to transparent ProRes MOV, cached by content hash. CLI: `studio card add <p> --type lower-third --text "..."`. Revision phrase: `add a lower third card saying "..."`. Tier1 cards are landscape-only.

**Playbook cut rules** — Fillers (um, uh, like, just, you know) only cut with ≥0.1 s silence on both sides (filler_guard). 60 ms decay pad at every cut start (cut_pad). Both rules write to new plans only; old plans render unchanged.

**QA checks** — Every-word-whole at joins (clipped_word), mouth position check for first 2.5 s and first frame of each shot (mouth:), caption contrast (contrast_issues), loudness on final file (warning if ≤-18 LUFS, not a failure). Output: QA sheet JPG with flagged frames highlighted.

**Caption style "playbook"** — Dark box with light edge, 1–3 word chunks, ALL CAPS, red/green/teal on 25–45% of chunks, hard swaps at cuts, 2-frame lead-in, chunks split at shot changes, moves off mouth. Default for new plans.

**Shorts pace "playbook"** — Speech starts ≤0.1 s, phrase gaps ≤0.2 s, 0.2–0.4 s beats after commas and list words, punch-ins at 0.6–1.0 s and on 5–15% of Short. Default for new plans; old plans keep "natural" pace.

**Music** — Licensed Mixkit library (~VibeStudio/music) with mood tags, BPM, LUFS. Pick with `studio plan <project> --music-mood confident|chill`. Bed volume -11 dB (brand override to -16). Per-brand opt-in.

**SFX** — Five synthesized categories (whoosh, tap, click, paper, check), 4 variants each, 48 kHz stereo, deterministic seed. Sounds only on visible actions. `studio sfx generate` rebuilds locally. Lives alongside Mixkit at ~/VibeStudio/sfx/manifest.json.

**Thumbnails** — 1280×720 (or 1080×1920 for Shorts cover) with face detection (BiRefNet) and seven proof-driven layouts: face-number, payment, checklist, screenshot, two-person, clean-white, shorts-cover. CLI: `studio thumbnail <p> --layout face-number --item "Website" --amount "$47"`. Outputs to exports/thumbnails/. Matches owner's reference style.

## To preview with owner

- **Fewer filler cuts** — New filler_guard rule protects stammers that feel natural.
- **New playbook captions** — Dark box, red/green/teal accents, all caps, better pacing.
- **Tighter Shorts** — New pace playbook keeps content punchy.
- **HyperFrames cards** — Branded motion overlays; can add lower-thirds, stats, section headers.
- **Thumbnails v2** — Seven new layouts with face detection and better composition.

## Open items

- **Holes Short preview:** must be re-rendered in its original style (not the new playbook captions).
- **Month 1 SEO video:** review leftover restarts in the listen transcript after last render.
- **GHL scheduling:** blocked on Media Storage upload or a Private Integration key.
- **Overlay wiring:** HyperCard/Remotion composition into render.py (in progress).
- **SFX mixing:** final pass on SFX levels in the audio mix (in progress).
