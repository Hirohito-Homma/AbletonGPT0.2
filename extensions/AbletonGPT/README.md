# AbletonGPT Extension companion

A localhost companion that speaks the `abletongpt.extensions.v1` protocol (see
[`docs/EXTENSIONS_SDK.md`](../../docs/EXTENSIONS_SDK.md)) so the AbletonGPT server can use
the `extensions` / `auto` backend. Zero runtime dependencies — Node.js 24+ built-ins only.

## Layout

```text
index.js                  standalone MOCK companion: node index.js (no SDK, no Live)
src/protocol.js           wire protocol + Dispatcher (token check, fixed command allowlist)
src/server.js             loopback-only, newline-delimited JSON TCP server
src/server.d.ts           types for server.js so the TS entry can import it
src/liveProvider.js       LiveProvider interface + MockLiveProvider (in-memory)
src/sdkLiveProvider.ts    SdkLiveProvider: drives real Live via the Extensions SDK
src/extension.ts          extension entry: activate() -> initialize() -> start server
manifest.json build.ts tsconfig.json   Ableton extension project files
test/protocol.test.js     node --test suite for the dispatcher
```

## Two ways to run

**Mock companion** (no SDK, no Live) — for verifying the wire contract from Python:

```bash
ABLETONGPT_EXTENSIONS_TOKEN=your-shared-token node index.js
npm test    # protocol/dispatch tests
```

Point the AbletonGPT server at the `extensions` backend and every MCP tool that maps to an
allowlisted command round-trips against this mock — no Ableton required.

**Real extension** (inside Live 12 Suite Beta) — `src/extension.ts` starts the same server
backed by `SdkLiveProvider`:

```bash
# 1. Put the SDK/CLI tarballs from your Extensions SDK download here (gitignored):
mkdir -p vendor
cp /path/to/ableton-extensions-sdk-1.0.0-beta.0.tgz vendor/
cp /path/to/ableton-extensions-cli-1.0.0-beta.0.tgz vendor/
npm install

# 2. Type-check and build, then run under Live's Developer Mode (see docs/development):
npm run typecheck
cp .env.example .env   # set EXTENSION_HOST_PATH + ABLETONGPT_EXTENSIONS_TOKEN
npm start              # tsc --noEmit && esbuild bundle && extensions-cli run
```

Config (shared with the Python bridge):

- `ABLETONGPT_EXTENSIONS_HOST` (default `127.0.0.1`, loopback only)
- `ABLETONGPT_EXTENSIONS_PORT` (default `9878`)
- `ABLETONGPT_EXTENSIONS_TOKEN` (falls back to `ABLETONGPT_TOKEN`)

## Command set (protocol v1)

| command | SdkLiveProvider | notes |
| --- | --- | --- |
| `ping` | — | liveness |
| `get_tempo` | `song.tempo` | |
| `get_tracks` | `song.tracks` | `has_midi_input` = `track instanceof MidiTrack` |
| `get_state` | `song.tempo` / `song.scenes` / `song.tracks` | tempo, scene count, per-track name/volume/mute/solo/arm/clip_slots. No `is_playing` or `signature` (no SDK API) |
| `get_mix_snapshot` | `track.mixer` / `song.returnTracks` / `song.mainTrack` | per-track/return/master volume/pan/mute/solo/sends. `output_meter_level` is always `null` (no meter in the SDK); the Python snapshot builder drops it anyway |
| `get_midi_clip_notes` | `midiClip.notes` (read) | returns the clip's notes + length/tempo; enables the read step of analyze/plan/apply |
| `create_midi_clip` | `clipSlot.createMidiClip` + `midiClip.notes` | non-destructive: refuses a non-empty slot; carries per-note probability |
| `apply_expression_to_clip` | `midiClip.notes` (wholesale replace) | replaces the notes of an existing MIDI clip; keeps probability; parity with the Remote Script backend |
| `set_tempo` | `song.tempo =` | |
| `set_track_volume` / `set_track_pan` | `mixer.volume` / `mixer.panning` `.setValue()` | echoes the applied value |
| `set_track_mute` / `set_track_solo` / `set_track_arm` | `track.mute` / `solo` / `arm` setters | |
| `get_track_devices` | `track.devices` / `DeviceParameter` | name + parameters (value/min/max/quantized/default). No class_name/type/is_active (not in SDK) |
| `get_clip_warp_markers` | `AudioClip.warpMarkers` / `warping` / `warpMode` | read-only warp markers (`beat_time`/`sample_time`) of a Session audio clip. Warp-marker writing is not in the SDK (or the LOM) |
| `add_native_device` | `track.insertDevice(name, index)` | inserts a built-in Live device by name (`index` -1 appends); verifies one device was added. No `type`/`class_display_name` in the result (not in SDK). Third-party plug-ins are rejected by the SDK |
| `set_device_parameter` / `reset_device_parameter` | `DeviceParameter.setValue()` | range-checked; supports `normalized`; reset refuses quantized params |
| `set_device_power` | `device.parameters[0].setValue()` | toggles Live's "Device On" (first parameter) |
| `get_selected_context` | **unsupported** | the SDK delivers selection only via context-menu commands, not as an ambient query |
| `set_transport` (play/stop) | **unsupported** | the SDK exposes no transport control |

`SdkLiveProvider` (`src/sdkLiveProvider.ts`) is written against the SDK's `@ableton-extensions/sdk`
type definitions and type-checks with `npm run typecheck`. The one thing to confirm on your
beta install is that the Extension Host permits the loopback TCP server (`node:net`); the
esbuild target is `platform: node`, so it should. If it does not, only the transport
(`src/server.js`) needs swapping — the protocol and provider are unaffected.

## Security requirements

- Listen only on `127.0.0.1` or another loopback address.
- Require the same shared token used by the Python bridge.
- Keep the fixed command allowlist (`src/protocol.js`).
- Reject arbitrary JavaScript, shell commands, and filesystem operations.
- Return newline-delimited JSON using protocol `abletongpt.extensions.v1`.

Do not commit the downloaded SDK itself unless its license explicitly permits
redistribution.
