// Dub delay automation for the MW10-centred KIHACHI layout (target spec v2.0, section 3D):
// step-envelope curves for a track's dub-delay send (the "throw") and for the
// return-path filter cutoff (300 Hz .. 4 kHz band), generated in TypeScript and
// written onto a Session clip of the target track.
//
// Where each part runs, and why -- this follows the architecture the project
// already verified, not the shape the spec prompt assumed:
//
// - Generation and target resolution live here, on the TypeScript side. The
//   filter device/parameter is resolved through the Extensions SDK provider
//   (SdkLiveProvider.getTrackDevices), which is the SDK surface that exists.
// - The write itself CANNOT go through @ableton-extensions/sdk: the SDK
//   1.0.0-beta.0 type definitions expose no clip-automation API at all, so
//   set_clip_send_envelope / set_clip_parameter_envelope do not port to the
//   Extensions backend (see docs/EXTENSIONS_SDK.md, audited against the SDK's
//   own index.d.mts). Both envelope kinds therefore go through the Remote
//   Script's single writer, the bridge command `set_clip_envelope`, reached
//   here via BridgeClient -- the same newline-JSON contract bridge.py speaks.
// - Clip envelopes are a Session-clip feature. Live exposes no API for writing
//   Arrangement automation lanes, so applying to an Arrangement clip is
//   refused by the writer; write in Session, then copy the clip across with
//   copy_session_clip_to_arrangement if the Arrangement is the destination.
//
// Plan/apply split (repo invariant, and KIHACHI's Gateway rule): the plan*
// functions are pure and touch nothing. applyDubDelayAutomation refuses to run
// without an explicit approval flag, writes the two envelopes sequentially
// (one writer, one Live main thread), and treats the writer's per-step
// readback (`matches`) as the only proof the write landed -- a mismatch is an
// error, never a verified result.

import { createConnection, type Socket } from "node:net";

// ---------------------------------------------------------------------------
// Wire shapes (identical to server.py's set_clip_send_envelope /
// set_clip_parameter_envelope and jobs/executors.py: {start, length, value}
// in the clip's own beat time).
// ---------------------------------------------------------------------------

export interface EnvelopeStep {
  start: number;
  length: number;
  value: number;
}

export const MAX_ENVELOPE_STEPS = 512;

// MW10 target spec v2.0 section 3D: the dub delay return loop is filtered to
// 300 Hz .. 4 kHz. The sweep generator defaults to exactly that band.
export const DUB_FILTER_LOW_HZ = 300;
export const DUB_FILTER_HIGH_HZ = 4000;

function assertFinite(value: number, label: string): void {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
}

function assertNonNegativeIndex(value: number, label: string): void {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
}

// The same checks server.py performs before anything reaches the bridge, kept
// word-for-word so a bad curve fails identically on either side.
export function assertValidSteps(
  steps: EnvelopeStep[],
  range?: { min: number; max: number },
): void {
  if (!Array.isArray(steps) || steps.length === 0) {
    throw new Error("steps must be a non-empty list");
  }
  if (steps.length > MAX_ENVELOPE_STEPS) {
    throw new Error(`steps must contain at most ${MAX_ENVELOPE_STEPS} entries`);
  }
  for (const step of steps) {
    assertFinite(step.start, "step start");
    assertFinite(step.length, "step length");
    assertFinite(step.value, "step value");
    if (step.start < 0) {
      throw new Error("step start must be non-negative");
    }
    if (step.length <= 0) {
      throw new Error("step length must be positive");
    }
    if (range && (step.value < range.min || step.value > range.max)) {
      throw new Error("step value out of range for this parameter");
    }
  }
}

// ---------------------------------------------------------------------------
// Curve generation (pure, deterministic, no Live access)
// ---------------------------------------------------------------------------

export interface DubThrowOptions {
  /** Clip length in beats; the curve covers exactly this span. */
  clipLengthBeats: number;
  /** Beat positions (clip time) where each delay throw opens. */
  throwBeats: number[];
  /** How long each throw stays open, in beats. Default 1. */
  throwLengthBeats?: number;
  /** Send level while a throw is open, 0..1. Default 0.85. */
  throwLevel?: number;
  /** Send level everywhere else, 0..1. Default 0. */
  baseline?: number;
}

