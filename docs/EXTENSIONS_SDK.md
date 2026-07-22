# Ableton Extensions SDK integration

This project keeps the existing Remote Script bridge and adds an optional
Extensions SDK path for Live 12 Suite Beta 12.4.5 or later.

## Intended architecture

```text
ChatGPT / Codex / MCP client
            |
            v
      AbletonGPT server
       |             |
       |             +--> ExtensionsBridge --> AbletonGPT Extension --> Live
       |
       +----------------> AbletonBridge -----> Remote Script --------> Live
```

The Remote Script remains the default backend. The Extensions backend is an
opt-in experimental path for commands that benefit from the JavaScript SDK.

## Selecting the backend

The MCP server chooses one backend at startup from the `backend` setting
(`ABLETONGPT_BACKEND` env var, or `"backend"` in `config.json`):

- `remote_script` (default, also `remote` / `default`) — the Control Surface
  Remote Script. Works on stable Live 11+.
- `extensions` (also `extension`) — the Ableton Extensions SDK companion
  described below. Requires the Live 12 Suite Beta and a running companion.
- `auto` — prefer the Extensions companion, fall back to the Remote Script if
  the companion is unreachable.

Both backends expose the same `call(command, **params)` contract, so every MCP
tool works unchanged regardless of the selected backend; only the in-Live
handler differs. Selection is lazy — no socket is opened until the first call.
`get_abletongpt_capabilities` reports the configured `backend` (without probing).

`auto` decides once, using a read-only `ping` probe on first use, then stays on
that backend for the session. This is deliberate: a real command is only ever
sent to one backend, so a mutating command can never be applied twice. Only a
connection failure (raised before a command reaches Live) triggers the
fallback; a command that reaches Live and fails there propagates unchanged and
is never retried on the other backend.

```bash
ABLETONGPT_BACKEND=extensions uv run abletongpt
```

## Python bridge

`src/abletongpt/extensions_bridge.py` implements a localhost-only,
newline-delimited JSON client. Its default endpoint is `127.0.0.1:9878`.

Configuration keys in the normal AbletonGPT `config.json`:

```json
{
  "extensions_host": "127.0.0.1",
  "extensions_port": 9878,
  "extensions_token": "replace-with-the-shared-token",
  "extensions_timeout": 3.0
}
```

Equivalent environment variables are available:

```text
ABLETONGPT_EXTENSIONS_HOST
ABLETONGPT_EXTENSIONS_PORT
ABLETONGPT_EXTENSIONS_TOKEN
ABLETONGPT_EXTENSIONS_TIMEOUT
```

When `extensions_token` is omitted, the bridge falls back to the existing
shared `token` value.

## Wire protocol

Each request and response is one UTF-8 JSON object followed by a newline.

Request:

```json
{
  "protocol": "abletongpt.extensions.v1",
  "command": "get_tempo",
  "params": {},
  "token": "shared-secret"
}
```

Success response:

```json
{
  "protocol": "abletongpt.extensions.v1",
  "ok": true,
  "result": {
    "tempo": 120
  }
}
```

Error response:

```json
{
  "protocol": "abletongpt.extensions.v1",
  "ok": false,
  "error": "unknown command"
}
```

## SDK-side implementation

A Node.js companion implementing this protocol lives under
`extensions/AbletonGPT/`. The standalone mock (`node index.js`, `npm test`)
runs the whole wire contract from the Python `ExtensionsBridge` without the SDK
or a running Live. The real extension (`src/extension.ts`) starts the same
server backed by `SdkLiveProvider` (`src/sdkLiveProvider.ts`), which drives Live
through the Extensions SDK and type-checks against `@ableton-extensions/sdk`
(`npm run typecheck`). See
[`extensions/AbletonGPT/README.md`](../extensions/AbletonGPT/README.md).

The official Ableton Extensions SDK is distributed separately during the public
beta; drop its tarballs into `extensions/AbletonGPT/vendor/` and `npm install`.
The adapter:

1. Binds only to localhost.
2. Verifies the shared token before executing a command.
3. Accepts the protocol above.
4. Maps fixed command names to SDK operations.
5. Returns one response and closes the connection.
6. Does not expose arbitrary JavaScript, shell, or filesystem execution.

Start with read-only commands:

- `ping`
- `get_tempo`
- `get_tracks`
- `get_selected_context`

Then add one non-destructive proof of concept:

- `create_midi_clip` on a newly created track or empty target slot

Do not remove the Remote Script backend until equivalent behavior is verified
on the user's Live beta installation.

## Requirements

At the time this integration was introduced, Ableton Extensions required Live
12 Suite Beta 12.4.5 or later, the separately downloaded Extensions SDK, and
Node.js 24.16.0 LTS or later. Check Ableton's current beta documentation before
installing because the SDK and manifest format may change during beta.

## Verifying on a real Live install

The companion's protocol, providers, and the Python bridge are all covered by
automated tests and type-checking; the one thing that can only be confirmed on a
real beta install is that the Extension Host lets the extension open its loopback
TCP server (`node:net`). This runbook walks that through. The `get_midi_clip_notes`
command is needed for the full read→plan→apply flow, so build from a checkout that
includes it.

### 1. Build the extension and launch it in Live

```bash
cd extensions/AbletonGPT
mkdir -p vendor
cp /path/to/ableton-extensions-sdk-1.0.0-beta.0.tgz vendor/
cp /path/to/ableton-extensions-cli-1.0.0-beta.0.tgz vendor/
npm install
npm run typecheck        # expected: 0 errors
```

Enable **Developer Mode** in Live (Preferences → Extensions), then export the
config in the shell so Live's Extension Host inherits it, and start:

```bash
export EXTENSION_HOST_PATH="/Applications/Ableton Live 12.4 Beta.app"
export ABLETONGPT_EXTENSIONS_PORT=9878
# Leave the token empty for the first connectivity check to remove one variable.
npm start
```

### 2. Critical check — does `node:net` work?

Success looks like this line in the startup log:

```text
AbletonGPT Extension listening on 127.0.0.1:9878 (token: none)
```

If it appears, the architecture holds. If it does not — capture the error; only
the transport (`src/server.js`) would then need swapping, not the protocol or
provider.

### 3. Drive real Live from Python

In Live, put a MIDI clip with some notes into a known slot (e.g. the first MIDI
track's top Session slot). Then, in a separate shell:

```bash
export ABLETONGPT_BACKEND=extensions ABLETONGPT_EXTENSIONS_PORT=9878
```

```python
# probe.py  — indices are 0-based; song.tracks excludes return/main tracks.
from abletongpt import server
print("backend:", type(server.bridge).__name__)
print("tracks:", server.bridge.call("get_tracks")["tracks"])
print("clip:", server.bridge.call("get_midi_clip_notes", track_index=0, clip_index=0))
res = server.apply_expression(0, 0, accent=0.8, swing=0.4)   # undoable in Live
print("applied:", res["applied"], "| velocity", res["diff"]["velocity"])
```

```bash
uv run python probe.py
```

Confirm: real track names come back; the clip's notes come back; after
`apply_expression` the clip's velocities change in Live and ⌘Z reverts it.

Once connectivity is confirmed, set the same `ABLETONGPT_EXTENSIONS_TOKEN` on both
sides (the Live-side shell and the Python side) for real use.
