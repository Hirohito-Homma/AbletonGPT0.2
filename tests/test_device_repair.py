"""Guarded selective device repair: one approved Live mutation, identity/state guards.

A fake bridge stands in for Ableton. Tests prove call ordering and that a refusal
or no-op never writes, a success writes exactly once, and a failed readback never
retries.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from abletongpt.device_repair import (
    REASON_DEVICE_IDENTITY_MISMATCH,
    REASON_INVALID_INDEX,
    REASON_PARAMETER_IDENTITY_MISMATCH,
    REASON_POSTCONDITION_FAILED,
    REASON_STATE_PRECONDITION_FAILED,
    REASON_TARGET_NOT_FOUND,
    REASON_TRACK_IDENTITY_MISMATCH,
    REASON_UNSUPPORTED_OPERATION,
    STATUS_FAILED,
    STATUS_NOOP,
    STATUS_REFUSED,
    STATUS_REPAIRED,
    is_mutation_command,
    repair_live_device,
)
from abletongpt import server


def _parameter(
    index: int = 1,
    name: str = "Dry/Wet",
    value: float = 0.25,
    default_value: float = 0.0,
    minimum: float = 0.0,
    maximum: float = 1.0,
    *,
    is_enabled: bool = True,
    is_quantized: bool = False,
) -> dict[str, Any]:
    span = maximum - minimum
    normalized = 0.0 if span == 0 else (value - minimum) / span
    payload: dict[str, Any] = {
        "index": index,
        "name": name,
        "value": value,
        "normalized_value": normalized,
        "min": minimum,
        "max": maximum,
        "is_enabled": is_enabled,
        "is_quantized": is_quantized,
    }
    if not is_quantized:
        payload["default_value"] = default_value
    else:
        payload["value_items"] = ["Off", "On"]
    return payload


def _power_parameter(enabled: bool = True) -> dict[str, Any]:
    value = 1.0 if enabled else 0.0
    return _parameter(
        index=0,
        name="Device On",
        value=value,
        default_value=1.0,
        minimum=0.0,
        maximum=1.0,
        is_quantized=True,
    )


def _device(
    *,
    index: int = 0,
    name: str = "Auto Filter",
    power_on: bool = True,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    params = parameters if parameters is not None else [_power_parameter(power_on), _parameter()]
    return {
        "index": index,
        "name": name,
        "class_name": "AutoFilter",
        "class_display_name": name,
        "type": 2,
        "is_active": power_on,
        "parameters": params,
    }


def _listing(
    *,
    track_index: int = 1,
    track: str = "Bass",
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "track_index": track_index,
        "track": track,
        "devices": devices if devices is not None else [_device()],
    }


class FakeDeviceBridge:
    """Live stand-in that records every call and optionally applies one mutation."""

    def __init__(
        self,
        listing: dict[str, Any] | None = None,
        *,
        apply_mutation: bool = True,
        mutation_error: Exception | None = None,
    ) -> None:
        self.listing = copy.deepcopy(listing if listing is not None else _listing())
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.apply_mutation = apply_mutation
        self.mutation_error = mutation_error

    def call(self, command: str, **params: Any) -> Any:
        self.calls.append((command, dict(params)))
        if command == "get_track_devices":
            return copy.deepcopy(self.listing)
        if command == "set_device_parameter":
            if self.mutation_error is not None:
                raise self.mutation_error
            if self.apply_mutation:
                self._set_parameter(params)
            return {"device": "Auto Filter", "parameter": {"index": params["parameter_index"]}}
        if command == "reset_device_parameter":
            if self.mutation_error is not None:
                raise self.mutation_error
            if self.apply_mutation:
                self._reset_parameter(params)
            return {"device": "Auto Filter"}
        if command == "set_device_power":
            if self.mutation_error is not None:
                raise self.mutation_error
            if self.apply_mutation:
                self._set_power(params)
            return {"device": "Auto Filter", "enabled": params["enabled"]}
        raise AssertionError("unexpected command: %s" % command)

    def _device(self, device_index: int) -> dict[str, Any]:
        return self.listing["devices"][device_index]

    def _set_parameter(self, params: dict[str, Any]) -> None:
        parameter = self._device(params["device_index"])["parameters"][params["parameter_index"]]
        value = float(params["value"])
        if params.get("normalized"):
            span = float(parameter["max"]) - float(parameter["min"])
            value = float(parameter["min"]) + value * span
        parameter["value"] = value
        span = float(parameter["max"]) - float(parameter["min"])
        parameter["normalized_value"] = 0.0 if span == 0 else (value - float(parameter["min"])) / span

    def _reset_parameter(self, params: dict[str, Any]) -> None:
        parameter = self._device(params["device_index"])["parameters"][params["parameter_index"]]
        parameter["value"] = float(parameter["default_value"])
        span = float(parameter["max"]) - float(parameter["min"])
        parameter["normalized_value"] = (
            0.0 if span == 0 else (parameter["value"] - float(parameter["min"])) / span
        )

    def _set_power(self, params: dict[str, Any]) -> None:
        device = self._device(params["device_index"])
        enabled = bool(params["enabled"])
        device["is_active"] = enabled
        device["parameters"][0]["value"] = 1.0 if enabled else 0.0
        device["parameters"][0]["normalized_value"] = 1.0 if enabled else 0.0

    def mutations(self) -> list[tuple[str, dict[str, Any]]]:
        return [(command, params) for command, params in self.calls if is_mutation_command(command)]

    def reads(self) -> list[tuple[str, dict[str, Any]]]:
        return [(command, params) for command, params in self.calls if command == "get_track_devices"]


def _request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "track_index": 1,
        "device_index": 0,
        "operation": "set_device_parameter",
        "parameter_index": 1,
        "value": 0.8,
        "expected_track_name": "Bass",
        "expected_device_name": "Auto Filter",
        "expected_parameter_name": "Dry/Wet",
        "expected_current_value": 0.25,
    }
    base.update(overrides)
    return base


def test_set_device_parameter_successful_repair():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request())

    assert result["status"] == STATUS_REPAIRED
    assert result["mutation_performed"] is True
    assert result["operation"] == "set_device_parameter"
    assert result["before"]["parameter"]["value"] == 0.25
    assert result["after"]["parameter"]["value"] == pytest.approx(0.8)
    assert len(bridge.mutations()) == 1
    assert bridge.mutations()[0][0] == "set_device_parameter"


def test_reset_device_parameter_successful_repair():
    bridge = FakeDeviceBridge()
    result = repair_live_device(
        bridge,
        _request(
            operation="reset_device_parameter",
            value=None,
            expected_current_value=0.25,
        ),
    )

    assert result["status"] == STATUS_REPAIRED
    assert result["after"]["parameter"]["value"] == pytest.approx(0.0)
    assert bridge.mutations() == [
        (
            "reset_device_parameter",
            {"track_index": 1, "device_index": 0, "parameter_index": 1},
        )
    ]


def test_set_device_power_successful_repair():
    bridge = FakeDeviceBridge()
    result = repair_live_device(
        bridge,
        {
            "track_index": 1,
            "device_index": 0,
            "operation": "set_device_power",
            "enabled": False,
            "expected_track_name": "Bass",
            "expected_device_name": "Auto Filter",
            "expected_power_state": True,
        },
    )

    assert result["status"] == STATUS_REPAIRED
    assert result["after"]["power_on"] is False
    assert bridge.mutations() == [
        ("set_device_power", {"track_index": 1, "device_index": 0, "enabled": False})
    ]


def test_already_correct_state_is_noop():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(value=0.25))

    assert result["status"] == STATUS_NOOP
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []
    assert [command for command, _ in bridge.calls] == ["get_track_devices"]


def test_already_correct_power_is_noop():
    bridge = FakeDeviceBridge()
    result = repair_live_device(
        bridge,
        {
            "track_index": 1,
            "device_index": 0,
            "operation": "set_device_power",
            "enabled": True,
        },
    )

    assert result["status"] == STATUS_NOOP
    assert bridge.mutations() == []


def test_wrong_track_identity_refuses_without_mutation():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(expected_track_name="Drums"))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_TRACK_IDENTITY_MISMATCH
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []


def test_wrong_device_identity_refuses_without_mutation():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(expected_device_name="Reverb"))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_DEVICE_IDENTITY_MISMATCH
    assert bridge.mutations() == []


def test_wrong_parameter_identity_refuses_without_mutation():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(expected_parameter_name="Frequency"))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_PARAMETER_IDENTITY_MISMATCH
    assert bridge.mutations() == []


def test_stale_parameter_value_refuses_without_mutation():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(expected_current_value=0.99))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_STATE_PRECONDITION_FAILED
    assert bridge.mutations() == []


def test_stale_power_state_refuses_without_mutation():
    bridge = FakeDeviceBridge()
    result = repair_live_device(
        bridge,
        {
            "track_index": 1,
            "device_index": 0,
            "operation": "set_device_power",
            "enabled": False,
            "expected_power_state": False,
        },
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_STATE_PRECONDITION_FAILED
    assert bridge.mutations() == []


def test_unsupported_operation_refuses_without_live_write():
    bridge = FakeDeviceBridge()
    result = repair_live_device(
        bridge,
        {
            "track_index": 1,
            "device_index": 0,
            "operation": "add_native_device",
            "parameter_index": 1,
            "value": 0.5,
        },
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_UNSUPPORTED_OPERATION
    assert result["mutation_performed"] is False
    assert bridge.calls == []


@pytest.mark.parametrize("track_index", [-1, True, 1.5, "0"])
def test_invalid_track_index_causes_zero_writes(track_index):
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(track_index=track_index))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.calls == []
    assert bridge.mutations() == []


@pytest.mark.parametrize("device_index", [-1, True, 1.5, "0"])
def test_invalid_device_index_causes_zero_writes(device_index):
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(device_index=device_index))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.mutations() == []
    assert bridge.calls == []


@pytest.mark.parametrize("parameter_index", [-1, True, 1.5, "1"])
def test_invalid_parameter_index_causes_zero_writes(parameter_index):
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(parameter_index=parameter_index))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.mutations() == []
    assert bridge.calls == []


def test_missing_device_index_is_target_not_found_after_read():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(device_index=9))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_TARGET_NOT_FOUND
    assert bridge.mutations() == []
    assert [command for command, _ in bridge.calls] == ["get_track_devices"]


def test_missing_parameter_index_is_target_not_found_after_read():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _request(parameter_index=9))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_TARGET_NOT_FOUND
    assert bridge.mutations() == []


def test_mutation_acknowledgement_without_matching_readback_is_failed():
    bridge = FakeDeviceBridge(apply_mutation=False)
    result = repair_live_device(bridge, _request())

    assert result["status"] == STATUS_FAILED
    assert result["reason"] == REASON_POSTCONDITION_FAILED
    assert result["mutation_performed"] is True
    assert result["after"]["parameter"]["value"] == pytest.approx(0.25)


def test_postcondition_failure_does_not_retry():
    bridge = FakeDeviceBridge(apply_mutation=False)
    repair_live_device(bridge, _request())

    assert len(bridge.mutations()) == 1
    assert [command for command, _ in bridge.calls] == [
        "get_track_devices",
        "set_device_parameter",
        "get_track_devices",
    ]


def test_successful_repair_performs_exactly_one_mutation():
    bridge = FakeDeviceBridge()
    repair_live_device(bridge, _request())
    assert len(bridge.mutations()) == 1


def test_read_happens_before_mutation():
    bridge = FakeDeviceBridge()
    repair_live_device(bridge, _request())

    commands = [command for command, _ in bridge.calls]
    assert commands[0] == "get_track_devices"
    assert commands[1] == "set_device_parameter"


def test_postcondition_read_happens_after_mutation():
    bridge = FakeDeviceBridge()
    repair_live_device(bridge, _request())

    commands = [command for command, _ in bridge.calls]
    assert commands[-1] == "get_track_devices"
    assert commands.index("set_device_parameter") < len(commands) - 1
    assert commands.count("get_track_devices") == 2


def test_server_tool_forwards_to_the_guarded_engine(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.repair_live_device(
        track_index=1,
        device_index=0,
        operation="set_device_parameter",
        parameter_index=1,
        value=0.8,
        expected_track_name="Bass",
        expected_device_name="Auto Filter",
        expected_parameter_name="Dry/Wet",
        expected_current_value=0.25,
    )

    assert result["status"] == STATUS_REPAIRED
    assert len(bridge.mutations()) == 1


def test_locked_parameter_refuses_without_mutation():
    listing = _listing(
        devices=[
            _device(
                parameters=[
                    _power_parameter(True),
                    _parameter(is_enabled=False),
                ]
            )
        ]
    )
    bridge = FakeDeviceBridge(listing)
    result = repair_live_device(bridge, _request())

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == "parameter_locked"
    assert bridge.mutations() == []


def test_mutation_rejection_is_failed_and_does_not_retry():
    bridge = FakeDeviceBridge(mutation_error=RuntimeError("parameter is currently locked or macro-controlled"))
    result = repair_live_device(bridge, _request())

    assert result["status"] == STATUS_FAILED
    assert result["reason"] == "mutation_rejected"
    assert result["mutation_performed"] is True
    assert len(bridge.mutations()) == 1
    assert [command for command, _ in bridge.calls] == [
        "get_track_devices",
        "set_device_parameter",
        "get_track_devices",
    ]


def test_capabilities_name_guarded_device_repair():
    capabilities = server.get_abletongpt_capabilities()
    assert any("guarded selective device repair" in feature for feature in capabilities["features"])
    assert any("one mutation maximum" in rule for rule in capabilities["safety"])


def test_existing_get_track_devices_still_forwards(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.get_track_devices(1)

    assert result["track"] == "Bass"
    assert bridge.calls == [("get_track_devices", {"track_index": 1})]
    assert bridge.mutations() == []


def test_existing_set_device_parameter_still_forwards(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.set_device_parameter(1, 0, 1, 0.8)

    assert bridge.calls == [
        (
            "set_device_parameter",
            {
                "track_index": 1,
                "device_index": 0,
                "parameter_index": 1,
                "value": 0.8,
                "normalized": False,
            },
        )
    ]


def test_existing_reset_device_parameter_still_forwards(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.reset_device_parameter(1, 0, 1)

    assert bridge.calls == [
        (
            "reset_device_parameter",
            {"track_index": 1, "device_index": 0, "parameter_index": 1},
        )
    ]


def test_existing_set_device_power_still_forwards(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.set_device_power(1, 0, False)

    assert bridge.calls == [
        ("set_device_power", {"track_index": 1, "device_index": 0, "enabled": False})
    ]


def test_existing_device_tools_reject_negative_indexes_before_the_bridge(monkeypatch):
    bridge = FakeDeviceBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    with pytest.raises(ValueError):
        server.get_track_devices(-1)
    with pytest.raises(ValueError):
        server.set_device_parameter(-1, 0, 0, 0.5)
    with pytest.raises(ValueError):
        server.reset_device_parameter(0, -1, 0)
    with pytest.raises(ValueError):
        server.set_device_power(-1, 0, True)

    assert bridge.calls == []
