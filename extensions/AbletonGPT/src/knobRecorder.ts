// Knob performance capture -> step envelope.
//
// The draft this is based on asked an extension to listen for APC40 MIDI
// CC and append points to an envelope at the playhead in real time. Two
// parts of that cannot exist here, for the same reasons as the pad
// trigger (liveDropTrigger.ts): the extension host exposes no MIDI input
// (the APC40 belongs to Live's control-surface layer), and envelopes are
// Session-clip step lists, not a real-time point stream on a timeline.
//
// One honest note first: for the literal goal -- "record my knob moves" --
// Live itself already does it. MIDI-map the knob to the parameter and
// record, and Live writes the automation natively. Use that.
//
// What code can add, and what this file is: capture a performed ride from
// ANY sample source (a future MIDI forwarder, a UI fader, a test feed),
// thin it into a clean quantized step envelope -- grid-snapped, jitter
// removed, in the target parameter's own units -- and write it onto a
// Session clip through the one verified writer, under the usual
// plan/apply split. A captured take becomes an editable curve instead of
// a thousand raw points.

import {
  assertReadbackVerified,
  assertValidSteps,
  type BridgeCall,
  type EnvelopeStep,
  type EnvelopeWriteResult,
  type TrackDevicesReader,
} from "./dubDelayAutomation.js";

const LOG = "[APC40 Live Recording]";

export interface KnobSample {
  /** Song position of the sample, in beats. */
  beat: number;
  /** Normalized knob position, 0.0 - 1.0 (e.g. a CC value / 127). */
  value: number;
}

export interface ThinOptions {
  /** Beat where the target clip starts; samples are made clip-relative. */
  clipStartBeat: number;
  /** Clip length in beats; samples outside the clip are dropped. */
  beats: number;
  /** Finest step resolution in beats. Default 0.25 (~136 ms at 110 BPM). */
  minStepBeats?: number;
  /** Value changes smaller than this (normalized) start no new step. Default 0.01. */
  epsilon?: number;
  /** The target parameter's real range; values are mapped into it. */
  range: { min: number; max: number };
}

// Pure conversion: a performed ride -> held steps. A new step starts when
// the grid advances past minStepBeats AND the value has moved by more
// than epsilon, or when the grid advances far (4x minStepBeats) regardless
// -- so a long slow drag still tracks, while static jitter does not
// fragment the envelope. The first in-clip sample opens the envelope;
// before it, the clip keeps whatever the parameter already does.
export function thinSamplesToSteps(samples: KnobSample[], options: ThinOptions): EnvelopeStep[] {
  const minStepBeats = options.minStepBeats ?? 0.25;
  const epsilon = options.epsilon ?? 0.01;
  if (!Number.isFinite(minStepBeats) || minStepBeats <= 0) {
    throw new Error("minStepBeats must be positive");
  }
  if (!Number.isFinite(epsilon) || epsilon < 0) {
    throw new Error("epsilon must be >= 0");
  }
  const toUnits = (normalized: number): number =>
    options.range.min + normalized * (options.range.max - options.range.min);

  const inClip = samples
    .filter(
      (sample) =>
        Number.isFinite(sample.beat) &&
        Number.isFinite(sample.value) &&
        sample.beat >= options.clipStartBeat &&
        sample.beat < options.clipStartBeat + options.beats,
    )
    .map((sample) => ({
      beat: sample.beat - options.clipStartBeat,
      value: Math.min(1, Math.max(0, sample.value)),
    }))
    .sort((a, b) => a.beat - b.beat);
  if (inClip.length === 0) {
    throw new Error("no samples fell inside the clip; nothing to record");
  }

  const raw: Array<{ start: number; value: number }> = [];
  let current = inClip[0] as { beat: number; value: number };
  raw.push({ start: current.beat, value: current.value });
  for (const sample of inClip.slice(1)) {
    const elapsed = sample.beat - current.beat;
    const moved = Math.abs(sample.value - current.value) > epsilon;
    if ((elapsed >= minStepBeats && moved) || elapsed >= minStepBeats * 4) {
      raw.push({ start: sample.beat, value: sample.value });
      current = sample;
    }
  }

  const steps: EnvelopeStep[] = raw.map((point, index) => {
    const next = raw[index + 1];
    const end = next ? next.start : options.beats;
    return { start: point.start, length: end - point.start, value: toUnits(point.value) };
  });
  assertValidSteps(steps, options.range);
  return steps;
}