// A dub throw is a step curve: the send sits at the baseline and jumps open
// for the throw windows. Adjacent steps with equal values are merged, so the
// result is the minimal full-coverage step list for the clip.
export function buildDubThrowSendSteps(options: DubThrowOptions): EnvelopeStep[] {
  const clipLength = options.clipLengthBeats;
  const throwLength = options.throwLengthBeats ?? 1;
  const throwLevel = options.throwLevel ?? 0.85;
  const baseline = options.baseline ?? 0;

  assertFinite(clipLength, "clipLengthBeats");
  if (clipLength <= 0) {
    throw new Error("clipLengthBeats must be positive");
  }
  assertFinite(throwLength, "throwLengthBeats");
  if (throwLength <= 0) {
    throw new Error("throwLengthBeats must be positive");
  }
  for (const [label, value] of [["throwLevel", throwLevel], ["baseline", baseline]] as const) {
    assertFinite(value, label);
    if (value < 0 || value > 1) {
      throw new Error("a send value must be between 0.0 and 1.0");
    }
  }

  const windows = options.throwBeats
    .map((beat) => {
      assertFinite(beat, "throw beat");
      if (beat < 0 || beat >= clipLength) {
        throw new Error("throw beat is outside the clip");
      }
      return { start: beat, end: Math.min(beat + throwLength, clipLength) };
    })
    .sort((a, b) => a.start - b.start);
  for (let i = 1; i < windows.length; i += 1) {
    const prev = windows[i - 1];
    const next = windows[i];
    if (prev && next && next.start < prev.end) {
      throw new Error("throw windows overlap");
    }
  }

  const steps: EnvelopeStep[] = [];
  const push = (start: number, end: number, value: number): void => {
    if (end <= start) {
      return;
    }
    const last = steps[steps.length - 1];
    if (last && last.value === value && Math.abs(last.start + last.length - start) < 1e-9) {
      last.length = end - last.start;
      return;
    }
    steps.push({ start, length: end - start, value });
  };

  let cursor = 0;
  for (const window of windows) {
    push(cursor, window.start, baseline);
    push(window.start, window.end, throwLevel);
    cursor = window.end;
  }
  push(cursor, clipLength, baseline);

  assertValidSteps(steps, { min: 0, max: 1 });
  return steps;
}

export interface FilterSweepOptions {
  /** Clip length in beats; the curve covers exactly this span. */
  clipLengthBeats: number;
  /** Resolution of the sweep, in beats per step. Default 1. */
  stepBeats?: number;
  /** Cutoff at the clip start, in Hz. Default 300 (MW10 spec band low). */
  fromHz?: number;
  /** Cutoff at the clip end, in Hz. Default 4000 (MW10 spec band high). */
  toHz?: number;
  /**
   * "exponential" interpolates on a log scale, which is how a frequency sweep
   * is heard; "linear" interpolates in raw Hz. Default "exponential".
   */
  curve?: "exponential" | "linear";
  /**
   * The target parameter's own range, when known (resolve it first via
   * getTrackDevices). Values are written in the parameter's own units -- for
   * a filter frequency parameter that is Hz -- and every generated value is
   * checked against this range before anything is planned.
   */
  parameterRange?: { min: number; max: number };
}

