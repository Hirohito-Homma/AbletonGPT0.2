"""Guarded selective repair of one Live device parameter or power state.

One invocation observes Live, validates identity and preconditions, then performs
at most one approved mutation and verifies the result with a second read. This is
not a general repair engine: it cannot insert, delete, replace or reorder devices,
and it cannot chain fallback writes.

The Live-facing layer remains authoritative for parameter ranges, locked/macro
parameters and device-power writes. This module only decides *whether* to send
exactly one of ``set_device_parameter``, ``reset_device_parameter`` or
``set_device_power`` through the existing bridge.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from .bridge import AbletonConnectionError

ALLOWED_OPERATIONS = (
    "set_device_parameter",
    "reset_device_parameter",
    "set_device_power",
)

STATUS_REPAIRED = "repaired"
STATUS_NOOP = "noop"
STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"

REASON_UNSUPPORTED_OPERATION = "unsupported_operation"
REASON_INVALID_INDEX = "invalid_index"
REASON_INVALID_VALUE = "invalid_value"
REASON_MISSING_FIELD = "missing_field"
REASON_TARGET_NOT_FOUND = "target_not_found"
REASON_TRACK_IDENTITY_MISMATCH = "track_identity_mismatch"
REASON_DEVICE_IDENTITY_MISMATCH = "device_identity_mismatch"
REASON_PARAMETER_IDENTITY_MISMATCH = "parameter_identity_mismatch"
REASON_STATE_PRECONDITION_FAILED = "state_precondition_failed"
REASON_PARAMETER_LOCKED = "parameter_locked"
REASON_VALUE_OUT_OF_RANGE = "value_out_of_range"
REASON_QUANTIZED_PARAMETER = "quantized_parameter"
REASON_POSTCONDITION_FAILED = "postcondition_failed"
REASON_MUTATION_REJECTED = "mutation_rejected"

#: Tight match for Live floats. Broad enough for binary rounding, not for hiding
#: a stale 0.51 vs 0.50.
_VALUE_TOLERANCE = 1e-6

_PARAMETER_OPERATIONS = frozenset(
    {"set_device_parameter", "reset_device_parameter"}
)
_MUTATION_COMMANDS = frozenset(ALLOWED_OPERATIONS)


@runtime_checkable
class SupportsBridgeCall(Protocol):
    """Anything that can dispatch an Ableton command, e.g. the Live bridge."""

    def call(self, command: str, **params: Any) -> Any: ...


def _result(
    *,
    status: str,
    operation: str | None,
    target: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    mutation_performed: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "operation": operation,
        "target": dict(target),
        "before": dict(before) if before is not None else None,
        "after": dict(after) if after is not None else None,
        "mutation_performed": mutation_performed,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _refused(
    reason: str,
    *,
    operation: str | None = None,
    target: Mapping[str, Any] | None = None,
    before: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _result(
        status=STATUS_REFUSED,
        operation=operation,
        target=target or {},
        before=before,
        after=before,
        mutation_performed=False,
        reason=reason,
    )


def _non_negative_index(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % label)
    if value < 0:
        raise ValueError("%s must be non-negative" % label)
    return value


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a finite number" % label) from exc
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError("%s must be a finite number" % label)
    return number


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("%s must be a string" % label)
    return value


def _values_equivalent(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= _VALUE_TOLERANCE
    except (TypeError, ValueError):
        return False


def _device_power_on(device: Mapping[str, Any]) -> bool:
    """Whether the device's power button is on, from ``get_track_devices`` fields.

    ``set_device_power`` writes ``parameters[0]`` (Device On). ``is_active`` is
    also exposed, but it can be False when an earlier device in the chain is off,
    so the first parameter is preferred when present.
    """

    parameters = device.get("parameters")
    if isinstance(parameters, list) and parameters:
        first = parameters[0]
        if isinstance(first, Mapping) and first.get("value") is not None:
            try:
                return float(first["value"]) >= 0.5
            except (TypeError, ValueError):
                pass
    return bool(device.get("is_active"))


def _parameter_view(parameter: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if parameter is None:
        return None
    view: dict[str, Any] = {
        "index": parameter.get("index"),
        "name": parameter.get("name"),
        "value": parameter.get("value"),
        "normalized_value": parameter.get("normalized_value"),
        "is_enabled": parameter.get("is_enabled"),
        "is_quantized": parameter.get("is_quantized"),
    }
    if "default_value" in parameter:
        view["default_value"] = parameter["default_value"]
    if "min" in parameter:
        view["min"] = parameter["min"]
    if "max" in parameter:
        view["max"] = parameter["max"]
    return view


def _state_view(
    *,
    track_index: int,
    track_name: Any,
    device: Mapping[str, Any] | None,
    parameter: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "track_index": track_index,
        "track": track_name,
        "device_index": None if device is None else device.get("index"),
        "device": None if device is None else device.get("name"),
        "is_active": None if device is None else device.get("is_active"),
        "power_on": None if device is None else _device_power_on(device),
        "parameter": _parameter_view(parameter),
    }


def _lookup_device(
    listing: Mapping[str, Any], device_index: int
) -> Mapping[str, Any] | None:
    devices = listing.get("devices")
    if not isinstance(devices, list):
        return None
    if device_index >= len(devices):
        return None
    device = devices[device_index]
    if not isinstance(device, Mapping):
        return None
    return device


def _lookup_parameter(
    device: Mapping[str, Any], parameter_index: int
) -> Mapping[str, Any] | None:
    parameters = device.get("parameters")
    if not isinstance(parameters, list):
        return None
    if parameter_index >= len(parameters):
        return None
    parameter = parameters[parameter_index]
    if not isinstance(parameter, Mapping):
        return None
    return parameter


def _requested_parameter_value(parameter: Mapping[str, Any], value: float, normalized: bool) -> float:
    if not normalized:
        return value
    minimum = float(parameter.get("min", 0.0))
    maximum = float(parameter.get("max", 1.0))
    return minimum + value * (maximum - minimum)


def _postcondition_holds(
    operation: str,
    after: Mapping[str, Any],
    *,
    value: float | None,
    normalized: bool,
    enabled: bool | None,
) -> bool:
    if operation == "set_device_power":
        return after.get("power_on") is enabled
    parameter = after.get("parameter")
    if not isinstance(parameter, Mapping):
        return False
    if operation == "reset_device_parameter":
        if "default_value" not in parameter:
            return False
        return _values_equivalent(parameter.get("value"), parameter.get("default_value"))
    if value is None:
        return False
    if normalized:
        return _values_equivalent(parameter.get("normalized_value"), value)
    return _values_equivalent(parameter.get("value"), value)


def _parse_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return either a parsed request dict or a refused result."""

    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS:
        return _refused(REASON_UNSUPPORTED_OPERATION, operation=operation if isinstance(operation, str) else None)

    target: dict[str, Any] = {}
    try:
        track_index = _non_negative_index(request.get("track_index"), "track_index")
        device_index = _non_negative_index(request.get("device_index"), "device_index")
    except ValueError:
        return _refused(REASON_INVALID_INDEX, operation=operation, target=target)
    target["track_index"] = track_index
    target["device_index"] = device_index

    parameter_index: int | None = None
    if operation in _PARAMETER_OPERATIONS:
        if "parameter_index" not in request or request.get("parameter_index") is None:
            return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
        try:
            parameter_index = _non_negative_index(
                request.get("parameter_index"), "parameter_index"
            )
        except ValueError:
            return _refused(REASON_INVALID_INDEX, operation=operation, target=target)
        target["parameter_index"] = parameter_index
    elif "parameter_index" in request and request.get("parameter_index") is not None:
        try:
            parameter_index = _non_negative_index(
                request.get("parameter_index"), "parameter_index"
            )
        except ValueError:
            return _refused(REASON_INVALID_INDEX, operation=operation, target=target)
        target["parameter_index"] = parameter_index

    value: float | None = None
    normalized = bool(request.get("normalized", False))
    if operation == "set_device_parameter":
        if "value" not in request or request.get("value") is None:
            return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
        try:
            value = _finite_number(request.get("value"), "value")
        except ValueError:
            return _refused(REASON_INVALID_VALUE, operation=operation, target=target)
        if normalized and not 0.0 <= value <= 1.0:
            return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    enabled: bool | None = None
    if operation == "set_device_power":
        if "enabled" not in request or request.get("enabled") is None:
            return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
        enabled = request.get("enabled")
        if not isinstance(enabled, bool):
            return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    try:
        expected_track_name = _optional_text(
            request.get("expected_track_name"), "expected_track_name"
        )
        expected_device_name = _optional_text(
            request.get("expected_device_name"), "expected_device_name"
        )
        expected_parameter_name = _optional_text(
            request.get("expected_parameter_name"), "expected_parameter_name"
        )
    except ValueError:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    expected_current_value = request.get("expected_current_value")
    if expected_current_value is not None:
        try:
            expected_current_value = _finite_number(
                expected_current_value, "expected_current_value"
            )
        except ValueError:
            return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    expected_power_state = request.get("expected_power_state")
    if expected_power_state is not None and not isinstance(expected_power_state, bool):
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    return {
        "operation": operation,
        "track_index": track_index,
        "device_index": device_index,
        "parameter_index": parameter_index,
        "value": value,
        "normalized": normalized,
        "enabled": enabled,
        "expected_track_name": expected_track_name,
        "expected_device_name": expected_device_name,
        "expected_parameter_name": expected_parameter_name,
        "expected_current_value": expected_current_value,
        "expected_power_state": expected_power_state,
        "target": target,
    }


