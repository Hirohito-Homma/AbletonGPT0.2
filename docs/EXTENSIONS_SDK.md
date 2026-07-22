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

Both backends expose the same `call(command, **params)` contract, so every MCP
tool works unchanged regardless of the selected backend; only the in-Live
handler differs. Selection is lazy — no socket is opened until the first call.
`get_abletongpt_capabilities` reports the active `backend`. Automatic
detection / fallback between backends is intentionally not implemented yet.

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

The official Ableton Extensions SDK is distributed separately during the
public beta. Place the SDK-created Extension project under
`extensions/AbletonGPT/`, then implement an adapter that:

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
