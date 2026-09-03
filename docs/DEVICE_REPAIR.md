# Guarded selective device repair

A small, same-process repair primitive for **one** Ableton Live device parameter
or power state. It is not a general repair engine.

Public MCP tool: `repair_live_device`.

## Contract

```text
READ LIVE          get_track_devices
    ↓
VALIDATE           target indexes + optional identity/state preconditions
    ↓
ZERO OR ONE WRITE  set_device_parameter | reset_device_parameter | set_device_power
    ↓
READ LIVE          get_track_devices
    ↓
VERIFY             postcondition from the second read, not the mutation acknowledgement
    ↓
STRUCTURED RESULT  repaired | noop | refused | failed
```

One request performs at most one Live mutation. A no-op or a refusal sends none.
A failed postcondition does not retry.

## Supported operations

Exactly one of:

- `set_device_parameter`
- `reset_device_parameter`
- `set_device_power`

Range checks, locked/macro-controlled parameters and device-power behaviour stay
in the existing Remote Script commands. This layer does not insert, delete,
replace or reorder devices.

## Guards

Optional expected-state fields, checked against `get_track_devices` before any
write:

- `expected_track_name`
- `expected_device_name`
- `expected_parameter_name`
- `expected_current_value` (Live `parameter.value`)
- `expected_power_state` (Device On / `is_active`)

A mismatch returns `status: "refused"` with a stable `reason` such as
`track_identity_mismatch`, `device_identity_mismatch`,
`parameter_identity_mismatch`, `state_precondition_failed`,
`unsupported_operation`, `target_not_found`, or `invalid_index`.

If Live already satisfies the requested postcondition, the result is
`status: "noop"` and no mutation is sent.

## Exclusions

Not implemented: session-clip repair, arrangement repair, track reconstruction,
device insertion/replacement, multi-device or batch repair, JobPlan replay,
KIHACHI recovery, generic reconciliation, or continuous monitoring.
