# Security and license review (fork of maddexritter-rgb/vibe-editing, 2026-11-07)

Reviewed before anything was installed or run.

## License
MIT (upstream `LICENSE`, unchanged). Modification and redistribution are allowed as long as the
copyright notice and license text stay with the code. Bundled fonts are OFL (Montserrat, Inter and the
Google Fonts set). Remotion has its own license (free for individuals and companies with up to 3
employees); HyperFrames is Apache-2.0; MediaPipe is Apache-2.0; faster-whisper is MIT.

## Findings in the upstream kit
| Item | Risk | Handling in Vibe Studio |
|---|---|---|
| `plugins/vibe-editing/config/editorial-brain.json` ships a shared read token for a Supabase edge function run by the upstream authors (`vibe-editorial-read`). It sends only a format name and downloads editorial "playbook" text that the agent is told to read. | Low data exposure, but it is remote, author-controlled text fed to an AI agent (a prompt-injection path) and it phones home. | Vibe Studio never calls it. Left in place so the upstream kit keeps working; do not run `editorial_brain.py` unless you trust that source. |
| `setup.sh` / doctor suggest the Homebrew `curl \| bash` installer | Standard but runs remote code | Not used on Windows; studio doctor suggests `winget` with official package IDs. |
| `requirements.txt` has no version pins | Supply-chain drift | Studio uses lower-bounded requirements; install into a project-local `.venv` only. |
| Scripts delete temp files with `os.remove`/`shutil.rmtree` | Checked: only their own temp/work folders, never source footage | Studio never deletes or writes to originals (tested by hash in the end-to-end test). |
| Network calls: AssemblyAI, Groq, Gemini, Frame.io, Monday, Buffer, YouTube upload, Adobe IMS | Only with your own keys | Studio's only optional network calls: Groq (if you add a key), MediaPipe model download from Google's model bucket, Tella export downloads you request. |
| Stray 25 KB file `plugins/vibe-editing/skills/caption-clips/--out` | Harmless leftover transcript | Left untouched (upstream file). |
| No `shell=True`, `eval` or pickle loading found | — | Studio follows the same rule. |

## Studio safeguards
- Dashboard binds to 127.0.0.1 only; file serving is restricted to the project's exports folder.
- Keys live in `~/.config/vibe-editing/keys.env`, are entered via a hidden prompt, and are redacted
  from error messages; a test scans tracked files for key patterns.
- Final renders require an approved plan; publishing is never automatic.
