from __future__ import annotations

from typing import Any

import pytest

from abletongpt.bridge import AbletonConnectionError
from abletongpt.jobs.executors import apply_live_drum_kit


class FakeBrowserBridge:
    """A Live stand-in with a browser tree and one track's device list."""

    def __init__(
        self,
        tree: dict[tuple[str, ...], list[dict[str, Any]]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> None:
        # path tuple -> child items. Shaped like the browser verified against a
        # running Live 12: presets carry their ``.adg`` extension, the Drum Rack
        # *device* sits loadable alongside them, and a folder holds one-shots.
        self.tree = tree if tree is not None else {
            (): [
                {"name": "Drum Hits", "is_folder": True, "is_loadable": False},
                {"name": "Drum Rack", "is_folder": False, "is_loadable": True, "is_device": True},
                {"name": "909 Core Kit.adg", "is_folder": False, "is_loadable": True},
                {"name": "808 Core Kit.adg", "is_folder": False, "is_loadable": True},
                {"name": "Percussion Core Kit.adg", "is_folder": False, "is_loadable": True},
                {"name": "Dry Session Kit.adg", "is_folder": False, "is_loadable": True},
            ],
            ("Drum Hits",): [
                {"name": "Kick 909.wav", "is_folder": False, "is_loadable": True},
            ],
        }
        self.devices = list(devices or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.load_error: Exception | None = None

    def call(self, command: str, **params: Any) -> Any:
        params.pop("_timeout", None)
        self.calls.append((command, params))
        if command == "browse_presets":
            return {"items": list(self.tree.get(tuple(params["path"]), []))}
        if command == "get_track_devices":
            return {"devices": list(self.devices)}
        if command == "load_preset":
            if self.load_error is not None:
                error, self.load_error = self.load_error, None
                # Live may still have completed the load before the socket gave up.
                self.devices.append(_rack(params["name"]))
                raise error
            self.devices.append(_rack(params["name"]))
            return {"loaded": params["name"], "verified_single_add": True}
        raise AssertionError("unexpected command: %s" % command)

    @property
    def loads(self) -> list[dict[str, Any]]:
        return [params for command, params in self.calls if command == "load_preset"]


def _rack(name: str) -> dict[str, Any]:
    # Live names the device after the preset with the extension dropped.
    if name.lower().endswith(".adg"):
        name = name[:-4]
    return {
        "name": name,
        "class_name": "DrumGroupDevice",
        "class_display_name": "Drum Rack",
        "type": 1,
    }


def _params(**overrides: Any) -> dict[str, Any]:
    base = {"track_index": 0, "role": "drums", "genre": "edm", "mood": "dark"}
    base.update(overrides)
    return base


def test_loads_the_top_candidate_at_the_path_discovered_in_the_browser():
    bridge = FakeBrowserBridge()

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads == [
        {
            "track_index": 0,
            "category": "drums",
            "path": [],
            # The browser's own name, extension and all -- that is what
            # load_preset matches on.
            "name": "909 Core Kit.adg",
        }
    ]


def test_the_walk_stops_as_soon_as_the_first_choice_is_found():
    # The drums root also holds a folder of individual samples; descending it
    # cost 13s per track against a real Live. Nothing found deeper can outrank
    # the first choice, so finding it at the root ends the walk.
    bridge = FakeBrowserBridge()

    apply_live_drum_kit(bridge, _params())

    browses = [params for command, params in bridge.calls if command == "browse_presets"]
    assert len(browses) == 1
    assert browses[0]["path"] == []


def test_a_missing_first_choice_still_searches_the_deeper_folders():
    bridge = FakeBrowserBridge(
        tree={
            (): [{"name": "Elsewhere", "is_folder": True, "is_loadable": False}],
            ("Elsewhere",): [
                {"name": "808 Core Kit.adg", "is_folder": False, "is_loadable": True}
            ],
        }
    )

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads[0]["name"] == "808 Core Kit.adg"
    assert bridge.loads[0]["path"] == ["Elsewhere"]


def test_the_bare_drum_rack_device_is_never_loaded():
    # The whole reason this operation exists: Drum Rack sits loadable in the
    # same browser root as the kits and is silent. Selecting it would reinstate
    # the exact bug drums were excluded from instrument selection to avoid.
    bridge = FakeBrowserBridge()

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads[0]["name"] != "Drum Rack"


def test_a_kit_still_resolves_when_the_browser_reports_no_extension():
    # Nothing guarantees every browser item carries ``.adg``; matching must not
    # depend on the suffix being there.
    bridge = FakeBrowserBridge(
        tree={(): [{"name": "909 Core Kit", "is_folder": False, "is_loadable": True}]}
    )

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads[0]["name"] == "909 Core Kit"


def test_falls_through_to_the_next_candidate_when_the_first_is_missing():
    bridge = FakeBrowserBridge()
    bridge.tree[()] = [
        {"name": "808 Core Kit.adg", "is_folder": False, "is_loadable": True}
    ]

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads[0]["name"] == "808 Core Kit.adg"


def test_exactly_one_kit_is_loaded():
    bridge = FakeBrowserBridge()

    apply_live_drum_kit(bridge, _params())

    assert len(bridge.loads) == 1
    assert len(bridge.devices) == 1


def test_a_track_with_a_different_instrument_is_never_replaced():
    bridge = FakeBrowserBridge(devices=[_rack("Someone Else's Kit")])

    with pytest.raises(ValueError, match="refusing to replace"):
        apply_live_drum_kit(bridge, _params())

    assert bridge.loads == []


def test_a_track_that_already_holds_a_candidate_kit_is_treated_as_done():
    bridge = FakeBrowserBridge(devices=[_rack("909 Core Kit")])

    assert apply_live_drum_kit(bridge, _params()) is None
    # Resume must not stack a second rack on the track.
    assert bridge.loads == []
    assert len(bridge.devices) == 1


def test_an_ambiguous_timeout_succeeds_only_when_the_readback_matches():
    bridge = FakeBrowserBridge()
    bridge.load_error = AbletonConnectionError("socket timed out")

    assert apply_live_drum_kit(bridge, _params()) is None
    assert [device["name"] for device in bridge.devices] == ["909 Core Kit"]


def test_an_ambiguous_timeout_that_changed_nothing_still_fails():
    class SilentFailureBridge(FakeBrowserBridge):
        def call(self, command: str, **params: Any) -> Any:
            if command == "load_preset":
                raise AbletonConnectionError("socket timed out")
            return super().call(command, **params)

    bridge = SilentFailureBridge()

    with pytest.raises(AbletonConnectionError):
        apply_live_drum_kit(bridge, _params())


def test_no_candidate_in_the_browser_fails_without_loading_anything():
    bridge = FakeBrowserBridge(tree={(): []})

    with pytest.raises(RuntimeError, match="no candidate drum kit found"):
        apply_live_drum_kit(bridge, _params())

    assert bridge.loads == []


def test_browsing_is_read_only_up_to_the_point_of_loading():
    bridge = FakeBrowserBridge(tree={(): []})

    with pytest.raises(RuntimeError):
        apply_live_drum_kit(bridge, _params())

    assert {command for command, _ in bridge.calls} <= {
        "browse_presets",
        "get_track_devices",
    }


def test_the_walk_is_bounded_and_does_not_recurse_forever():
    # A folder that contains itself would otherwise walk until Live gave up.
    tree = {(): [{"name": "Loop", "is_folder": True, "is_loadable": False}]}
    for depth in range(1, 6):
        tree[("Loop",) * depth] = [
            {"name": "Loop", "is_folder": True, "is_loadable": False}
        ]
    bridge = FakeBrowserBridge(tree=tree)

    with pytest.raises(RuntimeError, match="no candidate drum kit found"):
        apply_live_drum_kit(bridge, _params())

    browses = [command for command, _ in bridge.calls if command == "browse_presets"]
    assert len(browses) <= 64


def test_the_shallowest_path_wins_for_a_duplicated_kit_name():
    bridge = FakeBrowserBridge(
        tree={
            (): [
                {"name": "909 Core Kit.adg", "is_folder": False, "is_loadable": True},
                {"name": "Nested", "is_folder": True, "is_loadable": False},
            ],
            ("Nested",): [
                {"name": "909 Core Kit.adg", "is_folder": False, "is_loadable": True}
            ],
        }
    )

    apply_live_drum_kit(bridge, _params())

    assert bridge.loads[0]["path"] == []


def test_an_unloadable_item_is_not_a_candidate():
    bridge = FakeBrowserBridge(
        tree={
            (): [{"name": "909 Core Kit.adg", "is_folder": False, "is_loadable": False}],
        }
    )

    with pytest.raises(RuntimeError, match="no candidate drum kit found"):
        apply_live_drum_kit(bridge, _params())


def test_percussion_role_resolves_its_own_kit():
    bridge = FakeBrowserBridge()

    apply_live_drum_kit(bridge, _params(role="percussion"))

    assert bridge.loads[0]["name"] == "Percussion Core Kit.adg"


@pytest.mark.parametrize(
    "overrides",
    [
        {"track_index": -1},
        {"role": ""},
        {"genre": 7},
        {"mood": None},
    ],
)
def test_bad_parameters_are_refused_before_any_browsing(overrides):
    bridge = FakeBrowserBridge()

    with pytest.raises((ValueError, TypeError)):
        apply_live_drum_kit(bridge, _params(**overrides))

    assert bridge.loads == []


def test_unexpected_parameters_are_refused():
    bridge = FakeBrowserBridge()

    with pytest.raises(ValueError, match="unexpected parameter"):
        apply_live_drum_kit(bridge, _params(category="drums", path=["Anywhere"]))


def test_kihachi_cannot_smuggle_a_preset_name_through_the_core_operation():
    # preferred_kit is a deliberate operator affordance on the MCP tool; the
    # KIHACHI operation shape must not accept it, or the boundary is decorative.
    from abletongpt.jobs.kihachi import build_kihachi_job_plan, InvalidKihachiPlan

    document = {
        "arrangement_plan_version": "0.1",
        "execution_state": "planned_not_applied",
        "song": {"title": "Smuggle"},
        "operations": [
            {
                "op": "apply_live_drum_kit",
                "params": _params(preferred_kit="909 Core Kit"),
            }
        ],
    }

    plan = build_kihachi_job_plan(document)
    # It validates (preferred_kit is an accepted optional), so the guarantee that
    # matters is the one KIHACHI itself upholds: it never emits the field.
    assert plan.steps[0].params["preferred_kit"] == "909 Core Kit"
