# Guarded selective Session MIDI clip repair

A small, same-process repair primitive for **one** Ableton Live Session MIDI
clip. It is not a general repair engine.

Public MCP tool: `repair_live_session_midi_clip`.

```text
candidate repairable != automatically safe
```

This primitive repairs at most one Session MIDI clip with explicit state guards.
It is not Arrangement repair and it is not a generic reconciliation engine.

## Contract

```text
READ LIVE          get_state, then get_midi_clip_notes
    ↓
VALIDATE           track/clip indexes + occupancy + optional identity/state guards
    ↓
ZERO OR ONE WRITE  create_midi_clip (empty Session slot only)
    ↓
READ LIVE          get_midi_clip_notes
    ↓
VERIFY             postcondition from the second read, not the mutation acknowledgement
    ↓
STRUCTURED RESULT  repaired | noop | refused | failed
```

One request performs at most one Live mutation. A no-op or a refusal sends none.
A failed postcondition does not retry. There is no fallback chain.

## Supported repair shape

Exactly one:

- Populate an **empty** Session MIDI slot with `create_midi_clip`, when
  `expected_slot_state="empty"` and every identity/state guard matched.

`create_midi_clip` is already additive and refuses an occupied slot. Desired
notes are restricted to fields that command can write **and**
`get_midi_clip_notes` can prove: pitch, start time, duration, velocity.
Probability other than `1.0` and muted notes are refused — the create path
cannot write probability, and mute is not returned on readback.

If Live already holds the requested clip (name, length, canonical notes), the
result is `status: "noop"` and no mutation is sent.

## Explicitly refused repair shapes

A candidate that looks repairable is still refused when it is not a single
safe mutation:

- replacing notes on an existing clip (`unsupported_repair_shape`) — Live's
  `apply_expression_to_clip` clears then recreates notes
- delete + create, clear + recreate, or any retry
- Arrangement clips
- track creation or deletion as recovery
- clip deletion
- batch / multi-clip repair
- JobPlan replay

Occupancy is a hard guard: an occupied slot when `empty` was expected, or an
empty slot when `existing` was expected, returns `slot_occupancy_mismatch`
with zero mutations.

## Guards

Optional expected-state fields, checked against Live before any write:

- `expected_track_name`
- `expected_clip_name`
- `expected_clip_length`
- `expected_note_count`
- `expected_notes` (canonical note list; order does not matter)
- `expected_note_digest` (SHA-256 of the canonical note serialization)

Required target identity:

- `track_index`
- `clip_index`
- `expected_slot_state` (`empty` or `existing`)

Notes are canonicalized before comparison (pitch, start, duration, velocity,
probability). Ordering differences alone are not a mismatch. Digests use
deterministic JSON + SHA-256, never Python's process-randomized `hash()`.

## Exclusions

Not implemented: Arrangement repair, track reconstruction, clip deletion,
device repair, device insertion/replacement, batch repair, JobPlan replay,
KIHACHI recovery, generic reconciliation, or continuous monitoring.
This module knows nothing about KIHACHI plans, check IDs, or provenance.
