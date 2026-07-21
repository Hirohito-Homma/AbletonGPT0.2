from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from ..bridge import AbletonBridge
from .models import JobStep


@runtime_checkable
class SupportsBridgeCall(Protocol):
    """Anything that can dispatch an Ableton command, e.g. :class:`AbletonBridge`.

    Kept minimal so tests can inject a fake without a live Ableton connection.
    """

    def call(self, command: str, **params: Any) -> Any: ...


class UnsupportedStepCommand(ValueError):
    """Raised when a :class:`JobStep` command has no executor mapping yet.

    A subclass of ``ValueError`` so :class:`~abletongpt.jobs.runner.JobRunner`
    records the step as FAILED rather than crashing the whole run: unknown commands
    fail safely, one step at a time.
    """


# Handler signature: (bridge, params) -> the bridge result (discarded by ``execute``).
_Handler = Callable[[SupportsBridgeCall, dict], Any]


def _play(bridge: SupportsBridgeCall, params: dict) -> Any:
    return bridge.call("set_transport", action="play")


def _stop(bridge: SupportsBridgeCall, params: dict) -> Any:
    return bridge.call("set_transport", action="stop")


def _get_tempo(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"tempo": state["tempo"]}


def _set_tempo(bridge: SupportsBridgeCall, params: dict) -> Any:
    # A missing ``bpm`` raises KeyError, which the runner converts to a FAILED step.
    return bridge.call("set_tempo", bpm=float(params["bpm"]))


def _is_playing(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"is_playing": state["is_playing"]}


def _get_tracks(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"tracks": state["tracks"]}


class AbletonStepExecutor:
    """Connects a :class:`JobStep` to real Ableton operations via the bridge.

    MVP scope: only transport/tempo/read commands known to work today
    (``play``, ``stop``, ``get_tempo``, ``set_tempo``, ``is_playing``,
    ``get_tracks``). Any other command fails safely as an
    :class:`UnsupportedStepCommand`. Bridge/connection errors are **not** swallowed;
    they propagate so :class:`~abletongpt.jobs.runner.JobRunner` records the step as
    FAILED with the error text. Satisfies the ``StepExecutor`` protocol.
    """

    #: command name -> handler. Public so callers can inspect what is supported.
    HANDLERS: dict[str, _Handler] = {
        "play": _play,
        "stop": _stop,
        "get_tempo": _get_tempo,
        "set_tempo": _set_tempo,
        "is_playing": _is_playing,
        "get_tracks": _get_tracks,
    }

    def __init__(self, bridge: SupportsBridgeCall | None = None) -> None:
        # AbletonBridge() reads config but does not connect until ``call`` is invoked.
        self._bridge: SupportsBridgeCall = bridge or AbletonBridge()

    @property
    def supported_commands(self) -> tuple[str, ...]:
        return tuple(self.HANDLERS)

    def execute(self, step: JobStep) -> None:
        handler = self.HANDLERS.get(step.command)
        if handler is None:
            raise UnsupportedStepCommand(
                "unsupported step command: %r (supported: %s)"
                % (step.command, ", ".join(self.supported_commands))
            )
        handler(self._bridge, step.params)
