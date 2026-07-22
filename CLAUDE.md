# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev            # create .venv and install deps + pytest (dev also pulls NumPy)
uv sync --extra audio          # add the opt-in audio extra (NumPy) for tempo extraction
uv run pytest                  # full test suite (pythonpath=src is set in pyproject.toml)
uv run pytest tests/test_bridge.py::test_name   # single test
```

If `uv`/`pytest` are unavailable, run the standalone integration check, which executes
`tests/test_bridge.py` by hand plus an import smoke test of every module and a `mcp`
dependency check — no pytest required:

```bash
.venv/bin/python scripts/run_checks.py
```

Other entry points (both defined as `[project.scripts]` in `pyproject.toml`):

```bash
uv run abletongpt              # start the MCP server (stdio transport by default)
uv run abletongpt-doctor       # diagnose bridge config, Remote Script install, connectivity
ABLETONGPT_TRANSPORT=streamable-http uv run abletongpt   # HTTP mode for ChatGPT/remote clients
python3 scripts/setup_macos.py # macOS one-shot: deps, shared token, Remote Script install
```

## Architecture

Data flows in one direction through four layers:

```
MCP client (ChatGPT/Codex) → server.py (FastMCP tools) → bridge.py (JSON/TCP)
                                                              → Remote Script → Live Object Model
```

- **`src/abletongpt/server.py`** — the entire MCP tool surface (`FastMCP`) and the validation
  boundary. Every user-facing capability is a `@mcp.tool()` here. Tools either delegate to a pure
  logic module (planning) or call `bridge.call(command, **params)` (Live mutation). This is the
  only place that talks to both the pure engines and the bridge.
- **`src/abletongpt/bridge.py`** — `AbletonBridge.call()` sends newline-delimited JSON
  (`{command, params, token}`) over a localhost TCP socket and reads one line back. `BridgeConfig`
  **enforces localhost-only** at load time (rejects any non-loopback host).
- **`ableton_remote_script/AbletonGPT/__init__.py`** — a `ControlSurface` that runs *inside the
  Live process*. It listens on the TCP port and dispatches commands. All Live Object Model access
  is marshalled onto Live's main thread. This file is Python 2/3-compatible (`from __future__
  import …`, no f-strings) because Live's embedded interpreter demands it — keep it that way, and
  ship the `.py` source (never a stale `.pyc`). It is **not** installed from the repo path; the
  user copies it to `~/Music/Ableton/User Library/Remote Scripts/AbletonGPT_MCP/__init__.py`.

Pure logic engines (no Live connection, deterministic, unit-testable in isolation):

- **`composition.py`** — beginner song sketches and professional deterministic MIDI generation
  (degree progressions, voice-leading via nearest-inversion, density/swing/humanize, `seed`).
- **`contextual.py`** — read-only analysis of an existing MIDI clip + complementary-part planning.
- **`instruments.py`** — role/genre/mood → native-instrument selection with ordered fallbacks.
- **`vocal.py`** — lyrics → editable Vocal Guide MIDI and the external-render handoff contract.
- **`loudness.py`** — offline BS.1770 / EBU R128 analysis of WAV/AIFF; reads the file, never writes.
- **`audio.py`** — offline audio-track feature extraction (tempo, key, chord progression,
  monophonic melody). Reuses `loudness.py`'s reader and needs the optional `audio` extra (NumPy,
  imported lazily); the base install stays stdlib-only. Reads the file, never writes.
- **`snapshots.py`** — normalizes the read-only `get_state` + `get_mix_snapshot` bridge responses
  into a stable, meter-free mix-state snapshot (`build_snapshot`) and diffs two snapshots
  (`diff_snapshots`). Pure and deterministic (timestamp passed in, not read from a clock).
- **`transcription.py`** — bridges audio analysis to MIDI creation: `build_midi_from_melody`
  converts an `extract_melody` result + tempo into `create_midi_clip`-ready notes in beats.
  Pure, stdlib-only (no NumPy); the NumPy extraction stays in the server tool. Used by the
  `plan_/create_midi_from_audio_melody` plan/create tool pair (audio-to-MIDI).
- **`warp.py`** — `build_warp_alignment` compares a clip's warp-marker sample times against
  detected onset times and reports how well they align (markers-on-transients, onset coverage,
  offset stats). Pure, stdlib-only. Warp-marker *writing* is not exposed by the Live API, so this
  stays read-only (report only).
- **`reference.py`** — `build_reference_comparison` compares two audio *profiles* (loudness + tone
  + per-band balance + stereo image) and returns mix-minus-reference deltas, a weighted 0-100
  `match` score with per-dimension breakdown and the weakest dimension, plus plain-language mixing
  guidance. Pure, stdlib-only; the server tool builds the profiles from `loudness.py` + `audio.py`
  and never applies a change (report only).
- **`targets.py`** — curated, built-in genre mix/master *targets* (`GENRE_TARGETS`, `list_targets`,
  `get_target`), each a partial reference profile (LUFS/LRA/true-peak/crest + five-band balance;
  tone and stereo left unset) so a mix can be compared against a target with no reference file.
  Pure, stdlib-only; feeds the same `reference.py` comparator via the `compare_mix_to_target` tool
  (report only). Numbers are directional approximations, not measured from a specific master.

## Two separate ports — do not confuse them

- `ABLETONGPT_PORT` (default **9877**) — the Ableton TCP bridge. Shared by `bridge.py` and the
  Remote Script. **Never expose this externally.**
- `ABLETONGPT_MCP_PORT` (default 8000) — the FastMCP HTTP server port (streamable-http mode only).

## Config resolution

`config.py::setting()` resolves each value as: `ABLETONGPT_<NAME>` env var → `config.json` →
default. The config file lives in the OS app-support dir (macOS:
`~/Library/Application Support/AbletonGPT/config.json`), overridable via `ABLETONGPT_CONFIG`. The
Remote Script reads the same file/env independently because it runs in Live's process.

## Invariants to preserve

These are deliberate design constraints, enforced across `server.py`, `bridge.py`, and the Remote
Script. New tools must uphold them:

- **Plan/create split.** Planning tools (`plan_*`, `analyze_*`) are read-only and must not call the
  bridge to mutate. A separate `create_*`/`apply_*` tool performs the change after review.
- **No destructive operations.** No arbitrary Python/shell execution, no track/file deletion, no
  Live Set overwrite/save, no master export. Do not add tools that do these.
- Native-instrument insertion is limited to an **allowlist** (`ALLOWED_NATIVE_INSTRUMENTS` in the
  Remote Script), one track per call, and refuses tracks that already have an instrument.
- Browser-preset loading (`load_browser_preset` → `load_preset`) is kept **strictly additive**: it
  loads one browsed item onto one track and refuses tracks that already contain an instrument, so a
  load can never replace an existing device. Browsing (`browse_device_presets`) stays read-only.
- Arrangement-locator placement (`create_arrangement_locators_from_structure` → `add_locators`) is
  **additive**: it skips any position that already has a cue (never toggles/deletes one) and
  restores the playhead afterward. It uses `set_or_delete_cue`, so the no-cue-at-position guard is
  what keeps it from deleting.
- Device parameter changes are range-checked; Live-disabled or macro-controlled parameters are
  rejected. Always `get_track_devices` first — parameter indices/values are device-specific.

## Testing note

The only test file is `tests/test_bridge.py`. `scripts/run_checks.py` deliberately runs it without
pytest so contributors without dev deps can still validate; if you add test files, wire them into
that script too, or they won't run in the no-pytest path.
