"""Composable Live backends.

The MCP server talks to Live through an object exposing ``call(command, **params)``.
Two concrete backends implement it -- the Remote Script (:class:`AbletonBridge`) and the
Ableton Extensions companion (:class:`ExtensionsBridge`). :class:`FallbackBridge` composes
two of them so the ``auto`` mode can prefer one and fall back to the other.
"""

from __future__ import annotations

from typing import Any

from .bridge import AbletonConnectionError
from .extensions_bridge import ExtensionsConnectionError

#: Exceptions meaning "this backend is unreachable". Both are raised at connection time,
#: before a command reaches Live, so falling back can never re-apply a mutation.
UNREACHABLE_ERRORS = (AbletonConnectionError, ExtensionsConnectionError)


class FallbackBridge:
    """Prefer a primary backend, fall back to a secondary one when it is unreachable.

    The choice is made once, by a read-only ``ping`` probe on first use, then it stays
    sticky for the rest of the session. This is deliberate:

    * A real command is only ever sent to the single chosen backend, so a mutating
      command can never be applied twice.
    * Only a genuine *connection* failure (raised before the command reaches Live)
      triggers the fallback; a command that reaches Live and fails there propagates
      unchanged, and is never retried on the other backend.

    Selection is lazy -- constructing a ``FallbackBridge`` opens no socket.
    """

    def __init__(
        self,
        primary: Any,
        secondary: Any,
        *,
        probe_command: str = "ping",
        unreachable: tuple[type[BaseException], ...] = UNREACHABLE_ERRORS,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._probe_command = probe_command
        self._unreachable = unreachable
        self._chosen: Any | None = None

    def _resolve(self) -> Any:
        """Pick the backend once, probing the primary with a read-only command."""
        if self._chosen is None:
            try:
                self._primary.call(self._probe_command)
            except self._unreachable:
                self._chosen = self._secondary
            else:
                self._chosen = self._primary
        return self._chosen

    def call(self, command: str, **params: Any) -> Any:
        return self._resolve().call(command, **params)

    @property
    def is_resolved(self) -> bool:
        """True once the backend has been chosen (a probe has run)."""
        return self._chosen is not None
