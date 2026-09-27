# AGENTS.md — JARVIS

Instructions for Codex and other coding agents. [`CLAUDE.md`](CLAUDE.md) holds
the full rule set; background is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
and [`docs/ENGINEERING.md`](docs/ENGINEERING.md) (incidents, status, known
risks). This file is the condensed contract. If it and CLAUDE.md disagree,
CLAUDE.md wins — and fix the drift.

## What this is
An always-on Windows voice assistant in Python 3.12: wake word (openWakeWord)
→ local STT (faster-whisper) → Claude API (streaming, agentic tool loop) → TTS
(edge-tts, pyttsx3 fallback). Around it: ~36 tools, proactive monitors, a
camera/security subsystem, a phone PWA and a Discord bridge. It runs in
production — treat every change as a change to a running system.

## Where things are
| Area | Location |
|---|---|
| Composition root (wiring only) | `main.py` |
| Voice loop, conversation state | `src/listen_loop.py` |
| One turn: history, streaming, tool loop, TTS | `src/turn_runner.py` |
| LLM calls, persona prompt, tool schemas | `src/llm.py` (`JARVIS_SYSTEM_PROMPT`, `stream_response`) |
| Speech output | `src/text_to_speech.py` (`speak`, `speak_streaming`, `VOICE_BY_LANG`) |
| Config | `src/config.py`, `.env.example`, `docs/ENV_VARS.md` |
| Subsystem assembly, shutdown | `src/bootstrap.py` |
| Durable writes | `src/atomic_io.py` |
| Tests (auto-collected) | `tests/*_test.py` |
| Gate + hand-run tools (never in CI) | `scripts/` |
| Engineering log | `docs/MILESTONES.md`, `docs/CODE_AUDIT.md` |

## Commands (PowerShell, repo root, venv `.venv`)
```powershell
.\.venv\Scripts\python.exe scripts\run_all_tests.py   # full gate — baseline 58/58
.\.venv\Scripts\python.exe tests\<name>_test.py        # one suite, exit 0 = pass
.\.venv\Scripts\python.exe scripts\doctor.py           # environment check
.\.venv\Scripts\python.exe main.py                     # run with console
```
The launchers (`jarvis.pyw`, `jarvis_watchdog.pyw`) look for a hard-coded
`venv\` path; start them with `.\.venv\Scripts\pythonw.exe` explicitly. Older
docs and test headers that say `venv\` mean `.venv\`.

## Rules
1. **Understand first, then change.** Read the module and its tests before
   editing. Do not remove or restructure existing features unless asked.
2. **Small, targeted diffs.** No drive-by refactors, renames or reformatting.
3. **Plan before risk.** Hot path (`listen_loop`, `turn_runner`), security,
   tool gates, durable stores, dependencies, or more than a few files: present
   the plan and wait for approval.
4. **Test.** Run the matching suite after a code change; run the full gate after
   larger ones. Anything below 58/58 is a regression until proven otherwise.
5. **Git.** `main` is the stable base. Never commit to `basis-deutsch-stabil`.
   Work on a branch. Do not commit or push unless asked.
6. **No new dependencies** without a real need; a new direct import gets its
   own line in `requirements.txt`.
7. **Windows first.** PowerShell commands, Windows paths, Python 3.12.

## Hard boundaries — never without an explicit instruction
- Never commit, print, overwrite or read out `.env`, keys, tokens or certs.
- Never enable, widen or loosen: security mode, camera, microphone, screen
  capture, remote access (PWA, Discord, geofence webhook), `run_code`,
  `pc_shell`, `system_control`, self-update, background agents
  (`JARVIS_BACKGROUND_AGENTS`) — not in code, defaults or `.env`.
- Remote origins keep the restricted tool surface, enforced at **both** gates
  (tool list filter *and* executor deny check). Never make it prompt-only.
- Mutating actions keep their `confirm: bool` gate and a preview that carries
  the information needed to decide.

## Persona and language
- JARVIS answers in **German** by default (formal "Sie") and calls the owner
  **"Master"** — sparingly, never "sir". Other languages only when the owner
  explicitly asks.
- Everything the user hears or sees stays German. Logs, identifiers, tool
  results, prompts and wire values may stay English.
- Persona: `JARVIS_SYSTEM_PROMPT` in `src/llm.py`; reply language/voice:
  `REPLY_LANGUAGE` in `src/turn_runner.py`. Changing them is a behaviour change.

## Code conventions
- **Fail soft.** Optional components log and degrade to an honest "not
  configured" / "unavailable". The listen loop and the Announcer thread must
  never die.
- `turn_runner` collaborators (`stream_response`, `speak`, `speak_streaming`,
  `MemoryStore`, `_seal_session`) stay module-level globals — the test seam.
- New durable state goes through `src/atomic_io.py`.
- Tests isolate real state: set `LOCALAPPDATA` (and `JARVIS_KNOWLEDGE_DIR` +
  `JARVIS_KNOWLEDGE_DB` for the knowledge layer) to a temp dir.
  `tests/scheduled_briefing_test.py` is a known exception that touches the real
  reminder store — do not copy its pattern.
- Measure before tuning; prove a threshold separates labelled data first.
- A bug a test would have caught earns a test. Fix the failure mode across peer
  components, not just the instance.
- After adding a milestone entry: `python tests/milestones_toc_test.py --write`.

## Acting as reviewer or second opinion
Default to read-only. Report findings with `file:line`, severity and a concrete
failure scenario; separate verified facts from suspicions. Do not modify files
unless explicitly asked.