// Stepped approximation of a cutoff sweep: one step per stepBeats, valued at
// the step's start. The writer's insert_step holds each value for the step's
// length, so a 1-beat resolution reads as a staircase sweep in Live.
export function buildFilterSweepSteps(options: FilterSweepOptions): EnvelopeStep[] {
  const clipLength = options.clipLengthBeats;
  const stepBeats = options.stepBeats ?? 1;
  const fromHz = options.fromHz ?? DUB_FILTER_LOW_HZ;
  const toHz = options.toHz ?? DUB_FILTER_HIGH_HZ;
  const curve = options.curve ?? "exponential";

  assertFinite(clipLength, "clipLengthBeats");
  if (clipLength <= 0) {
    throw new Error("clipLengthBeats must be positive");
  }
  assertFinite(stepBeats, "stepBeats");
  if (stepBeats <= 0) {
    throw new Error("stepBeats must be positive");
  }
  assertFinite(fromHz, "fromHz");
  assertFinite(toHz, "toHz");
  if (fromHz <= 0 || toHz <= 0) {
    throw new Error("cutoff values must be positive (Hz)");
  }

  const steps: EnvelopeStep[] = [];
  for (let start = 0; start < clipLength; start += stepBeats) {
    const length = Math.min(stepBeats, clipLength - start);
    const t = clipLength === length && start === 0 ? 0 : start / clipLength;
    const value =
      curve === "exponential"
        ? fromHz * Math.pow(toHz / fromHz, t)
        : fromHz + (toHz - fromHz) * t;
    steps.push({ start, length, value });
  }

  assertValidSteps(steps, options.parameterRange);
  return steps;
}

export interface FilterDropCutOptions {
  /** Clip length in beats (whole beats, at least 2); the curve covers it exactly. */
  clipLengthBeats: number;
  /** Cutoff where the build-up starts, in Hz. Default 1000. */
  openFromHz?: number;
  /** Cutoff the build-up opens to, held until the cut, in Hz. Default 8000. */
  openToHz?: number;
  /** Cutoff the drop slams shut to, in Hz. Default 300 (MW10 spec band low). */
  closedHz?: number;
  /** Width of the closing cut in beats. Default 0.02 (~11 ms at 110 BPM). */
  cutBeats?: number;
  /** "exponential" (default) interpolates on a log scale, how a sweep is heard. */
  curve?: "exponential" | "linear";
  /** The target parameter's own range, when known (values here are Hz). */
  parameterRange?: { min: number; max: number };
}

// The filter counterpart of the swell's instant cut, from KIHACHI's draft:
// the cutoff opens across the build-up (1000 -> 8000 Hz), holds at the peak
// until the drop, then slams shut to a muffled 300 Hz in the last cutBeats
// of the clip. Everything stays inside the clip, like the swell's cut.
export function buildFilterDropCutSteps(options: FilterDropCutOptions): EnvelopeStep[] {
  const beats = options.clipLengthBeats;
  const openFromHz = options.openFromHz ?? 1000;
  const openToHz = options.openToHz ?? 8000;
  const closedHz = options.closedHz ?? DUB_FILTER_LOW_HZ;
  const cutBeats = options.cutBeats ?? 0.02;
  const curve = options.curve ?? "exponential";

  if (!Number.isInteger(beats) || beats < 2) {
    throw new Error("clipLengthBeats must be a whole number of beats of at least 2");
  }
  for (const [label, hz] of [
    ["openFromHz", openFromHz],
    ["openToHz", openToHz],
    ["closedHz", closedHz],
  ] as const) {
    assertFinite(hz, label);
    if (hz <= 0) {
      throw new Error(`${label} must be positive (Hz)`);
    }
  }
  if (!Number.isFinite(cutBeats) || cutBeats <= 0 || cutBeats >= 1) {
    throw new Error("cutBeats must be greater than 0 and less than 1 (beats)");
  }
  const interpolate = (t: number): number =>
    curve === "exponential"
      ? openFromHz * Math.pow(openToHz / openFromHz, t)
      : openFromHz + (openToHz - openFromHz) * t;

  const steps: EnvelopeStep[] = [];
  for (let beat = 0; beat < beats - 1; beat += 1) {
    steps.push({ start: beat, length: 1, value: interpolate(beat / (beats - 1)) });
  }
  steps.push({ start: beats - 1, length: 1 - cutBeats, value: openToHz });
  steps.push({ start: beats - cutBeats, length: cutBeats, value: closedHz });
  assertValidSteps(steps, options.parameterRange);
  return steps;
}

