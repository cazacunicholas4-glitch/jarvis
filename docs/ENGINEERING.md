# JARVIS — Engineering rules in depth, status, risks, backlog

Moved out of [`CLAUDE.md`](../CLAUDE.md), which keeps each rule as a one-liner.
This file holds the incidents behind the rules, the full feature status, the
known risks and the backlog. Architecture and stack background:
[`ARCHITECTURE.md`](ARCHITECTURE.md). Per-milestone history:
[`MILESTONES.md`](MILESTONES.md). Consolidation audits:
[`CODE_AUDIT.md`](CODE_AUDIT.md).

## Engineering rules — the reasoning and the incidents behind them
These are the conventions that keep an always-on, always-listening process
maintainable.

- **Fail soft, never crash the loop.** Every optional component (TTS backend,
  model download, a network tool, an MCP subprocess) must log and degrade. A
  component that cannot do its job returns an honest "not configured" /
  "unavailable" string rather than raising.
  **TWO threads must not die, not one (M100).** The listening loop is the
  obvious one. The other is the **Announcer** — the single path by which Jarvis
  speaks unprompted, so its death takes reminders, weather, homelab *and every
  security alert* with it, silently and with no symptom anyone can report. It
  died once, one second into a session, on an unguarded Tk call, and the machine
  ran mute for twelve hours overnight. Both loops now guard their whole per-item
  body; the UI fan-out sinks (`_console_call`, `_remote_call`) are defensive on
  both sides, because decoration must never be able to kill a worker thread.
- **Least privilege, enforced server-side.** Remote origins (phone, Discord) get
  a *restricted tool surface*: no shell, no system control, no filesystem, no
  code execution, no self-update. This is enforced at **two gates** — the tool
  list is filtered before it is offered to the model, *and* the executor
  re-checks the deny list by name. It is never prompt-only. Re-opening a single
  tool for a single origin is a surgical per-origin allowance, not a boundary
  flip. The guiding line: *Jarvis, not Ultron.*
- **Confirmation-gate every mutating action.** A destructive or irreversible
  verb (kill a process, restart/stop a service, cycle DHCP, pull code and
  restart) takes a `confirm: bool` parameter; calling it without confirmation
  returns a *description* of what would happen. **The gate must carry the
  information needed to evaluate it** — e.g. self-update previews the actual
  pending commits rather than asking "shall I pull?". A gate the user cannot
  evaluate is procedure, not safety. Privileged verbs additionally require the
  process to be running elevated, which is an opt-in tray action, never the
  default.
- **The container is the boundary for arbitrary code.** `run_code` cannot be
  allowlisted (arbitrary code is arbitrary), so it is contained instead:
  ephemeral Podman, `--network=none`, no host mount, CPU/memory/PID caps, hard
  timeout, non-root. Zero host blast radius, therefore no confirmation gate —
  but a full audit trail in the log.
- **Measure before you tune.** Do not adjust a threshold from a symptom. Get the
  numbers first — the project has repeatedly found that the obvious knob was the
  wrong one (an inference model was 17× too slow to ship, so it was replaced
  rather than tuned; a detection threshold was the weak lever where an amplitude
  floor was the real discriminator; a memory leak was attributed to the ML model
  for two milestones before a harness proved it was the video-capture handle).
  Correlate a score with its *input*, never tune on scores alone.
  **Before tuning a threshold, prove one EXISTS (2026-08-22).** Label the
  positives and negatives and check `min(POS) > max(NEG)`. The
  `knowledge_remember` dedup metric scored 0.750 vs 1.000 — it *overlapped*,
  so no threshold could have worked and picking a higher number was motion,
  not a fix. A metric that cannot separate a labelled set is unusable, not
  mis-tuned. **And if a fix also MIGRATES data, re-validate after the
  migration** — that same fix shipped a validation case its own corpus
  consolidation had silently invalidated in the same commit.
- **Cooperative gates have two sides.** Heavy background CPU work (vision,
  acoustic inference) yields while audio is playing, via a shared counted event.
  A gate is only as complete as (a) every *consumer* that opts into yielding and
  (b) every *producer* — every code path that speaks — that raises it. Both
  halves have been the source of a regression; both are now tested.
  **Authentication must GRANT something (M101).** The voice lock and the
  security challenge are two gates on the same person; for a while, clearing
  the second bought nothing at the first, so the user spoke the passphrase, was
  accepted, and was then refused twice saying "stand down". A successful
  challenge now opens a short trusted session, cleared on arm and disarm.
  **And it must cover STARTUP, not just the steady state (M99.1).** The gate
  covered the watcher's poll loop and the dlib warm but not the YOLO *model
  load*, so arming stuttered its own confirmation every single time — the one
  burst that is guaranteed to coincide with speech, because arming is what
  triggers both. When adding a subsystem, gate its load path, not only its loop.
- **Cost discipline.** Sonnet by default, Haiku for background jobs, prompt
  caching on the system prompt. Escalate deliberately, not reflexively.
