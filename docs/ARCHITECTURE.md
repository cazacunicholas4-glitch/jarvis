# JARVIS — Architecture and stack background

Moved out of [`CLAUDE.md`](../CLAUDE.md) so the file agents load every session
holds rules only. This is the *why* and the *how it fits together*; the rules
themselves stay in `CLAUDE.md`. Engineering incidents, status and risks live in
[`ENGINEERING.md`](ENGINEERING.md).

## Goal
A Windows desktop voice assistant. An always-on microphone listens for the wake
word "Jarvis" / "Hey Jarvis", transcribes the spoken question locally, sends the
text to the Claude API with a Jarvis-personality system prompt, and reads the
response back through the speakers via TTS. Inspired by Tony Stark's J.A.R.V.I.S.:
courteous, dryly witty, concise.

The interesting part is not the voice loop — it is everything hung off it: an
agentic tool layer (36 tools), proactive background monitors, a vision/security
subsystem, a phone client, and a set of engineering conventions strict enough to
keep an always-on process honest.

## Stack and the reasons for it
- **Language**: Python 3.12 on Windows.
  - Windows-native, not WSL: audio device access. WSL2 audio bridging is
    unreliable for always-on real-time listening.
- **Wake word**: [openWakeWord](https://github.com/dscripka/openWakeWord)
  - MIT, fully local, no API key or account. Ships a pre-trained `hey_jarvis`
    model. CPU-only, ~3-5% continuous utilization.
  - Slightly higher false-positive rate than commercial alternatives (Porcupine);
    tunable via a confidence threshold. Porcupine was the original pick but now
    requires a company email, which rules it out for an open personal project.
- **Speech-to-text**: [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)
  - Local Whisper on CPU; the small/base model is plenty for short commands.
    No internet required — question audio never leaves the machine.
  - Optionally offloaded to a CUDA box on the LAN over a small HTTP server
    (cuts transcription 5-10 s → 1.5-2.5 s); falls back to local on any failure.
- **LLM**: Anthropic Python SDK (`anthropic`)
  - Default `claude-sonnet-5` (`CLAUDE_MODEL` overrides). Haiku for the cheap
    background jobs (session summarizer, prediction miner). Opus only if a
    request genuinely needs more reasoning.
  - **Thinking is explicit.** Sonnet 5 runs *adaptive* thinking when the
    `thinking` param is omitted. Voice and background paths pass
    `thinking={"type": "disabled"}` (latency, plus small `max_tokens` budgets
    would be truncated by an unplanned thinking block); engineer mode passes
    `{"type": "adaptive"}`.
  - **Prompt caching** on the system prompt — it is reused every turn. Per-turn
    volatile context (clock, speaker identity) rides a *second, uncached* system
    block so it never invalidates the cache.
  - **Streaming** so TTS can start before the reply is complete.
- **Text-to-speech**: [`edge-tts`](https://github.com/rany2/edge-tts) primary,
  [`pyttsx3`](https://pyttsx3.readthedocs.io/) fallback.
  - Edge is a free Microsoft online voice, surprisingly good. pyttsx3 is offline
    (Windows SAPI) — the graceful degradation path when Edge is unreachable.
- **Audio I/O**: [`sounddevice`](https://python-sounddevice.readthedocs.io/) —
  cleaner than PyAudio, handles streaming well.
- **UI**: `pystray` tray icon (four states) + a `customtkinter` console window.
- **Vision**: `opencv-python` + `ultralytics` (YOLOv8n person detection) +
  `face_recognition`/dlib for the enrolled-face auth path.
- **Acoustic classification**: PANNs Cnn14 (`panns_inference`) — 527 AudioSet
  classes, ~0.2 s CPU inference.
- **Speaker ID**: Resemblyzer d-vectors (256-d), cosine similarity.
- **Env**: `python-dotenv`. **Async**: `asyncio` around the listen → process →
  respond cycle; background subsystems are daemon threads.

## Key files in detail
- `main.py` — the composition root, and *only* that: one `main()` that loads
  config, builds subsystems, starts threads, and waits. It was 2,805 lines
  until the 2026-07-28 extraction split it four ways (below).
- `src/listen_loop.py` — the voice path and the conversation-level state
  machine above a single turn: wake-word arming, barge-in, the follow-up
  window, conversation mode, interpreter mode, the speaker gate, dismissals.
- `src/turn_runner.py` — one turn, end to end: history, streaming, the tool
  loop, sentence-chunked TTS, finalisation. Its collaborators
  (`stream_response`, `speak`, `speak_streaming`, `MemoryStore`,
  `_seal_session`) must stay resolvable as module-level globals — that is
  the seam `turn_runner_test.py` patches, and `turn_runner_patch_test.py`
  exists to fail if a refactor ever breaks it.
- `src/bootstrap.py` — subsystem assembly: the two optional Plex connections,
  the announcement fan-out, the remote console, the status registry, ordered
  shutdown. Everything that *builds* a thing and returns a handle.
- `src/logging_setup.py` — stdout/stderr wiring for the three launch modes.
- `jarvis.pyw` — silent launcher (pythonw, no console); logs to
  `%LOCALAPPDATA%\Jarvis\jarvis.log`.
- `jarvis_watchdog.pyw` — supervisor; respawns `main.py` on crash.
- `src/wake_word.py` · `src/speech_to_text.py` · `src/llm.py` ·
  `src/text_to_speech.py` · `src/audio.py` — the spine's modules.
- `src/config.py` — loads `.env`, holds all runtime tunables.
- `src/ui.py` / `src/console.py` / `src/tray.py` / `src/hud.py` — the UI fan-out
  facade and its three sinks (console window, tray, ambient overlay).
  `src/reactor.py` — the shared arc-reactor renderer behind the console orb and
  the HUD. Frames are **pre-rendered per (size, colour) on a daemon thread and
  cached**, never drawn live: drawing one costs 9-25 ms, and at 20-30 fps that
  would be a permanent 55-74% of a core competing with the audio threads. Both
  callers keep their vector drawing as a fallback and use it until frames warm.
- `src/security.py` · `src/sound_detector.py` · `src/speaker_id.py` ·
  `src/face_auth.py` — the sensing subsystems.
- `src/remote_console.py` / `src/remote_pwa.py` / `src/discord_bot.py` — the
  remote clients.
- `scripts/run_all_tests.py` — the unified regression gate.
- `tests/*_test.py` — the regression suites; everything here runs in the gate.
- `docs/MILESTONES.md` — the engineering log's **index** (intro, a curated
  "Start here", and generated contents); the entries themselves live in
  `docs/milestones/part-N.md`. `docs/CODE_AUDIT.md` — the consolidation-pass
  audits. `docs/ENV_VARS.md` — config inventory.

The remaining ~50 `src/` modules are individual tools and monitors (weather,
news, TMDB, reminders, knowledge base, …). They are deliberately **not**
enumerated here — a full manifest rots. Grep `src/llm.py` for the tool schemas;
that file is the authoritative index of what Jarvis can do.

## Architecture

### The spine
`wake word → capture → STT → LLM (agentic, streaming) → TTS`, with the tray/
console/HUD reflecting each phase. `TurnRunner` (`src/turn_runner.py`) owns a
single turn: it appends to history, streams the response, runs the tool loop,
feeds sentences to TTS as they complete, and finalizes (memory write,
telemetry).

Turns arrive from **four origins** — local voice, the console text box, the
phone PWA, and a Discord channel — through one `text_queue`. The origin is a
first-class parameter: it derives `speak` (never talk to an empty room for a
phone-typed message) and `restricted` (the least-privilege tool surface).

### The tool layer
Claude drives an agentic loop (max 8 iterations) over:
- **Server-side**: `web_search`, `web_fetch`.
- **Client-side data tools** (all fail-soft, all read-only): weather + NWS
  weather alerts, sports, news (RSS), TMDB film/TV/person/watch-providers, game
  info + playtime, WolframAlpha, a personal knowledge base (hybrid FTS5 +
  embedding search over a curated markdown corpus), conversation recall
  (full-text + semantic search over verbatim session transcripts), reminders,
  and composition tools (`get_briefing`, `get_good_night`, `status_report`,
  `what_did_you_hear`).
- **Client-side action tools** (gated): `system_control`, `pc_shell`
  (read-only 18-verb allowlist), `run_code` (Python in an ephemeral
  network-less Podman container), `update_jarvis`, file/screen/camera capture.
- **MCP**: a Plex Media Server MCP subprocess bridged into the same tool loop
  behind a voice allowlist.

### Subsystems (all optional, all fail-soft)
- **Vision security** — YOLOv8n person detection on a webcam; a pet-rejection
  height heuristic; a challenge-response flow (spoken passphrase *or* enrolled
  face, first match wins) before any deterrent fires; evidence snapshots; push
  notification. Arm/disarm by voice, tray, or a geofence webhook.
- **Acoustic awareness** — PANNs classifier on its own input stream; fires on a
  small set of salient classes. While armed it also triggers a look-and-describe
  (camera frame → Claude vision → push).
- **Proactive monitors** — homelab health, calendar (pre-event announces),
  severe weather, and an "anticipation" layer that fuses the world-state and
  asks the model for at most one genuinely useful cross-domain insight per tick
  (most ticks correctly produce nothing).
- **Remote clients** — a token-gated `websockets` server + PWA (type, talk,
  hear replies, see state), and a Discord bot bridge.
- **Reliability** — a crash watchdog, a mic-session supervisor, a memory
  watchdog, atomic+fsync'd JSON stores.

## Multilingual support (German default, English + Spanish on request)
Everything the user hears or sees in normal mode is German; the owner is
addressed as "Master". Speech input stays multilingual.

- **Auto-detect per turn.** faster-whisper returns `detected_language` with each
  transcript. It is stored with the turn and picks the fixed fallback lines
  (apology / empty-reply ack have en/es variants), but it no longer picks the
  reply language: the system prompt fixes replies to German, and
  `turn_runner.REPLY_LANGUAGE` voices them with the German voice.
- **Voice mapping** (`VOICE_BY_LANG` in `src/text_to_speech.py`):
  ```python
  VOICE_BY_LANG = {
      'de': 'de-DE-ConradNeural',   # default reply voice
      'en': 'en-GB-RyanNeural',     # calm British male
      'es': 'es-MX-JorgeNeural',    # formal male, butler-like
  }
  ```
  An explicitly requested English reply is still voiced by the German voice.
- **What stays English**: tool results only Claude reads, prompts/tool
  descriptions, logs (self_review/self_status parse them), identifiers and
  wire values. Scheduled briefings are composed in English (the composers are
  also tool results) and translated to German at fire time
  (`reminders._translate_or_keep`, wired to `llm.stream_translation`).
- **System prompt addendum** for an explicit Spanish request: formal *usted*,
  Latin American conventions.
- **Interpreter mode** is the recombination payoff: "be my interpreter" stops
  Jarvis answering and makes him *relay* — each utterance translated into the
  other language of the configured pair and spoken in that language's voice,
  continuously, with no wake word between turns, until "stop interpreting"
  (German: "sei mein Dolmetscher" / "Dolmetschen beenden"). A German owner sets
  `JARVIS_INTERPRETER_LANGS=de,es`; the start/stop confirmations follow the pair.
  Built from the per-turn language detection and voice map that already existed.
- **Wake-word caveat**: the `hey_jarvis` model is English-trained, so a
  Spanish-accented "Jarvis" (soft J) triggers less reliably. Mitigations, in
  order of preference: lower the confidence threshold; train a custom wake word;
  fall back to a more phonetically robust word.

## Runtime state that is not in git
`%LOCALAPPDATA%\Jarvis\` holds everything the process *learns*, and none of it
is in this repo. Most of it genuinely rebuilds — logs rotate, `diagnostics/`
regenerates, `knowledge.db` is only an FTS5 cache of the `jarvis-knowledge`
repo. Two things do not: **`sessions/` + `summaries.jsonl`** (verbatim
conversation history — the corpus `recall_conversation` searches, and
unreconstructable by any means) and **`speakers/`** (voice enrollments,
rebuildable only by having each person re-enroll aloud).

`scripts/backup_state.ps1` replicates ~675 KB of that 18.6 MB tree to the
private `jarvis-state` repo. **It selects by ALLOWLIST, and that is
load-bearing** — the same directory holds a TLS private key, a Ring API token,
and `security/` camera evidence (photographs of whoever walked past). A
denylist starts replicating those the day someone drops in a file its patterns
did not anticipate; an allowlist fails closed. When you add a new durable
store, it is NOT backed up until you add it to `$include` in that script.

## `tests/` versus `scripts/`
**The directory is the boundary.** Anything in `tests/` is collected by the gate
automatically — adding a suite there is the whole registration step. Nothing in
`scripts/` is ever collected, whatever it is named: that is where the
operational entry points (`run_all_tests.py`, `doctor.py`, `js_parse_gate.py`)
and the hand-run instruments live. Several of those instruments cost live API
calls (`effort_probe.py`, `web_search_version_probe.py`) or need hardware and
run for hours (`leak_repro.py`, the `*_soak.py` pair) — they must never be
picked up by CI, and a directory guarantees that where a naming convention only
asks politely.

## TLS certificate (phone PWA / geofence webhook)
Tailscale + Let's Encrypt. A daily scheduled task (`JarvisTlsCertRenew`) runs
`scripts\renew_tls_cert.ps1`; renewal is a no-op until 30 days before expiry.
```powershell
pwsh -File scripts\renew_tls_cert.ps1            # renew if due
pwsh -File scripts\renew_tls_cert.ps1 -Force     # renew now
pwsh -File scripts\renew_tls_cert.ps1 -Install   # (re)register the daily task
```
**The cert is 90 days and a running Jarvis loads it ONCE at startup.** So a
renewal only takes effect after a restart, and an expiry produces *no symptom
on this machine at all* — the failure is on the client side of the handshake,
so the only sign is an error on the phone. Hence both a scheduled renewal and
a `doctor.py` line reporting days-remaining.
