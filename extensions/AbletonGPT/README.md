# AbletonGPT Extension workspace

This directory is reserved for the official Ableton Extensions SDK project.

The SDK is currently distributed separately to Live 12 Suite Beta users, so
its generated files and package names are not guessed or vendored here. Create
a starter Extension with the SDK, copy its generated project into this folder,
and preserve this repository's protocol contract in
`docs/EXTENSIONS_SDK.md`.

The first implementation should expose a localhost-only adapter for these
commands:

1. `ping`
2. `get_tempo`
3. `get_tracks`
4. `get_selected_context`
5. `create_midi_clip`

Security requirements:

- Listen only on `127.0.0.1` or another loopback address.
- Require the same shared token used by the Python bridge.
- Keep a fixed command allowlist.
- Reject arbitrary JavaScript, shell commands, and filesystem operations.
- Return newline-delimited JSON using protocol `abletongpt.extensions.v1`.

Do not commit the downloaded SDK itself unless its license explicitly permits
redistribution.
