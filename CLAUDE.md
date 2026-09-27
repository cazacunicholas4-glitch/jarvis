# Project: jarvis

Agent instructions, loaded every session — rules only. Background lives in
`docs/`: [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) (stack and reasons,
subsystems, language details, runtime state, TLS),
[`ENGINEERING.md`](docs/ENGINEERING.md) (incidents behind the rules, status,
risks, backlog), [`MILESTONES.md`](docs/MILESTONES.md) (full log),
[`CODE_AUDIT.md`](docs/CODE_AUDIT.md), [`ENV_VARS.md`](docs/ENV_VARS.md).
Codex reads [`AGENTS.md`](AGENTS.md), a condensed copy of these rules — keep
them in sync; if they disagree, this file wins.

## The project
An always-on Windows voice assistant (Python 3.12): wake word (openWakeWord) →
local STT (faster-whisper) → Claude API (streaming, agentic tool loop, ~36
tools) → TTS (edge-tts, pyttsx3 fallback). Around it: proactive monitors,
camera security, acoustic awareness, speaker ID, a phone PWA and a Discord
bridge. In production as a supervised process; the regression gate is
**58/58 green** on the stable Windows baseline.

| What | Where |
|---|---|
| Composition root — wiring only | `main.py` |
| Voice loop, conversation state machine | `src/listen_loop.py` |
| One turn: history, streaming, tool loop, TTS | `src/turn_runner.py` |
| Persona, LLM calls, tool schemas (the index of what Jarvis can do) | `src/llm.py` |
| Speech output, voices | `src/text_to_speech.py` |
| Subsystem assembly, shutdown | `src/bootstrap.py` |
| Config | `src/config.py`, `.env.example`, `docs/ENV_VARS.md` |
| Durable writes | `src/atomic_io.py` |
| Launchers | `jarvis.pyw` (silent), `jarvis_watchdog.pyw` (respawns on crash) |
| Tests / gate | `tests/*_test.py`, `scripts/run_all_tests.py` |

## Working rules
**JARVIS is an existing production project. Understand first, then change.**

- **Scope.** Don't remove or restructure existing features unless asked. Prefer
  small, targeted diffs. Before editing, read the module *and its tests*.
- **Plan before risk.** Hot path (`listen_loop`, `turn_runner`), security, tool
  gates, durable stores, dependencies, or more than a few files: show the plan
  and wait for approval.
- **Test after change.** Matching suite(s) after a code change; the full gate
  after larger ones. Below 58/58 is a regression until proven otherwise.
- **Git.** `main` is the stable base. `basis-deutsch-stabil` is a frozen
  snapshot of the German baseline — never commit to it. Work on a branch
  (e.g. `claude-setup`). Commit or push only when asked.
- **Secrets.** Never commit, print, overwrite or read out `.env`, keys, tokens
  or certs. Refer to settings by name; `.env.example` is the template.
- **Sensitive capabilities stay as configured.** Don't enable, widen or loosen
  security mode, camera, microphone, screen capture, remote access (PWA,
  Discord, geofence webhook), `run_code` / `pc_shell` / `system_control`,
  self-update or background agents without an explicit instruction — not in
  code, defaults or `.env`.
- **Dependencies.** None without a real need; a new direct import gets its own
  line in `requirements.txt` (and `requirements-ci.txt` if it is a plain wheel).
- **Platform.** Windows first; venv `.venv` (Python 3.12); PowerShell commands.
  Older docs and test headers saying `venv\` mean `.venv\`.

**Tooling.** fast-context (`fast_context_search`) for broad or natural-language
code search, grep for exact strings. context7 for current library docs
(anthropic, faster-whisper, openwakeword, edge-tts, sounddevice, websockets,
discord.py, ultralytics). CCG / Codex for review, architecture, debugging and
second opinions — confirm their findings in the code before acting.

## Commands
```powershell
# Setup
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip uninstall -y typing   # resemblyzer's backport shadows stdlib typing
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # never overwrite

# Run
.\.venv\Scripts\python.exe main.py                # console, dev/debug
.\.venv\Scripts\pythonw.exe jarvis.pyw            # silent (production)
.\.venv\Scripts\pythonw.exe jarvis_watchdog.pyw   # supervised (production)