// ---------------------------------------------------------------------------
// Recorder: resolve the target once, collect samples, finish into a plan,
// apply under approval.
// ---------------------------------------------------------------------------

export type KnobSampleSource = (emit: (sample: KnobSample) => void) => { close(): void };

export interface KnobRecorderOptions {
  reader: TrackDevicesReader & {
    getTracks(): Promise<{
      tracks: Array<{ index: number; name: string; has_midi_input: boolean }>;
    }>;
  };
  trackName: string;
  deviceName: string;
  paramName: string;
}

export interface KnobRecordingPlan {
  trackIndex: number;
  deviceIndex: number;
  parameterIndex: number;
  parameterName: string;
  steps: EnvelopeStep[];
  sampleCount: number;
}

export interface KnobRecorder {
  /** Feed one performed sample directly. */
  push(sample: KnobSample): void;
  /** Attach an external sample source; returns a detach function. */
  attach(source: KnobSampleSource): () => void;
  /** Convert everything captured so far into a step plan (writes nothing). */
  finish(options: { clipStartBeat: number; beats: number; minStepBeats?: number; epsilon?: number }): KnobRecordingPlan;
  /** Write a finished plan to a Session clip, read-back verified. */
  apply(
    plan: KnobRecordingPlan,
    bridge: BridgeCall,
    options: { clipIndex: number; approved?: boolean },
  ): Promise<EnvelopeWriteResult>;
}

export async function createKnobRecorder(options: KnobRecorderOptions): Promise<KnobRecorder> {
  const { tracks } = await options.reader.getTracks();
  const track = tracks.find((candidate) => candidate.name === options.trackName);
  if (!track) {
    const names = tracks.map((candidate) => candidate.name).join(", ");
    throw new Error(`track "${options.trackName}" not found; Live reports: ${names}`);
  }
  const deviceState = await options.reader.getTrackDevices({ track_index: track.index });
  const device = deviceState.devices.find((candidate) => candidate.name === options.deviceName);
  if (!device) {
    const names = deviceState.devices.map((candidate) => candidate.name).join(", ");
    throw new Error(
      `device "${options.deviceName}" not found on "${options.trackName}"; devices present: ${names}`,
    );
  }
  const parameter = device.parameters.find((candidate) => candidate.name === options.paramName);
  if (!parameter) {
    const names = device.parameters.map((candidate) => candidate.name).join(", ");
    throw new Error(
      `"${options.deviceName}" has no parameter named "${options.paramName}"; parameters: ${names}`,
    );
  }
  console.log(
    `${LOG} recording target resolved: "${options.trackName}" -> "${device.name}" / ` +
      `"${parameter.name}" (range ${parameter.min}..${parameter.max})`,
  );

  const samples: KnobSample[] = [];
  return {
    push(sample: KnobSample): void {
      samples.push(sample);
    },
    attach(source: KnobSampleSource): () => void {
      const handle = source((sample) => samples.push(sample));
      return () => handle.close();
    },
    finish(finishOptions): KnobRecordingPlan {
      const steps = thinSamplesToSteps(samples, {
        clipStartBeat: finishOptions.clipStartBeat,
        beats: finishOptions.beats,
        range: { min: parameter.min, max: parameter.max },
        ...(finishOptions.minStepBeats !== undefined
          ? { minStepBeats: finishOptions.minStepBeats }
          : {}),
        ...(finishOptions.epsilon !== undefined ? { epsilon: finishOptions.epsilon } : {}),
      });
      console.log(
        `${LOG} captured ${samples.length} samples -> ${steps.length} steps on "${parameter.name}"`,
      );
      return {
        trackIndex: track.index,
        deviceIndex: device.index,
        parameterIndex: parameter.index,
        parameterName: parameter.name,
        steps,
        sampleCount: samples.length,
      };
    },
    async apply(plan, bridge, applyOptions): Promise<EnvelopeWriteResult> {
      if (applyOptions.approved !== true) {
        throw new Error("refusing to write a recording without explicit approval");
      }
      const result = await bridge.call("set_clip_envelope", {
        track_index: plan.trackIndex,
        clip_index: applyOptions.clipIndex,
        device_index: plan.deviceIndex,
        parameter_index: plan.parameterIndex,
        steps: plan.steps,
      });
      const verified = assertReadbackVerified(result, "recorded envelope");
      console.log(`${LOG} recorded envelope written to clip ${applyOptions.clipIndex} and verified`);
      return verified;
    },
  };
}
