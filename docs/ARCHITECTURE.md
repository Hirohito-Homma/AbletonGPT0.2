# Architecture

```text
ChatGPT / Codex / MCP client
            |
            | MCP (stdio or local Streamable HTTP)
            v
      AbletonGPT server
       |      |      |
       |      |      +-- Vocal planning/import contract
       |      +--------- Composition engine
       |---------------- Existing-MIDI context analyzer/generator
       |---------------- Native-instrument selection engine
       |---------------- Offline loudness analyzer
       +---------------- Validated localhost JSON bridge
                              |
                              v
                    Ableton Remote Script
                              |
                              v
                      Live Object Model
```

## Components

- `src/abletongpt/server.py`: MCP tools and validation boundary.
- `src/abletongpt/bridge.py`: newline-delimited JSON request/response transport.
- `src/abletongpt/composition.py`: deterministic beginner and professional MIDI generation.
- `src/abletongpt/contextual.py`: existing MIDI analysis and complementary-part generation.
- `src/abletongpt/instruments.py`: role/genre/mood-aware native-instrument selection and fallbacks.
- `src/abletongpt/vocal.py`: lyrics-to-note guide and render handoff contract.
- `src/abletongpt/loudness.py`: read-only WAV/AIFF BS.1770/EBU R128 loudness analysis.
  Uses FFmpeg's `ebur128` filter when the binary is present and the stdlib implementation
  otherwise; the engines differ by ~0.1 dB of true peak, so each report names its
  `analysis_engine` and callers can pin one with `engine=`.
- `src/abletongpt/delivery.py`: read-only manual export manifests and post-export delivery verification.
- `src/abletongpt/device_repair.py`: guarded selective repair of one Live device parameter or power state (read → validate → at most one mutation → readback). See [DEVICE_REPAIR.md](DEVICE_REPAIR.md).
- `ableton_remote_script/AbletonGPT/__init__.py`: main-thread-safe Live Object Model adapter.
- `scripts/setup_macos.py`: dependency setup, shared-token creation, and Remote Script installation.

## Safety model

- The Ableton TCP bridge binds only to `127.0.0.1`.
- Requests may use a shared random token stored in the user's application-support directory.
- The MCP surface exposes fixed commands; arbitrary Python and shell execution are not supported.
- Destructive actions such as deleting tracks/files, overwriting a Live Set, and exporting masters are intentionally absent.
- Because the public Live Object Model exposes neither Set saving nor Main rendering, `plan_audio_export` records an explicit manual handoff instead of pretending to automate it.
- `verify_audio_export` is read-only and separates blocking format/duration/True-Peak failures from advisory loudness/path warnings.
- Planning tools are read-only and separate from creation tools.
- Instrument planning is read-only; confirmed insertion is limited to an allowlist and one track per call.
- Existing MIDI analysis is read-only; complementary material is created on a new track after review.
- Loudness analysis reads a selected local audio file but never rewrites or normalizes it.
- Parameters are range-checked, and Live-disabled or macro-controlled parameters are rejected.
- Guarded device repair (`repair_live_device`) observes Live first, refuses a mismatched or stale target, performs at most one approved mutation (`set_device_parameter` / `reset_device_parameter` / `set_device_power`), and reports success only from a second Live read. It does not insert, delete, replace or reorder devices.

## Compatibility

- Ableton Live 11+: Remote Script, MIDI note creation, existing device control.
- Ableton Live 12.3+: native Live device insertion through `Track.insert_device`.
- AI singing audio: requires a separate licensed singing engine. AbletonGPT prepares the guide and imports rendered audio.