def _read_devices(bridge: SupportsBridgeCall, track_index: int) -> Mapping[str, Any] | dict[str, Any]:
    try:
        listing = bridge.call("get_track_devices", track_index=track_index)
    except AbletonConnectionError:
        raise
    except Exception:
        return _refused(REASON_TARGET_NOT_FOUND, target={"track_index": track_index})
    if not isinstance(listing, Mapping):
        return _refused(REASON_TARGET_NOT_FOUND, target={"track_index": track_index})
    return listing


def repair_live_device(bridge: SupportsBridgeCall, request: Mapping[str, Any]) -> dict[str, Any]:
    """Read Live, maybe perform one approved mutation, read back, return a structured result.

    ``request`` is a mapping (MCP arguments or a test dict). Unexpected operations
    and failed guards return ``status="refused"`` and never send a mutation.
    """

    parsed = _parse_request(request)
    if parsed.get("status") == STATUS_REFUSED:
        return parsed

    operation: str = parsed["operation"]
    track_index: int = parsed["track_index"]
    device_index: int = parsed["device_index"]
    parameter_index: int | None = parsed["parameter_index"]
    target: dict[str, Any] = parsed["target"]

    listing = _read_devices(bridge, track_index)
    if isinstance(listing, dict) and listing.get("status") == STATUS_REFUSED:
        listing["operation"] = operation
        listing["target"] = target
        return listing

    device = _lookup_device(listing, device_index)
    if device is None:
        before = _state_view(
            track_index=track_index,
            track_name=listing.get("track"),
            device=None,
            parameter=None,
        )
        return _refused(
            REASON_TARGET_NOT_FOUND,
            operation=operation,
            target=target,
            before=before,
        )

    parameter: Mapping[str, Any] | None = None
    if parameter_index is not None:
        parameter = _lookup_parameter(device, parameter_index)
        if parameter is None:
            before = _state_view(
                track_index=track_index,
                track_name=listing.get("track"),
                device=device,
                parameter=None,
            )
            return _refused(
                REASON_TARGET_NOT_FOUND,
                operation=operation,
                target=target,
                before=before,
            )
    elif operation in _PARAMETER_OPERATIONS:
        before = _state_view(
            track_index=track_index,
            track_name=listing.get("track"),
            device=device,
            parameter=None,
        )
        return _refused(
            REASON_MISSING_FIELD,
            operation=operation,
            target=target,
            before=before,
        )

    before = _state_view(
        track_index=track_index,
        track_name=listing.get("track"),
        device=device,
        parameter=parameter,
    )

    if parsed["expected_track_name"] is not None and listing.get("track") != parsed["expected_track_name"]:
        return _refused(
            REASON_TRACK_IDENTITY_MISMATCH,
            operation=operation,
            target=target,
            before=before,
        )
    if parsed["expected_device_name"] is not None and device.get("name") != parsed["expected_device_name"]:
        return _refused(
            REASON_DEVICE_IDENTITY_MISMATCH,
            operation=operation,
            target=target,
            before=before,
        )
    if parsed["expected_parameter_name"] is not None:
        actual_name = None if parameter is None else parameter.get("name")
        if actual_name != parsed["expected_parameter_name"]:
            return _refused(
                REASON_PARAMETER_IDENTITY_MISMATCH,
                operation=operation,
                target=target,
                before=before,
            )

    if parsed["expected_power_state"] is not None:
        if _device_power_on(device) is not parsed["expected_power_state"]:
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )
    if parsed["expected_current_value"] is not None:
        if parameter is None:
            return _refused(
                REASON_MISSING_FIELD,
                operation=operation,
                target=target,
                before=before,
            )
        if not _values_equivalent(parameter.get("value"), parsed["expected_current_value"]):
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )

    if _postcondition_holds(
        operation,
        before,
        value=parsed["value"],
        normalized=parsed["normalized"],
        enabled=parsed["enabled"],
    ):
        return _result(
            status=STATUS_NOOP,
            operation=operation,
            target=target,
            before=before,
            after=before,
            mutation_performed=False,
        )

    if parameter is not None and parameter.get("is_enabled") is False:
        return _refused(
            REASON_PARAMETER_LOCKED,
            operation=operation,
            target=target,
            before=before,
        )
    if operation == "set_device_power":
        power_parameter = _lookup_parameter(device, 0)
        if power_parameter is None:
            return _refused(
                REASON_TARGET_NOT_FOUND,
                operation=operation,
                target=target,
                before=before,
            )
        if power_parameter.get("is_enabled") is False:
            return _refused(
                REASON_PARAMETER_LOCKED,
                operation=operation,
                target=target,
                before=before,
            )
    if operation == "reset_device_parameter":
        assert parameter is not None
        if parameter.get("is_quantized"):
            return _refused(
                REASON_QUANTIZED_PARAMETER,
                operation=operation,
                target=target,
                before=before,
            )
        if "default_value" not in parameter:
            return _refused(
                REASON_TARGET_NOT_FOUND,
                operation=operation,
                target=target,
                before=before,
            )
    if operation == "set_device_parameter":
        assert parameter is not None
        requested = _requested_parameter_value(
            parameter, parsed["value"], parsed["normalized"]
        )
        minimum = parameter.get("min")
        maximum = parameter.get("max")
        if minimum is not None and maximum is not None:
            try:
                if requested < float(minimum) or requested > float(maximum):
                    return _refused(
                        REASON_VALUE_OUT_OF_RANGE,
                        operation=operation,
                        target=target,
                        before=before,
                    )
            except (TypeError, ValueError):
                return _refused(
                    REASON_INVALID_VALUE,
                    operation=operation,
                    target=target,
                    before=before,
                )

    mutation_params = _mutation_params(parsed)
    try:
        bridge.call(operation, **mutation_params)
    except AbletonConnectionError:
        raise
    except Exception as exc:
        after_listing = _read_devices(bridge, track_index)
        after = before
        if not (isinstance(after_listing, dict) and after_listing.get("status") == STATUS_REFUSED):
            after_device = _lookup_device(after_listing, device_index)
            after_parameter = (
                None
                if after_device is None or parameter_index is None
                else _lookup_parameter(after_device, parameter_index)
            )
            after = _state_view(
                track_index=track_index,
                track_name=after_listing.get("track") if isinstance(after_listing, Mapping) else None,
                device=after_device,
                parameter=after_parameter,
            )
        failed = _result(
            status=STATUS_FAILED,
            operation=operation,
            target=target,
            before=before,
            after=after,
            mutation_performed=True,
            reason=REASON_MUTATION_REJECTED,
        )
        failed["detail"] = str(exc)[:300]
        return failed

    after_listing = _read_devices(bridge, track_index)
    if isinstance(after_listing, dict) and after_listing.get("status") == STATUS_REFUSED:
        return _result(
            status=STATUS_FAILED,
            operation=operation,
            target=target,
            before=before,
            after=None,
            mutation_performed=True,
            reason=REASON_POSTCONDITION_FAILED,
        )
    after_device = _lookup_device(after_listing, device_index)
    after_parameter = (
        None
        if after_device is None or parameter_index is None
        else _lookup_parameter(after_device, parameter_index)
    )
    after = _state_view(
        track_index=track_index,
        track_name=after_listing.get("track"),
        device=after_device,
        parameter=after_parameter,
    )
    if not _postcondition_holds(
        operation,
        after,
        value=parsed["value"],
        normalized=parsed["normalized"],
        enabled=parsed["enabled"],
    ):
        return _result(
            status=STATUS_FAILED,
            operation=operation,
            target=target,
            before=before,
            after=after,
            mutation_performed=True,
            reason=REASON_POSTCONDITION_FAILED,
        )
    return _result(
        status=STATUS_REPAIRED,
        operation=operation,
        target=target,
        before=before,
        after=after,
        mutation_performed=True,
    )


def _mutation_params(parsed: Mapping[str, Any]) -> dict[str, Any]:
    operation = parsed["operation"]
    params: dict[str, Any] = {
        "track_index": parsed["track_index"],
        "device_index": parsed["device_index"],
    }
    if operation in _PARAMETER_OPERATIONS:
        params["parameter_index"] = parsed["parameter_index"]
    if operation == "set_device_parameter":
        params["value"] = parsed["value"]
        params["normalized"] = parsed["normalized"]
    if operation == "set_device_power":
        params["enabled"] = parsed["enabled"]
    return params


def is_mutation_command(command: str) -> bool:
    """True for the three device-repair writes; false for reads and everything else."""

    return command in _MUTATION_COMMANDS