export interface ReverbSpikeOptions {
  /** Length of the clip that starts at the drop, in beats. */
  clipLengthBeats: number;
  /** Send level held outside the spike. Default 0.1. */
  baseline?: number;
  /** Send level at the spike. Default 1.0. */
  spikeValue?: number;
  /**
   * Width of the spike in beats, from the clip's first beat (the drop
   * moment). Default 0.02 (~11 ms at 110 BPM): a blast of signal into the
   * return, whose tail then rings on its own -- a reverb throw. Widen it
   * (e.g. 1.0) to feed the tail with a full beat of source.
   */
  spikeBeats?: number;
}

// A reverb send spike at the drop, from KIHACHI's draft: the send sits at
// the baseline, spikes to full for the first spikeBeats of the drop clip,
// then returns to the baseline while the reverb tail decays. Send values
// are 0..1 by definition, and the steps are validated against that range.
export function buildReverbSpikeSteps(options: ReverbSpikeOptions): EnvelopeStep[] {
  const beats = options.clipLengthBeats;
  const baseline = options.baseline ?? 0.1;
  const spikeValue = options.spikeValue ?? 1.0;
  const spikeBeats = options.spikeBeats ?? 0.02;
  if (!Number.isFinite(beats) || beats <= 0) {
    throw new Error("clipLengthBeats must be positive");
  }
  if (!Number.isFinite(spikeBeats) || spikeBeats <= 0 || spikeBeats >= beats) {
    throw new Error("spikeBeats must be greater than 0 and shorter than the clip");
  }
  const steps: EnvelopeStep[] = [
    { start: 0, length: spikeBeats, value: spikeValue },
    { start: spikeBeats, length: beats - spikeBeats, value: baseline },
  ];
  assertValidSteps(steps, { min: 0, max: 1 });
  return steps;
}

// ---------------------------------------------------------------------------
// Target resolution through the SDK-backed provider (read-only)
// ---------------------------------------------------------------------------

// The subset of SdkLiveProvider this module needs. SdkLiveProvider satisfies
// it structurally; the mock provider in src/liveProvider.js has the same
// method shape. Kept as an interface so the generators stay testable without
// a running Live.
export interface TrackDevicesReader {
  getTrackDevices(params: { track_index: number }): Promise<{
    track_index: number;
    track: string;
    devices: Array<{
      index: number;
      name: string;
      parameters: Array<{
        index: number;
        name: string;
        value: number;
        min: number;
        max: number;
      }>;
    }>;
  }>;
}

export interface ResolvedParameter {
  deviceIndex: number;
  deviceName: string;
  parameterIndex: number;
  parameterName: string;
  min: number;
  max: number;
}

// Find the filter cutoff parameter on a track by name, the way a human would
// in Live: a device whose name mentions the filter (default "Filter", e.g.
// Auto Filter / EQ Eight is matched via deviceNameIncludes) and its frequency
// parameter. Indices are never guessed -- get_track_devices is the source of
// truth, and its min/max are what the sweep is validated against.
export async function resolveFilterParameter(
  reader: TrackDevicesReader,
  trackIndex: number,
  options?: { deviceNameIncludes?: string; parameterNameIncludes?: string },
): Promise<ResolvedParameter> {
  assertNonNegativeIndex(trackIndex, "track_index");
  const deviceNeedle = (options?.deviceNameIncludes ?? "Filter").toLowerCase();
  const parameterNeedle = (options?.parameterNameIncludes ?? "Frequency").toLowerCase();

  const state = await reader.getTrackDevices({ track_index: trackIndex });
  const device = state.devices.find((candidate) =>
    candidate.name.toLowerCase().includes(deviceNeedle),
  );
  if (!device) {
    throw new Error(
      `no device matching "${options?.deviceNameIncludes ?? "Filter"}" on track ${trackIndex}`,
    );
  }
  const parameter = device.parameters.find((candidate) =>
    candidate.name.toLowerCase().includes(parameterNeedle),
  );
  if (!parameter) {
    throw new Error(
      `no parameter matching "${options?.parameterNameIncludes ?? "Frequency"}" on device "${device.name}"`,
    );
  }
  return {
    deviceIndex: device.index,
    deviceName: device.name,
    parameterIndex: parameter.index,
    parameterName: parameter.name,
    min: parameter.min,
    max: parameter.max,
  };
}