# Test
.\.venv\Scripts\python.exe scripts\run_all_tests.py   # full gate — must be 58/58 before any commit
.\.venv\Scripts\python.exe tests\<name>_test.py        # one suite, exit 0 = pass
.\.venv\Scripts\python.exe scripts\doctor.py           # deps, config, TLS cert days left
```
- **Launchers** hard-code `venv\Scripts\pythonw.exe` (`jarvis.pyw:32`,
  `jarvis_watchdog.pyw:63`). Start them with the `.venv` interpreter as above;
  a bare `pythonw jarvis.pyw` or a double-click runs system Python and dies on
  import. Changing the launchers is a code change — ask first.
- **The gate** = `py_compile` + `import main` + a PWA JS structure check + every
  `tests/*_test.py` (55). CI runs a lighter subset (`--allow-missing-deps`); the
  local full gate is the bar.
- **`tests/` is auto-collected; `scripts/` never is** — some scripts there cost
  API calls or need hardware for hours. Keep it that way.
- **Known gap:** `tests/scheduled_briefing_test.py` writes to the *real*
  `%LOCALAPPDATA%\Jarvis\reminders.json`. New suites isolate `LOCALAPPDATA`
  (and `JARVIS_KNOWLEDGE_DIR` + `JARVIS_KNOWLEDGE_DB`) like `reminders_test.py`.
- After adding a milestone entry: `python tests/milestones_toc_test.py --write`,
  or the gate fails.

## Privacy by design
- Wake word and STT are local; only the transcribed text goes to Claude. Edge
  TTS is online (Microsoft sees reply text).
- Anything that ships data off-box (push notifications, remote clients) is
  opt-in and off by default.
- **One deliberate exception: background agents (M91)** run on Anthropic's
  infrastructure, so they are **off unless `JARVIS_BACKGROUND_AGENTS=1`**. Don't
  widen this quietly — any new off-box feature gets its own flag and its own
  line here.

## Security boundaries
- **Least privilege, server-side.** Remote origins (phone, Discord) get a
  restricted tool surface — no shell, system control, filesystem, code
  execution or self-update — enforced at **two gates**: the tool list offered
  to the model *and* the executor's deny check. Never prompt-only. Re-opening
  one tool for one origin is a surgical allowance, not a boundary flip.
  *Jarvis, not Ultron.*
- **Confirmation gates.** Mutating verbs take `confirm: bool`; without it they
  return a description of what would happen, carrying what the user needs to
  decide (self-update lists the actual pending commits). Privileged verbs also
  need an elevated process (opt-in tray action).
- **`run_code` is contained, not allowlisted:** ephemeral Podman,
  `--network=none`, no host mount, CPU/memory/PID caps, timeout, non-root, full
  audit log.

## Engineering rules
One line each; the incidents behind them are in
[`docs/ENGINEERING.md`](docs/ENGINEERING.md).
- **Fail soft, never crash the loop.** Optional components log and degrade to
  an honest "not configured" / "unavailable". Two threads must never die: the
  listening loop and the **Announcer** (the only path for unprompted speech,
  including security alerts). UI sinks (`_console_call`, `_remote_call`) stay
  defensive on both sides.
- **`turn_runner` seam.** `stream_response`, `speak`, `speak_streaming`,
  `MemoryStore`, `_seal_session` stay module-level globals;
  `turn_runner_patch_test.py` fails if a refactor breaks that.
- **New durable state uses `src/atomic_io.py`** (no UPS on the target). It is
  not backed up until added to `$include` in `scripts/backup_state.ps1` — an
  allowlist on purpose, since that folder also holds a TLS key, a Ring token
  and camera evidence. `sessions/`, `summaries.jsonl`, `speakers/` are
  irreplaceable.
- **Measure before you tune.** Correlate scores with their input. Before tuning
  a threshold, prove one exists (`min(POS) > max(NEG)` on labelled data). If a
  fix migrates data, re-validate after the migration.
- **Cooperative gates have two sides.** Heavy CPU work yields while audio
  plays: every consumer yields, every producer (every path that speaks) raises
  the gate — including model *load* at startup. Authentication must grant
  something (a passed challenge opens a short trusted session).
- **A bug a test would have caught earns a test**, with a fixture big enough to
  express the bug.
- **Fix the failure mode, not the instance.** Symmetric components (the two
  capture streams, capture/playback rings, every origin in the tool gate) fail
  symmetrically — check the peers.
- **Rule of three** before extracting a shared helper.
- **Cost and latency.** Sonnet by default, Haiku for background jobs, prompt
  caching on the system prompt; thinking explicitly disabled on voice and
  background paths, adaptive only in engineer mode. Stream everything; short
  replies. Targets: wake word <100 ms, STT <2 s, first audio ≤1 s after
  streaming starts, question-to-answer 2-3 s.
- **Consolidation passes** (no new features; fix in risk order) after ~20
  milestones, a recurring regression, or a god-file signal. Look at the newest
  code first. Template: [`docs/CODE_AUDIT.md`](docs/CODE_AUDIT.md).
- **Close-out.** Gate green → sync `CLAUDE.md`, `AGENTS.md`, `docs/MILESTONES.md`
  → commit/push when the user asks. Mark deferred items done in this file — it
  is the only state a context reset reloads.

## Persona and language
- Butler tone: courteous, dryly witty, concise — the films' understated
  J.A.R.V.I.S., not a parody. Headline first, then offer more. Short
  sentences, no needless apologies.
- **German by default** (formal "Sie"), even when the input contains English.
  Other languages only on explicit request (Spanish: formal *usted*, Latin
  American). The owner is **"Master"** — sparingly, never "sir"; other enrolled
  people by name.
- User-facing text stays German. Tool results, prompts, tool descriptions, logs
  (`self_review` parses them), identifiers and wire values stay English.
  Scheduled briefings are composed in English and translated at fire time.
- In code: persona `JARVIS_SYSTEM_PROMPT` (`src/llm.py`); reply language and
  voice `turn_runner.REPLY_LANGUAGE = "de"`; voices `VOICE_BY_LANG`
  (`src/text_to_speech.py`). Changing them is a behaviour change.
- Engineer mode (tray toggle) lifts the brevity rule and enables adaptive
  thinking. After any model swap, check reply *length* as well as tool routing.

## Open items to know before touching related code
Details in [`docs/ENGINEERING.md`](docs/ENGINEERING.md).
- **Armed-mode audio starvation (M99) is open.** Three fixes were measured and
  rejected — read the entry before touching audio buffering.
- **`listen_loop()` extraction is deferred** (945-line function, 598-line
  closure): it needs a `VoiceSession` state object and a tested seam first.
- **Home Assistant MCP is deliberately not built** until a real HA instance
  exists to validate against.
