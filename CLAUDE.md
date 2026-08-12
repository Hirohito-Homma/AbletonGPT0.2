# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sends and return tracks

`set_track_send` writes a track's send amount; `create_return_track` adds a
return. Both were verified against a running Live 12 Beta: writing 0.42 to send 1
read back as 0.42 and Live displayed -23.2 dB on B-Delay.

Sends are `DeviceParameter` objects on `track.mixer_device`, the same kind of
object as `volume` and `panning` -- which is why they are writable, and how that
was established before any of this was built.

`set_clip_send_envelope` automates a send across a Session clip, which is what a
dub delay throw actually is. `set_clip_parameter_envelope` cannot do it: that
resolves a parameter in the *device chain*, and a send is on the mixer. Both go
through one writer in the Remote Script, so the left-continuous `value_at_time`
handling is shared.

`create_return_track` names are prefixed by Live: asking for "KIHACHI Dub"
produces "C-KIHACHI Dub", following A-Reverb and B-Delay. There is no delete
command; removing a return is a manual action in Live.

KIHACHI plans enter through `jobs import-kihachi`, which is a pure preflight: it
accepts plan version 0.1, `planned_not_applied`, the existing `set_tempo`, and only
the six additive core operations (`create_track`, `apply_live_instrument_selection`,
`apply_live_drum_kit`, `create_midi_clip`, `set_clip_send_envelope`,
`copy_session_clip_to_arrangement`).
Instrument selection accepts a semantic role/genre/mood, then AbletonGPT owns the
native-device candidates and sends `insert_first_available_instrument` to Live.
Resume accepts one candidate-matching instrument; a different existing instrument
is never replaced. Drums stay outside *instrument selection* — an empty Drum Rack or
Impulse is silent — and go through `apply_live_drum_kit`, which discovers a real kit
by walking the read-only browser and verifies the readback. The resulting saved
JobPlan remains pending until a separate `jobs run`/`resume`; unknown operations or
bad parameters reject the whole import before any Live bridge call.

**Reloading the Remote Script needs a full Live restart.** Re-selecting the
control surface re-instantiates the class but Python keeps the module in
`sys.modules`, so the file is never re-read -- confirmed by the file's access
time not moving. The script is installed in *two* places on this machine and both
have to be updated:
`~/Music/Ableton/User Library/Remote Scripts/AbletonGPT_MCP/` and the same path
under the external drive's `12.４b` User Library — that is
`/Volumes/NO NAME/12.４b/...`, and the `４` is **full-width**, so a copied-and-pasted
half-width `12.4b` will not match. Delete `__pycache__` in both (only the external
copy tends to have one).

