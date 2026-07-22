"""Non-destructive state snapshots: normalize and diff a Live Set's mix state.

Pure logic, no Live connection. :func:`build_snapshot` folds the read-only ``get_state``
and ``get_mix_snapshot`` bridge responses into one stable, serializable snapshot;
:func:`diff_snapshots` compares two such snapshots and reports exactly what changed. Both
are deterministic (they take any timestamp as an argument rather than reading a clock) so
they unit-test in isolation.

Momentary meter levels (``output_meter_level``) are deliberately dropped: they fluctuate
frame to frame and are not part of the set's state, so keeping them would make every diff
noisy. Snapshots are a read-only capture -- nothing here mutates a Live Set.
"""

from __future__ import annotations

from typing import Any

SNAPSHOT_VERSION = 1

# Mixer fields compared per track/return/master. Floats use `_TOLERANCE`; the rest exact.
_NUMERIC_FIELDS = ("volume", "pan")
_BOOLEAN_FIELDS = ("mute", "solo", "arm")
_TOLERANCE = 1e-6


def _mix_track(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize one mix-snapshot track/return/master entry, dropping the momentary meter."""
    normalized: dict[str, Any] = {
        "index": entry.get("index"),
        "name": entry.get("name"),
        "volume": entry.get("volume"),
        "pan": entry.get("pan"),
        "mute": bool(entry.get("mute", False)),
        "solo": bool(entry.get("solo", False)),
        "sends": [
            {"index": send.get("index"), "value": send.get("value")}
            for send in entry.get("sends", [])
        ],
    }
    return normalized


def build_snapshot(
    state: dict[str, Any],
    mix: dict[str, Any],
    *,
    label: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Fold ``get_state`` + ``get_mix_snapshot`` responses into one normalized snapshot.

    Per-track mix parameters (volume/pan/mute/solo/sends) come from ``mix``; ``arm`` and
    ``clip_slots`` are merged in from ``state`` by matching track index. Returns and master
    come from ``mix``. Momentary meter levels are excluded so the result is stable.
    """
    state_by_index = {track.get("index"): track for track in state.get("tracks", [])}

    tracks: list[dict[str, Any]] = []
    for entry in mix.get("tracks", []):
        track = _mix_track(entry)
        source = state_by_index.get(track["index"], {})
        track["arm"] = bool(source.get("arm", False))
        track["clip_slots"] = source.get("clip_slots")
        tracks.append(track)

    signature = state.get("signature")
    return {
        "read_only": True,
        "snapshot_version": SNAPSHOT_VERSION,
        "label": label,
        "captured_at": captured_at,
        "transport": {
            "tempo": state.get("tempo"),
            "signature": list(signature) if signature is not None else None,
            "scene_count": state.get("scene_count"),
        },
        "tracks": tracks,
        "returns": [_mix_track(entry) for entry in mix.get("returns", [])],
        "master": _mix_track(mix["master"]) if mix.get("master") is not None else None,
    }


def _changed(before: Any, after: Any, *, numeric: bool) -> bool:
    if numeric and isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return abs(float(before) - float(after)) > _TOLERANCE
    return before != after


def _diff_channel(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Field-level diff of two normalized channels (track/return/master)."""
    changes: dict[str, Any] = {}
    if before.get("name") != after.get("name"):
        changes["name"] = {"before": before.get("name"), "after": after.get("name")}
    for field in _NUMERIC_FIELDS:
        if _changed(before.get(field), after.get(field), numeric=True):
            changes[field] = {"before": before.get(field), "after": after.get(field)}
    for field in _BOOLEAN_FIELDS:
        if field in before or field in after:
            if _changed(before.get(field), after.get(field), numeric=False):
                changes[field] = {"before": before.get(field), "after": after.get(field)}

    send_changes = []
    before_sends = {send.get("index"): send.get("value") for send in before.get("sends", [])}
    after_sends = {send.get("index"): send.get("value") for send in after.get("sends", [])}
    for index in sorted(set(before_sends) | set(after_sends), key=lambda value: (value is None, value)):
        if _changed(before_sends.get(index), after_sends.get(index), numeric=True):
            send_changes.append(
                {"index": index, "before": before_sends.get(index), "after": after_sends.get(index)}
            )
    if send_changes:
        changes["sends"] = send_changes
    return changes


def _diff_channel_list(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, Any]:
    """Diff two lists of channels matched by index; report added/removed/changed."""
    before_by_index = {channel.get("index"): channel for channel in before}
    after_by_index = {channel.get("index"): channel for channel in after}

    changed = []
    for index in sorted(set(before_by_index) & set(after_by_index), key=lambda v: (v is None, v)):
        channel_changes = _diff_channel(before_by_index[index], after_by_index[index])
        if channel_changes:
            changed.append({"index": index, "changes": channel_changes})

    added = [
        {"index": index, "name": after_by_index[index].get("name")}
        for index in sorted(set(after_by_index) - set(before_by_index), key=lambda v: (v is None, v))
    ]
    removed = [
        {"index": index, "name": before_by_index[index].get("name")}
        for index in sorted(set(before_by_index) - set(after_by_index), key=lambda v: (v is None, v))
    ]
    return {"changed": changed, "added": added, "removed": removed}


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two snapshots built by :func:`build_snapshot`; report what changed.

    Tracks, returns, and master are matched by index. Returns a structured diff plus a
    top-level ``changed`` flag that is ``True`` when anything differs.
    """
    transport_changes: dict[str, Any] = {}
    before_transport = before.get("transport", {})
    after_transport = after.get("transport", {})
    if _changed(before_transport.get("tempo"), after_transport.get("tempo"), numeric=True):
        transport_changes["tempo"] = {
            "before": before_transport.get("tempo"),
            "after": after_transport.get("tempo"),
        }
    for field in ("signature", "scene_count"):
        if _changed(before_transport.get(field), after_transport.get(field), numeric=False):
            transport_changes[field] = {
                "before": before_transport.get(field),
                "after": after_transport.get(field),
            }

    tracks = _diff_channel_list(before.get("tracks", []), after.get("tracks", []))
    returns = _diff_channel_list(before.get("returns", []), after.get("returns", []))
    master_before = before.get("master")
    master_after = after.get("master")
    master_changes = (
        _diff_channel(master_before, master_after)
        if master_before is not None and master_after is not None
        else {}
    )

    changed = bool(
        transport_changes
        or tracks["changed"]
        or tracks["added"]
        or tracks["removed"]
        or returns["changed"]
        or returns["added"]
        or returns["removed"]
        or master_changes
    )
    return {
        "read_only": True,
        "changed": changed,
        "transport": transport_changes,
        "tracks": tracks,
        "returns": returns,
        "master": master_changes,
    }
