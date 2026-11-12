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