// ---------------------------------------------------------------------------
// Plan (pure) and apply (bridge write, approval-gated, readback-verified)
// ---------------------------------------------------------------------------

export interface DubDelayAutomationRequest {
  trackIndex: number;
  clipIndex: number;
  /** Return-track send to automate: 0 = A, 1 = B, ... (per server.py). */
  sendIndex: number;
  filter: ResolvedParameter;
  sendSteps: EnvelopeStep[];
  filterSteps: EnvelopeStep[];
}

export interface DubDelayAutomationPlan {
  kind: "dub_delay_automation_plan";
  status: "planned_not_applied";
  target: {
    track_index: number;
    clip_index: number;
    send_index: number;
    device_index: number;
    parameter_index: number;
  };
  commands: Array<{ command: "set_clip_envelope"; params: Record<string, unknown> }>;
}

// Build the full plan -- both bridge payloads -- without touching Live.
// Throws on any invalid step, exactly as server.py would, so a plan that
// builds here is a plan the writer will accept structurally.
export function planDubDelayAutomation(
  request: DubDelayAutomationRequest,
): DubDelayAutomationPlan {
  assertNonNegativeIndex(request.trackIndex, "track_index");
  assertNonNegativeIndex(request.clipIndex, "clip_index");
  assertNonNegativeIndex(request.sendIndex, "send_index");
  assertNonNegativeIndex(request.filter.deviceIndex, "device_index");
  assertNonNegativeIndex(request.filter.parameterIndex, "parameter_index");
  assertValidSteps(request.sendSteps, { min: 0, max: 1 });
  assertValidSteps(request.filterSteps, {
    min: request.filter.min,
    max: request.filter.max,
  });

  const target = {
    track_index: request.trackIndex,
    clip_index: request.clipIndex,
    send_index: request.sendIndex,
    device_index: request.filter.deviceIndex,
    parameter_index: request.filter.parameterIndex,
  };
  return {
    kind: "dub_delay_automation_plan",
    status: "planned_not_applied",
    target,
    commands: [
      {
        command: "set_clip_envelope",
        params: {
          track_index: target.track_index,
          clip_index: target.clip_index,
          send_index: target.send_index,
          steps: request.sendSteps,
        },
      },
      {
        command: "set_clip_envelope",
        params: {
          track_index: target.track_index,
          clip_index: target.clip_index,
          device_index: target.device_index,
          parameter_index: target.parameter_index,
          steps: request.filterSteps,
        },
      },
    ],
  };
}

// The bridge contract (bridge.py's AbletonBridge.call): one newline-delimited
// JSON object {command, params, token} out, one {ok, result|error} line back.
export interface BridgeCall {
  call(command: string, params: Record<string, unknown>): Promise<unknown>;
}

export interface BridgeClientOptions {
  host?: string;
  /** Remote Script bridge port (ABLETONGPT_PORT). Default 9877. */
  port?: number;
  token?: string;
  timeoutMs?: number;
}

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

// TypeScript counterpart of bridge.py: loopback-only, one request per
// connection, errors surface as thrown Errors carrying Live's own message.
export class BridgeClient implements BridgeCall {
  private readonly host: string;
  private readonly port: number;
  private readonly token: string;
  private readonly timeoutMs: number;

  constructor(options: BridgeClientOptions = {}) {
    this.host = options.host ?? "127.0.0.1";
    if (!LOOPBACK_HOSTS.has(this.host)) {
      throw new Error("bridge host must be loopback (bridge.py enforces localhost-only)");
    }
    this.port = options.port ?? 9877;
    this.token = options.token ?? "";
    this.timeoutMs = options.timeoutMs ?? 10_000;
    if (this.timeoutMs <= 0) {
      throw new Error("bridge request timeout must be positive");
    }
  }

