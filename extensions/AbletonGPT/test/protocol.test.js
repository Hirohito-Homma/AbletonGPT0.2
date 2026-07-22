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
      "get_selected_context",
      "get_tempo",
      "get_tracks",
      "ping",
    ],
  );
});
