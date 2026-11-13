# Decisions

## 2026-11-11

1. **HyperFrames cards render to the same transparent MOV as Remotion, so one overlay path serves both.**
   - Decision: Use a single render pipeline for both HyperFrames and Remotion overlays.
   - Why: Simplifies the motion pipeline and reduces code duplication. Both produce transparent ProRes 4444, so they can be composed identically.
   - Alternatives rejected: Separate pipelines per card type (adds complexity); render-time format conversion (adds overhead).

2. **The vendored library is read-only; it's staged per render and works offline.**
   - Decision: Never edit cards in studio/motion/hyperframes/library/. Copy cards to _stage/ before rendering.
   - Why: Keeps the library clean, supports offline operation, and makes updates safe (new versions can be swapped in without conflicts).
   - Alternatives rejected: Direct edits in library (loses track of changes, breaks updates); always fetch from external source (requires network).

3. **New behaviour is keyed on plan fields written by build(), so old plans render the same.**
   - Decision: Playbook cut rules (filler_guard, cut_pad), Shorts pace, captions style, and music are applied only to new plans that have the field set.
   - Why: Preserves rendering consistency for existing projects; users can opt-in or re-plan to use new defaults.
   - Alternatives rejected: Apply to all plans (breaks existing videos on re-render); config file switch (doesn't scale as features grow).

4. **SFX are synthesized locally, alongside the licensed Mixkit library; music comes from the licensed library by mood.**
   - Decision: SFX are generated on-demand (deterministic by seed), stored as WAV + manifest.json. Music is picked from Mixkit by mood tag.
   - Why: SFX don't require licensing overhead and stay consistent across runs. Music mood selection is faster than searching by hand.
   - Alternatives rejected: Download SFX from the same library (licensing cost); use only Mixkit (has few SFX); random generation (hard to reproduce).

5. **QA checks report; loudness is a warning, not a failure.**
   - Decision: QA output includes every check (words, mouth, contrast, loudness). Loudness ≤-18 LUFS prints a warning but doesn't block render.
   - Why: Loudness varies by content and platform. A warning nudges the user without stopping production.
   - Alternatives rejected: Loudness fail (too strict for varied content); skip loudness entirely (loses valuable info).

6. **Tier1 cards are landscape-only.**
   - Decision: `tier_allowed()` returns False if tier1 and height > width. Tier1 cards don't fit vertical frames.
   - Why: Tier1 takeovers are full-bleed landscape designs. Forcing them into Shorts would crop and ruin them.
   - Alternatives rejected: Scale/crop tier1 to fit (destroys the design); allow anyway (broken output).

7. **Licences are kept in studio/motion/hyperframes/licenses.**
   - Decision: MIT, Apache-2.0 (HyperFrames), and PIPELINE-USE-PERMISSION are in the licenses/ folder. Vendored kit is documented in README.md.
   - Why: All dependencies and their licences are in one place; easy to audit and redistribute.
   - Alternatives rejected: Licenses scattered (hard to find); no license docs (legal risk).

## 2026-11-12

8. **The vertical screen panel pans/zooms to wherever the real content is, instead of a fixed centre crop.**
   - Decision: `compose.py` samples the screen recording (frame differencing + edge density, ignoring the top chrome band), smooths it into held/eased keyframes, and builds a dynamic ffmpeg `crop` expression (w/h/x/y as functions of `t`) for the vertical master's screen panel. A plan/project `screen_focus` list of manual `{t, cx, cy, zoom}` keyframes overrides the automatic ones near their own time (e.g. where the owner circled something on a Short).
   - Why: Screen-share recordings often put the meaningful content (a keyword list, a chart's values) off to one side; a fixed centre crop cuts it off or makes it too small to read.
   - Alternatives rejected: Always re-center on cursor position (jittery, chases clicks instead of content); let the owner hand-place every keyframe (too slow for a whole recording).
   - Caveat: ffmpeg's expression parser rejects a piecewise `if(lt(t,...))` chain nested much past ~98 levels, so keyframes are thinned to 80 before building the expression (`_thin_keyframes`).

9. **Rebuilding a vertical master writes a new file; it never overwrites the one already in use.**
   - Decision: `build_masters()` always writes to its out_dir's fixed `layout_vertical.mp4`/`layout_landscape.mp4`, so re-running it with new framing logic is done in a scratch out_dir, and only the vertical file is copied out as `layout_vertical_v2.mp4`. The project keeps the old path as `source.vertical_path_v1`.
   - Why: Lets a framing change be previewed and compared against the original without risking the file every existing render points at.
   - Alternatives rejected: Overwrite in place (destructive, no fallback if the new framing is worse somewhere).

10. **A HyperFrames tier2 card reaches Shorts the same way a Remotion template does.**
    - Decision: `pipeline._short_graphics()`'s template whitelist includes `"HyperCard"` (previously it silently dropped every HyperCard graphic from a Short's render, even though `tier_allowed()` already handles the real tier1-vs-vertical restriction one layer down).
    - Why: Tier2 cards are designed to be overlay-safe on vertical frames; there's no reason a Short-specific label/lower-third card should be excluded.
    - Alternatives rejected: Route Short labels through a Remotion template instead (works, but throws away the HyperFrames card library for the one surface - Shorts - where a quick label is used most).
