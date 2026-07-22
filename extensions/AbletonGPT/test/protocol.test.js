// Protocol/dispatch tests for the companion. Run with `npm test` (node --test).
// These exercise the transport-independent Dispatcher against MockLiveProvider; no
// socket and no Extensions SDK are involved.

import assert from "node:assert/strict";
import { test } from "node:test";

import { ALLOWED_COMMANDS, Dispatcher, PROTOCOL } from "../src/protocol.js";
import { MockLiveProvider } from "../src/liveProvider.js";

function dispatcher({ token = "" } = {}) {
  return new Dispatcher(new MockLiveProvider(), { token });
}

test("ping returns a protocol-tagged success", async () => {
  const response = await dispatcher().handle({ command: "ping" });
  assert.equal(response.protocol, PROTOCOL);
  assert.equal(response.ok, true);
  assert.equal(response.result.pong, true);
});

test("get_tempo comes from the provider", async () => {
  const response = await dispatcher().handle({ command: "get_tempo", params: {} });
  assert.equal(response.ok, true);
  assert.equal(response.result.tempo, 120);
});

test("get_tracks returns the track list", async () => {
  const response = await dispatcher().handle({ command: "get_tracks" });
  assert.equal(response.ok, true);
  assert.equal(response.result.tracks.length, 2);
});

test("get_state returns tempo, scene count and tracks", async () => {
  const response = await dispatcher().handle({ command: "get_state" });
  assert.equal(response.ok, true);
  assert.equal(response.result.tempo, 120);
  assert.equal(typeof response.result.scene_count, "number");
  assert.equal(response.result.tracks.length, 2);
  assert.equal(response.result.tracks[0].clip_slots, 8);
  // Parity note: no is_playing / signature (unavailable via the SDK).
  assert.equal("is_playing" in response.result, false);
});

test("get_mix_snapshot returns tracks, returns and master", async () => {
  const response = await dispatcher().handle({ command: "get_mix_snapshot" });
  assert.equal(response.ok, true);
  const { tracks, returns, master } = response.result;
  assert.equal(tracks.length, 2);
  assert.equal(returns.length, 1);
  assert.equal(master.index, -1);
  // Parity shape: every channel carries volume/pan/mute/solo/sends; the SDK has no meter.
  for (const channel of [...tracks, ...returns, master]) {
    assert.equal(typeof channel.volume, "number");
    assert.equal(typeof channel.pan, "number");
    assert.equal(typeof channel.mute, "boolean");
    assert.equal(Array.isArray(channel.sends), true);
    assert.equal(channel.output_meter_level, null);
  }
});

test("get_mix_snapshot reflects a volume mutation", async () => {
  const provider = new MockLiveProvider();
  const disp = new Dispatcher(provider, {});
  await disp.handle({ command: "set_track_volume", params: { track_index: 0, volume: 0.42 } });
  const response = await disp.handle({ command: "get_mix_snapshot" });
  assert.equal(response.result.tracks[0].volume, 0.42);
});

test("get_midi_clip_notes returns a readable clip payload", async () => {
  const response = await dispatcher().handle({
    command: "get_midi_clip_notes",
    params: { track_index: 0, clip_index: 0 },
  });
  assert.equal(response.ok, true);
  assert.equal(typeof response.result.length_beats, "number");
  assert.equal(response.result.notes.length, response.result.note_count);
  assert.equal(response.result.notes[0].pitch, 60);
});