- **Latency over cleverness.** Short replies. This is voice. Stream Claude's
  response and feed TTS in sentence chunks rather than waiting for the full
  reply — that is what makes the interaction feel immediate rather than
  transactional.
- **Rule of three before extracting.** Two call sites is a coincidence; three is
  a pattern. Shared helpers (`http_util`, `atomic_io`, `gates`) were each
  extracted on the third consumer, not speculatively.
- **New durable state uses `src/atomic_io.py`.** fsync-before-replace, unique
  temp names, Windows `os.replace` retry. The target machine has no UPS, so an
  unclean power loss is a realistic failure mode, not a theoretical one.
- **A bug that a test would have caught earns a test.** The regression gate grew
  from a handful of suites to 55 exactly this way. **Check the FIXTURE is big
  enough to express the bug**: the dedup suite already had a
  "distinct facts stay separate" case and it passed for the wrong reason —
  its fixture corpus held one short note, and the defect only appears against
  a large one. A green negative case over a toy fixture asserts nothing.
- **Fix the failure mode, not the instance.** When a fix lands on a component,
  find its peers and ask whether they share the defect. M99 cost a milestone to
  a `latency="high"` + throttled-callback-log fix that was applied to the
  acoustic capture stream and not to the main microphone — in the same commit
  that touched both files. Symmetric components (the two capture streams, the
  capture and playback rings, every origin in the tool gate) fail symmetrically;
  a fix to one is a checklist for the rest, not a closed ticket.
- **QoL consolidation cadence.** Periodically run a no-new-features hardening
  pass: verify the regression net is green, run read-only audits across the
  tree, then fix in *risk order* (correctness → latent → cosmetic), gating each
  fix. Trigger on any of: (a) ~20 milestones since the last pass, (b) a
  regression recurs that a test would have caught, or (c) a core file crosses a
  god-file threshold (a 1,500-line `main()` is a signal regardless of milestone
  count). The count is the backstop; (b) and (c) are the real triggers — debt
  accrues with coupling events, not with the calendar. Template and findings in
  [`CODE_AUDIT.md`](CODE_AUDIT.md).
- **Model migrations: verify verbosity, not just tool routing.** A model swap
  can leave routing perfect while default reply length triples — which, on a
  voice interface, is a regression measured in minutes of unwanted speech.
  Probe both.

## Current status
The project is feature-complete for its intended use and running in production
as a supervised always-on process. ~101 milestones, then the German-default
rework (`0c8e9c8`, `56b02a0`, `c513cce`). The regression gate is at 58 gates
(55 test suites + 3 structural): 58/58 green on the stable Windows baseline.

**Latest hardening** — full write-ups in [`CODE_AUDIT.md`](CODE_AUDIT.md) and
the commit messages:
- **Pass #6** (`5186705`, 2026-08-22): `knowledge_remember` silently dropped
  new facts while reporting success. The dedup metric was replaced by
  measurement (Ochiai, cut at 0.40); the knowledge corpus is now written
  atomically; three direct-but-transitive imports declared (`torch`,
  `icalendar`, `av`).
- **`fd36cc1`** (2026-08-21): `knowledge_remember_test` was rebuilding the real
  `knowledge.db` — fixed with `JARVIS_KNOWLEDGE_DB`; restated facts are now
  merged into the existing note instead of duplicated.
- The top defect of each of the last two passes sat in the newest code in the
  tree: treat "written this week" as the highest-yield place to look.

**Working:**
- The core loop: wake word → local STT (multilingual auto-detect; replies in
  German) → streaming, prompt-cached, agentic Claude call → streaming TTS, with
  a tray icon, a console window with live transcript and waveform, and an
  optional ambient overlay. Both the console orb and the overlay render the
  shared pre-rendered arc reactor (`src/reactor.py`).
- **Conversational**: a follow-up window after each reply (no wake word needed);
  a persistent hands-free conversation mode; barge-in (interrupt mid-reply by
  saying the wake word).
- **36 tools** across web, data, personal knowledge, memory recall, reminders,
  diagnostics, and gated system actions. See [`ARCHITECTURE.md`](ARCHITECTURE.md).
- **Memory**: in-process turn history + a JSONL session store, summarized at
  session boundaries and recalled into the system prompt; a separate curated
  knowledge base (hybrid keyword + embedding retrieval); full-text/semantic
  search over verbatim past conversations.
- **Senses**: webcam (vision security, on-demand snapshots), screen capture,
  acoustic classification, per-turn speaker identification.
- **Proactive**: homelab monitoring, calendar pre-event announces, severe-weather
  alerts, scheduled briefings, an anticipation layer, and a quiet-hours policy
  that lets important announcements pierce while routine ones defer.
- **Long-horizon work (M91/M92)**: research tasks that outlive the turn, run on
  Anthropic's Managed Agents and polled to completion, delivered when ready
  (and held back through quiet hours). Schedulable — "every Monday, look into
  X" reuses the existing reminder scheduler. **Off unless
  `JARVIS_BACKGROUND_AGENTS=1`** — see the privacy exception in `CLAUDE.md`.
