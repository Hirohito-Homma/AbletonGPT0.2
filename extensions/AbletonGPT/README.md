# AbletonGPT Extension companion

A localhost companion that speaks the `abletongpt.extensions.v1` protocol (see
[`docs/EXTENSIONS_SDK.md`](../../docs/EXTENSIONS_SDK.md)) so the AbletonGPT server can use
the `extensions` / `auto` backend. Zero runtime dependencies — Node.js 24+ built-ins only.

## Layout

```text
index.js               entry point: reads env config, picks a provider, starts the server
src/protocol.js        wire protocol + Dispatcher (token check, fixed command allowlist)
src/server.js          loopback-only, newline-delimited JSON TCP server
src/liveProvider.js    LiveProvider interface, MockLiveProvider, SdkLiveProvider (stub)
test/protocol.test.js  node --test suite for the dispatcher
```

## Run it

```bash
# Mock provider (default) — runs without the Extensions SDK or a running Live.
ABLETONGPT_EXTENSIONS_TOKEN=your-shared-token node index.js

npm test    # protocol/dispatch tests
```

Config (shared with the Python bridge):

- `ABLETONGPT_EXTENSIONS_HOST` (default `127.0.0.1`, loopback only)
- `ABLETONGPT_EXTENSIONS_PORT` (default `9878`)
- `ABLETONGPT_EXTENSIONS_TOKEN` (falls back to `ABLETONGPT_TOKEN`)
- `ABLETONGPT_EXTENSIONS_PROVIDER` (`mock` default, or `sdk`)

With the mock provider you can verify the whole wire contract end to end from Python:
start this server, point the AbletonGPT server at the `extensions` backend, and every MCP
tool that maps to an allowlisted command works — no Ableton required.

## Wiring the real SDK

`MockLiveProvider` returns canned data and records mutations in memory. To drive real
Live, implement the methods of `SdkLiveProvider` in `src/liveProvider.js` against the
Ableton Extensions SDK inside your Live 12 Suite Beta project, keeping the same return
shapes, then start with `ABLETONGPT_EXTENSIONS_PROVIDER=sdk`. The v1 command set is:

1. `ping`
2. `get_tempo`
3. `get_tracks`
4. `get_selected_context`
5. `create_midi_clip` (non-destructive: refuse a non-empty slot)

## Security requirements

- Listen only on `127.0.0.1` or another loopback address.
- Require the same shared token used by the Python bridge.
- Keep the fixed command allowlist (`src/protocol.js`).
- Reject arbitrary JavaScript, shell commands, and filesystem operations.
- Return newline-delimited JSON using protocol `abletongpt.extensions.v1`.

Do not commit the downloaded SDK itself unless its license explicitly permits
redistribution.