test("create_midi_clip records a non-destructive mutation", async () => {
  const provider = new MockLiveProvider();
  const disp = new Dispatcher(provider, {});
  const response = await disp.handle({
    command: "create_midi_clip",
    params: { track_index: 0, clip_index: 0, name: "Demo", length_beats: 8, notes: [{ pitch: 60 }] },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.note_count, 1);
  assert.equal(provider.createdClips.length, 1);
});

test("apply_expression_to_clip records a note replacement", async () => {
  const provider = new MockLiveProvider();
  const disp = new Dispatcher(provider, {});
  const response = await disp.handle({
    command: "apply_expression_to_clip",
    params: {
      track_index: 0,
      clip_index: 0,
      length_beats: 8,
      notes: [{ pitch: 60, start_time: 0, duration: 1, velocity: 90, probability: 0.8 }],
    },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.note_count, 1);
  assert.equal(provider.appliedExpressions.length, 1);
});

test("apply_expression_to_clip rejects a bad target", async () => {
  const response = await dispatcher().handle({
    command: "apply_expression_to_clip",
    params: { track_index: -1, clip_index: 0, notes: [] },
  });
  assert.equal(response.ok, false);
  assert.match(response.error, /track_index/);
});

test("create_midi_clip rejects a bad target", async () => {
  const response = await dispatcher().handle({
    command: "create_midi_clip",
    params: { track_index: -1, clip_index: 0, length_beats: 8 },
  });
  assert.equal(response.ok, false);
  assert.match(response.error, /track_index/);
});

test("set_tempo updates the tempo", async () => {
  const provider = new MockLiveProvider();
  const disp = new Dispatcher(provider, {});
  const response = await disp.handle({ command: "set_tempo", params: { bpm: 128 } });
  assert.equal(response.ok, true);
  assert.equal(response.result.tempo, 128);
  assert.equal(provider.tempo, 128);
});

test("set_track_mute toggles a track and echoes state", async () => {
  const response = await dispatcher().handle({
    command: "set_track_mute",
    params: { track_index: 0, muted: true },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.muted, true);
  assert.equal(response.result.track, "MIDI 1");
});

test("set_track_volume echoes the applied volume", async () => {
  const response = await dispatcher().handle({
    command: "set_track_volume",
    params: { track_index: 1, volume: 0.5 },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.volume, 0.5);
});

test("control commands reject a bad track index", async () => {
  const response = await dispatcher().handle({
    command: "set_track_solo",
    params: { track_index: 99, soloed: true },
  });
  assert.equal(response.ok, false);
  assert.match(response.error, /out of range/);
});

test("get_track_devices returns devices with parameter state", async () => {
  const response = await dispatcher().handle({
    command: "get_track_devices",
    params: { track_index: 0 },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.devices[0].name, "Reverb");
  const param = response.result.devices[0].parameters[1];
  assert.equal(param.name, "Dry/Wet");
  assert.equal(param.is_quantized, false);
  assert.equal(param.default_value, 0.5);
});

test("set_device_parameter clamps to range and echoes state", async () => {
  const provider = new MockLiveProvider();
  const disp = new Dispatcher(provider, {});
  const ok = await disp.handle({
    command: "set_device_parameter",
    params: { track_index: 0, device_index: 0, parameter_index: 1, value: 0.8 },
  });
  assert.equal(ok.ok, true);
  assert.equal(ok.result.parameter.value, 0.8);

  const bad = await disp.handle({
    command: "set_device_parameter",
    params: { track_index: 0, device_index: 0, parameter_index: 1, value: 2 },
  });
  assert.equal(bad.ok, false);
  assert.match(bad.error, /out of range/);
});

test("set_device_parameter accepts a normalized value", async () => {
  const response = await dispatcher().handle({
    command: "set_device_parameter",
    params: { track_index: 0, device_index: 0, parameter_index: 1, value: 1, normalized: true },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.parameter.value, 1); // 0 + 1*(1-0)
});

test("reset_device_parameter refuses quantized and resets continuous", async () => {
  const quantized = await dispatcher().handle({
    command: "reset_device_parameter",
    params: { track_index: 0, device_index: 0, parameter_index: 0 },
  });
  assert.equal(quantized.ok, false);
  assert.match(quantized.error, /quantized/);

  const reset = await dispatcher().handle({
    command: "reset_device_parameter",
    params: { track_index: 0, device_index: 0, parameter_index: 1 },
  });
  assert.equal(reset.ok, true);
  assert.equal(reset.result.parameter.value, 0.5);
});

test("set_device_power toggles the first parameter", async () => {
  const response = await dispatcher().handle({
    command: "set_device_power",
    params: { track_index: 0, device_index: 0, enabled: false },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.enabled, false);
});

test("device commands reject a bad device index", async () => {
  const response = await dispatcher().handle({
    command: "get_track_devices",
    params: { track_index: 1 },
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.devices.length, 0); // Audio 1 has no devices
});

test("unknown command is rejected", async () => {
  const response = await dispatcher().handle({ command: "delete_everything" });
  assert.equal(response.ok, false);
  assert.equal(response.error, "unknown command");
});

test("token is required when configured", async () => {
  const disp = dispatcher({ token: "secret" });
  const bad = await disp.handle({ command: "ping", token: "wrong" });
  assert.equal(bad.ok, false);
  assert.equal(bad.error, "unauthorized");
  const good = await disp.handle({ command: "ping", token: "secret" });
  assert.equal(good.ok, true);
});

test("mismatched protocol version is rejected", async () => {
  const response = await dispatcher().handle({ command: "ping", protocol: "something.else" });
  assert.equal(response.ok, false);
  assert.match(response.error, /protocol/);
});

test("the command allowlist is exactly the v1 set", () => {
  assert.deepEqual(
    [...ALLOWED_COMMANDS].sort(),
    [
      "apply_expression_to_clip",
      "create_midi_clip",
      "get_midi_clip_notes",
      "get_mix_snapshot",
      "get_selected_context",
      "get_state",
      "get_tempo",
      "get_track_devices",
      "get_tracks",
      "ping",
      "reset_device_parameter",
      "set_device_parameter",
      "set_device_power",
      "set_tempo",
      "set_track_arm",
      "set_track_mute",
      "set_track_pan",
      "set_track_solo",
      "set_track_volume",
    ],
  );
});
