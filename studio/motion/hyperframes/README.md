# HyperFrames motion kit (vendored)

This folder vendors a subset of the **Herk Edit Kit** by Nate Herk, so Vibe
Studio's motion pipeline can drive HyperFrames/GSAP card animations locally
without pulling the whole external repo into every clone.

Source: https://github.com/nateherkai/herk-edit-kit

## What's here

- `package.json` / `node_modules/` (gitignored) — local install of the
  `hyperframes` CLI (0.7.109) and `gsap` (3.14.2) devDependencies.
- `library/` — a copy of the kit's `style-library/`: `GUIDE.md`,
  `registry.json`, `_blueprint/`, and the `01-vox-explainer/` and
  `02-kallaway/` style packs (each with `cards/`, `DESIGN.md`, `style.json`,
  `tokens.css`, and `_preview/`). No `.mp4` previews are vendored — this
  snapshot of the kit ships `_preview/contact-sheet.html` only, no PNG/MP4
  poster assets.
- `templates/` — a copy of the kit's `style-templates/` (starter HyperFrames
  projects, e.g. `dark-graph-paper-template/`, `left-glass-popout/`).
- `docs/` — `EDITING-PLAYBOOK.md`, `MOTION_PHILOSOPHY.md`, and the relevant
  `.claude/skills/` folders copied under `docs/skills/`: `hyperframes`,
  `hyperframes-cli`, `gsap`, `hyperframes-video-beats`, `cut-mistakes`,
  `cut-silences`, `short-form-edit`, `video-storytelling`.
- `licenses/` — `LICENSE` (MIT), `PIPELINE-USE-PERMISSION.txt`,
  `HYPERFRAMES-LICENSE` (Apache-2.0, for the HyperFrames package itself),
  `THIRD_PARTY_NOTICES.md`, and the per-skill `NOTICE-*.txt` files.

Not vendored: `.env.example`, `video-projects/`, `examples/`,
`package-lock.json` (none of these are needed for the motion pipeline).

## Licenses, in plain terms

- The Herk Edit Kit content (skills, templates, style library) is **MIT**,
  plus an additional **PIPELINE-USE-PERMISSION** that spells out how it may
  be used inside an automated pipeline like this one. Read both files in
  `licenses/` before redistributing or reselling anything built from this
  kit.
- **HyperFrames** itself (the npm package / CLI) is **Apache-2.0** — see
  `licenses/HYPERFRAMES-LICENSE`.
- See `licenses/THIRD_PARTY_NOTICES.md` and the `NOTICE-*.txt` files for
  attribution details on individual skills.

## Rules for working in this folder

- **Never edit cards in `library/`.** The pipeline stages copies of cards
  into a project's working directory before rendering — edit the staged
  copy, not the source in `library/cards/...`.
- `node_modules/`, `renders/`, and `_stage/` are gitignored; run
  `npm install` here after cloning to pull in `hyperframes` and `gsap`.