  async call(command: string, params: Record<string, unknown>): Promise<unknown> {
    const payload = `${JSON.stringify({ command, params, token: this.token })}\n`;
    const line = await this.exchange(payload);
    let decoded: { ok?: boolean; result?: unknown; error?: string };
    try {
      decoded = JSON.parse(line) as { ok?: boolean; result?: unknown; error?: string };
    } catch {
      throw new Error("Ableton Live returned an unreadable response");
    }
    if (!decoded.ok) {
      throw new Error(decoded.error ?? "Ableton command failed");
    }
    return decoded.result ?? null;
  }

  private exchange(payload: string): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      let socket: Socket;
      try {
        socket = createConnection({ host: this.host, port: this.port });
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      const chunks: Buffer[] = [];
      let settled = false;
      const fail = (error: Error): void => {
        if (!settled) {
          settled = true;
          socket.destroy();
          reject(error);
        }
      };
      socket.setTimeout(this.timeoutMs, () => {
        fail(new Error(`bridge request timed out after ${this.timeoutMs} ms`));
      });
      socket.on("error", (error) => {
        fail(
          new Error(
            "cannot connect to Ableton Live; start Live and select the " +
              `AbletonGPT control surface (${error.message})`,
          ),
        );
      });
      socket.on("connect", () => {
        socket.write(payload, "utf8");
      });
      socket.on("data", (chunk: Buffer) => {
        chunks.push(chunk);
        const text = Buffer.concat(chunks).toString("utf8");
        const newline = text.indexOf("\n");
        if (newline >= 0 && !settled) {
          settled = true;
          socket.end();
          resolve(text.slice(0, newline));
        }
      });
      socket.on("end", () => {
        if (!settled) {
          settled = true;
          resolve(Buffer.concat(chunks).toString("utf8").trim());
        }
      });
    });
  }
}

export interface EnvelopeWriteResult {
  steps?: Array<{ matches?: boolean }>;
}

// The writer reports value_at_time sampled mid-step for every step it wrote.
// All of them must match; anything less is reported as unverified, never as
// success (the Gateway read-back rule).
export function assertReadbackVerified(result: unknown, label: string): EnvelopeWriteResult {
  const write = (result ?? {}) as EnvelopeWriteResult;
  if (!Array.isArray(write.steps) || write.steps.length === 0) {
    throw new Error(`${label}: writer returned no readback; result is unverified`);
  }
  const mismatches = write.steps.filter((step) => step.matches !== true).length;
  if (mismatches > 0) {
    throw new Error(
      `${label}: readback mismatch on ${mismatches} of ${write.steps.length} step(s); ` +
        "the envelope in Live does not match the plan",
    );
  }
  return write;
}

export interface ApplyDubDelayOptions {
  /**
   * Explicit human approval of THIS plan, in the caller's hand. There is no
   * default: without it the function refuses before any socket is opened.
   */
  approved: boolean;
}

export interface ApplyDubDelayResult {
  target: DubDelayAutomationPlan["target"];
  send: EnvelopeWriteResult;
  filter: EnvelopeWriteResult;
  verified: true;
}

// Apply a reviewed plan. Sequential on purpose: both commands share the one
// Remote Script writer on Live's main thread, and if the send write fails the
// filter write is never attempted.
export async function applyDubDelayAutomation(
  bridge: BridgeCall,
  plan: DubDelayAutomationPlan,
  options: ApplyDubDelayOptions,
): Promise<ApplyDubDelayResult> {
  if (options.approved !== true) {
    throw new Error(
      "refusing to write to Live without explicit approval of this plan " +
        "(plan/apply split: review the plan, then re-call with approved: true)",
    );
  }
  if (plan.kind !== "dub_delay_automation_plan" || plan.commands.length !== 2) {
    throw new Error("not a dub delay automation plan");
  }
  const [sendCommand, filterCommand] = plan.commands;
  if (!sendCommand || !filterCommand) {
    throw new Error("plan is missing an envelope command");
  }

  const sendResult = await bridge.call(sendCommand.command, sendCommand.params);
  const send = assertReadbackVerified(sendResult, "send envelope");
  const filterResult = await bridge.call(filterCommand.command, filterCommand.params);
  const filter = assertReadbackVerified(filterResult, "filter envelope");

  return { target: plan.target, send, filter, verified: true };
}