- **Self-diagnosis (M93)**: `self_review` clusters this machine's own logs
  across sessions and restarts into ranked recurring problems, read-only.
- **Clients**: local voice, console, a token-gated phone PWA (type / push-to-talk
  / reply audio / state), and a Discord bridge — the last two on a restricted
  tool surface.
- **Reliability**: crash watchdog, mic-session supervisor, memory watchdog,
  atomic durable writes, self-update behind a confirmation gate.

## Known unknowns and risks
- **Wake-word false positives.** Background speech or media saying "Jarvis" can
  trigger a capture. The confidence threshold is the knob; the opt-in speaker
  gate (answer only enrolled voices) is the stronger mitigation.
- **TTS prosody.** Edge is good, not perfect. Voice choice and pacing are the
  levers.
- **Audio device selection.** Multi-device machines need `JARVIS_MIC_DEVICE`
  pinned; note that budget microphones often enumerate under a generic OEM
  string, so identify the device by unplug-diff rather than by guessing a name.
- **Armed-mode audio starvation is OPEN, and now instrumented (M99).** While
  armed, the capture stream drops samples: 565 PortAudio input overflows in a
  69-minute armed window vs 1 in the 112 unarmed minutes before it. This is a
  4-core box running openWakeWord, PANNs, YOLO and dlib concurrently, and a
  single 90 ms YOLO call straddles the 80 ms audio callback budget — so the
  cost is GIL starvation, not any one subsystem. It degrades speaker ID (0.82
  unarmed → 0.64 armed) and is the likely source of the armed-only TTS stutter.
  **Three candidate fixes were measured and rejected — do not re-attempt them
  blind:** `latency="high"` is a no-op (`sd.default.latency` is already
  `['high','high']`, and an explicit blocksize pins the ring regardless);
  lowering capture resolution makes YOLO *slower*; bounding the capture queue
  would gap the STT clip. The remaining real levers are less armed CPU work, or
  an explicit numeric ring depth traded against the "first audio within 1 s"
  target. **Take armed-mode numbers before choosing** — `[audio] status: input
  overflow` (capture, with queue depth) and `[tts] output underflow` (playback;
  this one is literally the audible stutter and was invisible until M99). Both
  logs are rate-limited, because a per-event log inside a starved audio callback
  feeds the stall it reports.
- **Fully hands-free talk-over** (interrupting without the wake word) was built
  and shelved: once the assistant's own echo is cancelled, an energy gate fires
  on *any* residual sound, because it detects the presence of sound, not the
  intent to interrupt. The code is kept behind a default-off flag for a
  headset/quiet-room scenario. Wake-word barge-in is the robust UX.
- **Test isolation gap.** `tests/scheduled_briefing_test.py` adds and cancels a
  reminder in the real `%LOCALAPPDATA%\Jarvis\reminders.json` (no
  `LOCALAPPDATA` override, no `finally`). Harmless on a dev box; on the
  production machine it races the live reminder store.
- **Launcher interpreter path.** `jarvis.pyw:32` and `jarvis_watchdog.pyw:63`
  hard-code `venv\Scripts\pythonw.exe`; the dev venv is now `.venv`. Without a
  `venv\` folder they run under whichever interpreter started them.

## Possible future work
Neutral backlog; nothing here is committed. The standing discipline is
**iterate on real usage** — do not pre-build.

- Multi-camera / RTSP support (OpenCV already supports it; needs a camera
  registry and a `camera` parameter).
- Additional MCP servers through the existing bridge (home automation, 3D
  printing) — same async↔sync wrapper and voice allowlist. **Home Assistant is
  the concrete next one and is deliberately NOT built**: there is no HA
  instance on this network to validate against, and an integration written
  against documentation alone would ship untested against the one thing that
  matters (the real entity registry). Build it when HA is actually installed.
- Growing the knowledge corpus. The hybrid retrieval is correct but the corpus is
  currently too small to demonstrate an aggregate win; size, not the algorithm,
  is the limiter.
- Finer-grained per-verb tuning in `pc_shell` / `system_control` as real use
  cases prove out.
- A custom multilingual wake-word model for non-English accents.
- Extracting the text/voice intent dispatch (a real hot-path refactor; wants a
  test at the right level first). **Measured 2026-08-22:** `listen_loop()` is
  **945 lines taking 15 parameters**, and its body is largely one 598-line
  closure (`_voice_session_loop`) capturing **11 of them** plus a `nonlocal`.
  That capture is why it resists extraction — it needs a small state object
  (a `VoiceSession` holding the captured collaborators), not a longer
  parameter list. This is the sharpest structural item in the tree, and a
  worse smell than any large *file*: by contrast `security.py`'s 1,714 lines
  are 36 methods with the largest at 181, which is a big class, not a god
  function. Deferred twice now (passes #5 and #6) for the same reason — hot
  path, no correctness payoff, needs its seam tested first.
