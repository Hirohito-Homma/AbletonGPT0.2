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
- `ableton_remote_script/AbletonGPT/__init__.py`: main-thread-safe Live Object Model adapter.
- `scripts/setup_macos.py`: dependency setup, shared-token creation, and Remote Script installation.

## Safety model

- The Ableton TCP bridge binds only to `127.0.0.1`.
- Requests may use a shared random token stored in the user's application-support directory.
- The MCP surface exposes fixed commands; arbitrary Python and shell execution are not supported.
- Destructive actions such as deleting tracks/files, overwriting a Live Set, and exporting masters are intentionally absent.
- Planning tools are read-only and separate from creation tools.
- Instrument planning is read-only; confirmed insertion is limited to an allowlist and one track per call.
- Existing MIDI analysis is read-only; complementary material is created on a new track after review.
- Loudness analysis reads a selected local audio file but never rewrites or normalizes it.
- Parameters are range-checked, and Live-disabled or macro-controlled parameters are rejected.

## Compatibility

- Ableton Live 11+: Remote Script, MIDI note creation, existing device control.
- Ableton Live 12.3+: native Live device insertion through `Track.insert_device`.
- AI singing audio: requires a separate licensed singing engine. AbletonGPT prepares the guide and imports rendered audio.