**Live loads the external copy.** Updating only the home copy leaves Live running
the old code through a restart, which reads as "the restart did not work". Check
the reload actually took by looking for a field the new code adds — `get_state`
returning `scenes`, not just `scene_count`.

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
- **`meters.py`** — `build_live_headroom_report` turns a window of Live master `output_meter_level`
  samples (Live's momentary peak meter, 0..1 — **not** LUFS) into a peak/headroom check against a
  `targets.py` target's true-peak ceiling. Pure, stdlib-only; the `compare_live_meter_to_target`
  server tool samples the meter over a short window (needs the set playing; Remote Script backend
  only — the Extensions SDK exposes no meter). Peak-based and report-only; for a calibrated LUFS
  gap it points to the offline `compare_mix_to_target` path.
- **`harmony.py`** — Camelot-wheel harmonic-mixing key compatibility. `parse_key` accepts
  `"C major"`/`"Am"`/`"F#m"`/flats/Camelot codes; `build_key_compatibility` reports the
  relationship (identical/relative/adjacent/two-step/diagonal/distant) + a 0-100 score;
  `suggest_compatible_keys` lists the safe ring (same/relative/±1 fifth). Pure, stdlib-only.
  Tools `analyze_key_compatibility`/`suggest_harmonic_keys` (two keys) and
  `analyze_audio_key_compatibility` (two files via `estimate_key`). Report only (never transposes).
- **`transpose.py`** — `build_transpose_plan` shifts every note in a `get_midi_clip_notes` clip by
  a constant semitone offset (a chromatic shift = a true key change; out-of-range notes are
  octave-folded, note count preserved); `shift_to_target_pc` computes the offset to move a source
  tonic to a target one. Pure, stdlib-only. The `plan_/apply_transpose_midi` pair takes explicit
  `semitones` or a `target_key` (key name/Camelot via `harmony.parse_key`, source key detected via
  `contextual.analyze_midi_context` unless given); apply writes back through the undoable
  `apply_expression_to_clip` path with a fingerprint guard. Edits only the target clip's notes.
- **`scale.py`** — `build_scale_quantize_plan` snaps a clip's out-of-scale notes to the nearest
  in-scale pitch (`snap_pitch`: nearest by distance, tie snaps down, stays in 0..127); in-scale
  notes and note count are untouched. `SCALE_INTERVALS`/`parse_scale` cover major/minor/modes/
  pentatonics/blues/chromatic (with aliases). Pure, stdlib-only. The `plan_/apply_scale_quantize_midi`
  pair resolves the tonic+scale from a `key` (via `harmony.parse_key`; `scale="auto"` follows the
  key's mode) or detects it from the clip (`contextual.analyze_midi_context`); apply writes back
  through the same undoable `apply_expression_to_clip` path with a fingerprint guard.
- **`remap.py`** — `build_scale_remap_plan` transcribes a clip from one key/scale to another *by
  scale degree* (diatonic/modal remap): each note is resolved to its source-scale degree + octave
  + chromatic offset and rebuilt on the same degree of the target scale, so harmonic function is
  kept (C major I-IV-V → C minor i-iv-v). Reuses `scale.SCALE_INTERVALS`; source and target scales
  must have the same degree count (else it raises). Same-shape scales reduce to a diatonic
  transposition. Pure, stdlib-only. The `plan_/apply_remap_progression_to_key` pair resolves
  source/target tonic+scale (target from `target_key`, source from `source_key` or detected) and
  writes back via the undoable `apply_expression_to_clip` path with a fingerprint guard. Distinct
  from `transpose.py` (a mode-blind chromatic shift).
- **`quantize.py`** — `build_quantize_plan` snaps note *start times* to a grid: `strength` (0..1)
  sets how far each note moves toward its grid target (Live's Amount), `swing` (0..1) pushes odd
  grid positions (the off-beats) later by up to half a grid step. Only `start_time` moves
  (pitch/duration/velocity/probability kept, note count unchanged); notes never snap to the grid
  line at the clip end. Pure, stdlib-only. The `plan_/apply_quantize_midi_timing` pair writes back
  via the undoable `apply_expression_to_clip` path with a fingerprint guard. Timing quantization —
  distinct from `scale.py`'s pitch quantization.
- **`progression.py`** — `build_progression_analysis` slices a clip into fixed windows (a bar by
  default), identifies each window's chord by energy-weighted template matching (`identify_chord`:
  maj/min/dim/aug + 7th qualities), and labels it with a Roman numeral (chromatic roots get b/#,
  quality sets case + °/+/7/ø7) and a rough function (tonic/subdominant/dominant) relative to a
  key. Reuses `scale.SCALE_INTERVALS`. Read-only heuristic (each chord carries `confidence` +
  `complete`); the `analyze_chord_progression` tool resolves the key from `key` (via
  `harmony.parse_key`) or detects it, and derives the default window from the clip's time signature.
- **`groove.py`** — `build_velocity_groove_plan` reshapes note *velocities* only: `crescendo`
  (-1..1) ramps velocity over clip time, `dynamics` (-1..1) compresses/expands the range about the
  mean, and `accent_pattern` (cyclic multipliers) × `grid_beats` applies a groove template.
  Velocities clamp to 1..127; pitch/timing/duration/probability and note count are kept. Pure,
  stdlib-only. The `plan_/apply_velocity_groove` pair writes back via the undoable
  `apply_expression_to_clip` path with a fingerprint guard. Macro-dynamics — deliberately distinct
  from `expression.py` (metric downbeat accents, swing, random humanize).
- **`phrase.py`** — `build_phrase_from_loop` tiles an existing loop's notes `repeats` times into
  one longer clip (a Session loop → arrangement-length phrase), with an optional velocity
  `build_up` ramp across the phrase and a `final_fill` density subdivision on the last bar. Note
  count grows, so this is a plan/**create** (not an in-place edit): the `plan_/create_phrase_from_loop`
  pair writes the result into an **empty** slot via the non-overwriting `create_midi_clip` (refuses
  occupied slots) with a source-fingerprint guard. Works on the user's own material — distinct from
  `create_part_variation` (regenerates a part from scratch with a new seed). Pure, stdlib-only.
- **`layering.py`** — `build_layering_plan(structure, tracks)` decides which tracks play in each
  song section by mapping the section label to an arrangement archetype (intro/verse/build/chorus/
  bridge/breakdown/outro → a set of active roles) and each track to a role (`infer_track_role` by
  name keyword). Read-only plan. The `plan_section_layers` tool builds it from `get_state`;
  `apply_section_layer` sets each track's mute to match one chosen section via `set_track_mute`
  (mute toggles only — trivially reversible, no track/clip changes). Pure, stdlib-only.
- **`narrative.py`** — `build_narrative_arc(structure)` reads the *meaning* of a song's development
  into a per-section arc: each section gets an `energy` (0..1) shaped by arrangement conventions
  (sparse intro, a `build` that ramps toward the next chorus, a `breakdown` that drops before a
  harder final chorus, a returning verse/chorus that grows each time), plus its `tension`
  (rise/fall/hold/open), a narrative `role` (setup/development/climax/release/resolution/reset), and
  concrete change `directives` (density/dynamics/register/`motion` into the next section/target
  velocity/`vary`). Where `layering.py` decides *which* tracks play, this decides *how much energy*
  a section carries and *what change* it deserves, so the same material can be developed with intent
  rather than repeated verbatim. Reuses `layering.section_archetype`. Read-only plan
  (`plan_narrative_arc`); a create/apply tool consumes the directives. Pure, stdlib-only.
- **`develop.py`** — `build_developed_arrangement(clip_data, structure, section_repeats, seed)`
  develops one MIDI loop into a *narrative* arrangement. Where `phrase.py` tiles a loop verbatim,
  this reads the narrative arc (`narrative.build_narrative_arc`) and rebuilds the loop **differently
  in every section** per that section's directives: density (thin the intro / fill the chorus),
  register (octave-double the chorus top / drop the breakdown's low voices), velocity (toward the
  section's target with a crescendo/pull-back shape), `vary` (deterministically thin a returning
  section so it differs), and a motion fill into the next section. The transformed sections are
  concatenated into one long clip, so a single loop becomes a full arrangement with a rise, a peak
  and a release. Note count/length grow, so this is a plan/**create** (not in-place): the
  `plan_/create_developed_arrangement` pair writes into an empty slot via the non-overwriting
  `create_midi_clip` with a source-fingerprint guard. Deterministic (same loop + structure + seed →
  same arrangement). Pure, stdlib-only.
- **`timescale.py`** — `build_timescale_plan` scales every note's start/duration and the clip
  length by a factor: 2.0 = half-time (slower/longer), 0.5 = double-time (faster/shorter);
  `factor_for` maps the `"half"`/`"double"` modes. Pitch/velocity/probability and the note count
  are kept. The length changes, so this is a plan/**create** (not in-place): the
  `plan_/create_timescale_clip` pair writes into an empty slot via the non-overwriting
  `create_midi_clip` with a source-fingerprint guard. Pure, stdlib-only.
- **`reverse.py`** — `build_reverse_plan` reverses a clip in time (retrograde): each note's start
  becomes `length - (start + duration)`, so the pattern plays backwards. Pitch/velocity/duration,
  note count and clip length are all preserved (in-place edit). The `plan_/apply_reverse_clip` pair
  writes back via the undoable `apply_expression_to_clip` path with a fingerprint guard. Pure,
  stdlib-only.
- **`notelength.py`** — in-place note-length editing. `build_legato_plan` sets each note's duration
  from the gap to the next same-pitch onset (or clip end) scaled by `gate` (1.0 = legato/connect,
  <1 = staccato); note count unchanged. `build_split_plan` divides each note into `divisions` equal
  parts (count × divisions). Both keep pitch/velocity, same clip length. The
  `plan_/apply_legato_clip` and `plan_/apply_split_notes` pairs write back via the undoable
  `apply_expression_to_clip` path with a fingerprint guard (shared `_apply_note_edit` helper).
  Split alone opts into note-count changes and sends the reviewed source-note count; the Remote
  Script rejects stale counts, implicit count changes, and attempts to clear the clip. Pure,
  stdlib-only.

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
  loads one browsed item onto one track. It refuses an *instrument* preset when the track already
  has an instrument, so a load can never replace one; `audio_effects` and `midi_effects` are allowed
  there, because an effect cannot replace an instrument and putting a delay after a synth is
  ordinary signal-chain work. Browsing (`browse_device_presets`) stays read-only.
- Arrangement-locator placement is **additive**: it skips any position that already has a cue
  (never toggles/deletes one) and restores the transport afterward. Live exposes no way to create a
  cue at a given time — only `set_or_delete_cue()`, a **toggle at the playhead** — and `CuePoint.time`
  is read-only, so a cue cannot be moved after the fact. Placement therefore has to move the
  transport first, and **Live applies a transport move on a later tick**: reading `current_song_time`
  back inside the same command still returns the old position, which used to put every locator
  wherever the transport was parked and delete existing ones on repeat. So the server drives three
  separate bridge calls per locator — `jump_transport` → `get_transport_state` →
  `toggle_cue_at_playhead` — because one bridge call is one Live tick. `toggle_cue_at_playhead`
  refuses unless the transport actually arrived; that refusal is what keeps a toggle from deleting
  someone else's locator. Both `create_arrangement_locators_from_structure` (audio-detected) and
  `create_arrangement_locators_from_sections` (explicit, tempo-free) go through this path.
- Clip envelopes (`set_clip_parameter_envelope` → `set_clip_envelope`) are a **Session-clip**
  feature: Live documents `automation_envelope` as returning None for Arrangement clips, and it
  exposes no API for writing Arrangement automation lanes at all. An envelope written on a Session
  clip *does* travel with the clip into the Arrangement, so the order is create the clip in a
  Session slot → write the envelope → `copy_session_clip_to_arrangement`. Writing after the copy
  silently automates nothing, so the command refuses an Arrangement clip instead. Values are
  range-checked against the parameter before anything is written (no partial batch), and the result
  reports `value_at_time` sampled at the **middle** of each step: `value_at_time` is
  left-continuous, so sampling exactly on a step boundary returns the step that *ends* there and
  makes a correct write look like an off-by-one failure.
- `get_transport_state` is read-only and is the way to check any of the above: transport position,
  `start_time`, `song_length`, loop, and the existing cue list.
- Device parameter changes are range-checked; Live-disabled or macro-controlled parameters are
  rejected. Always `get_track_devices` first — parameter indices/values are device-specific.

## Testing note

`uv run pytest` runs the whole suite (81 files, ~813 tests). `scripts/run_checks.py` is a separate,
deliberately narrow path for contributors without dev deps: it hand-runs `tests/test_bridge.py` and
`tests/test_remote_script_runtime.py` — the two files whose checks need no pytest — plus an import
smoke test of every module. Its printed total adds a hardcoded `+ 57` for those import checks, so
**when you add a module, add it to that list and bump the constant**. Most new test files belong in
the pytest suite only; wire one into `run_checks.py` just when its checks must survive without dev
deps.
