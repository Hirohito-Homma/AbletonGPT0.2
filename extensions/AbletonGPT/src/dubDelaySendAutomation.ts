// Dub delay send automation: a feedback-style swell and drop for the
// KIHACHI_Dub_Delay_Send track's External Audio Effect, generated in
// TypeScript and written onto a Session clip on that track.
//
// Two facts shape this implementation, both verified against the real tools
// rather than assumed from the request:
//
// 1. @ableton-extensions/sdk (1.0.0-beta.0) has NO automation-envelope API.
//    There is no automationEnvelope.addPoints() -- the SDK's audited type
//    definitions expose no clip envelopes at all (docs/EXTENSIONS_SDK.md).
//    So the SDK side does what it can do -- find the track, the device, and
//    the real parameters with their ranges -- and the envelope write goes
//    through the project's one verified writer, the Remote Script bridge
//    command `set_clip_envelope`, via the BridgeClient in
//    dubDelayAutomation.ts. Envelopes are Session-clip only; no Live API
//    writes Arrangement automation lanes.
//
// 2. The External Audio Effect device has no `Feedback` parameter. In the
//    MW10 layout the feedback lives in the hardware loop itself (the return
//    path through the MW10 channels), not in a Live parameter. What a swell
//    can automate in Live is the device's Dry/Wet: opening it up feeds more
//    signal around the hardware loop, which is how the self-oscillation
//    builds, and dropping it chokes the loop at the drop. This function
//    therefore checks at runtime whether the device exposes a Feedback
//    parameter (and uses it if a future device ever does), and otherwise
//    swells Dry/Wet -- and says so in the log instead of pretending.
//
// Plan/apply split, as everywhere in this project: without an explicit
// approval flag the function returns a plan and writes nothing.

import {
  assertReadbackVerified,
  assertValidSteps,
  buildFilterDropCutSteps,
  buildFilterSweepSteps,
  buildReverbSpikeSteps,
  resolveFilterParameter,
  type BridgeCall,
  type EnvelopeStep,
  type EnvelopeWriteResult,
  type TrackDevicesReader,
} from "./dubDelayAutomation.js";

const LOG = "[Ableton Automation]";

// The read surface this function needs. SdkLiveProvider (which is backed by
// @ableton-extensions/sdk) satisfies both halves structurally.
export interface DubDelayLiveReader extends TrackDevicesReader {
  getTracks(): Promise<{
    tracks: Array<{ index: number; name: string; has_midi_input: boolean }>;
  }>;
}

export interface GenerateDubDelayDeps {
  /** SDK-backed provider (reads only): track / device / parameter lookup. */
  reader: DubDelayLiveReader;
  /** Bridge to the Remote Script writer. Required only when applying. */
  bridge?: BridgeCall;
  /** Session clip slot on the target track that carries the envelopes. */
  clipIndex?: number;
  /**
   * Explicit human approval of the generated plan. Without it the function
   * stops at planned_not_applied and writes nothing (Gateway rule).
   */
  approved?: boolean;
  /** Swell start, as a fraction of the Dry/Wet range. Default 0.3. */
  swellFrom?: number;
  /** Swell peak, as a fraction of the Dry/Wet range. Default 0.85. */
  swellTo?: number;
  /** Level the curve drops to on the final bar, fraction. Default 0.25. */
  dropTo?: number;
  /** Swell shape: "sigmoid" (default, S-curve) or "quadratic" (plain ramp). */
  curve?: SwellCurve;
  /** Drop shape: "bar" (default) holds the final bar low; "instant" cuts at the end. */
  dropMode?: DropMode;
  /** Width of the instant cut in beats. Default 0.02 (~11 ms at 110 BPM). */
  cutBeats?: number;
  /** Also automate a filter device on the same track (see filterMode). */
  includeFilterSweep?: boolean;
  /**
   * "sweep" (default): 300 Hz -> 4 kHz across the section, stays open.
   * "dropCut": opens 1000 -> 8000 Hz across the build, then slams shut to
   * 300 Hz in the final cutBeats -- the swell's instant cut, for the filter.
   */
  filterMode?: "sweep" | "dropCut";
  /** dropCut only: cutoff the build starts from, Hz. Default 1000. */
  filterOpenFromHz?: number;
  /** dropCut only: cutoff the build opens to, Hz. Default 8000. */
  filterOpenToHz?: number;
  /** dropCut only: cutoff after the drop, Hz. Default 300. */
  filterClosedHz?: number;
  /** Also write a reverb send spike that fires at the drop. */
  includeReverbSpike?: boolean;
  /**
   * Which send (index) is the reverb return. Required with
   * includeReverbSpike: which send feeds which return is a fact about the
   * Set, so it is given explicitly, never guessed.
   */
  reverbSendIndex?: number;
  /**
   * Clip that carries the spike -- the clip starting at the drop. Defaults
   * to clipIndex. The spike clip is assumed to span the same barLength.
   */
  spikeClipIndex?: number;
  /** Send level outside the spike. Default 0.1. */
  reverbBaseline?: number;
  /** Send level at the spike. Default 1.0. */
  reverbSpikeValue?: number;
  /** Spike width in beats from the drop. Default 0.02. */
  reverbSpikeBeats?: number;
}

export interface GenerateDubDelayResult {
  status: "planned_not_applied" | "applied_verified";
  track: { index: number; name: string };
  device: { index: number; name: string };
  /** Which parameter the swell was written to, and why. */
  swellParameter: { index: number; name: string; viaFeedbackParameter: boolean };
  beats: number;
  swellSteps: EnvelopeStep[];
  filterSteps: EnvelopeStep[] | null;
  reverbSteps: EnvelopeStep[] | null;
  writes: EnvelopeWriteResult[] | null;
}

interface DeviceParameterShape {
  index: number;
  name: string;
  value: number;
  min: number;
  max: number;
}

function fractionToValue(fraction: number, parameter: DeviceParameterShape): number {
  return parameter.min + fraction * (parameter.max - parameter.min);
}

// Ease-in-out cubic ("S-curve"): lifted from KIHACHI's own draft of this
// feature. Slow lift at the start, a steep climb through the second half,
// and a plateau as it reaches the peak -- so the loop is already singing
// just before the drop instead of arriving at the peak on the drop itself.
export function calculateSigmoidCurve(t: number): number {
  const clamped = Math.min(1, Math.max(0, t));
  if (clamped < 0.5) {
    return 4 * clamped * clamped * clamped;
  }
  const f = -2 * clamped + 2;
  return 1 - (f * f * f) / 2;
}

export type SwellCurve = "sigmoid" | "quadratic";

// How the swell ends. "bar": the final bar sits at dropTo (the original
// shape). "instant": the ramp runs to the very end of the section and the
// level cuts to dropTo in the last `cutBeats` of the clip -- KIHACHI's
// "instant cut" at the drop moment, about 11 ms at 110 BPM for the
// default 0.02 beats, which is how a step envelope cuts anyway.
export type DropMode = "bar" | "instant";

// The swell itself (pure): a ramp sampled once per beat from swellFrom up
// to swellTo, then the drop per DropMode above. Fractions are of the
// parameter's own range, so the same shape lands correctly whether
// Dry/Wet is 0..1 or 0..100. The default shape is the S-curve above;
// "quadratic" keeps the earlier plain exponential ramp.
export function buildSwellSteps(options: {
  beats: number;
  fromFraction: number;
  toFraction: number;
  dropFraction: number;
  parameter: DeviceParameterShape;
  curve?: SwellCurve;
  dropMode?: DropMode;
  cutBeats?: number;
}): EnvelopeStep[] {
  const { beats, parameter } = options;
  for (const [label, fraction] of [
    ["swellFrom", options.fromFraction],
    ["swellTo", options.toFraction],
    ["dropTo", options.dropFraction],
  ] as const) {
    if (!Number.isFinite(fraction) || fraction < 0 || fraction > 1) {
      throw new Error(`${label} must be a fraction between 0.0 and 1.0`);
    }
  }
  if (!Number.isInteger(beats) || beats < 8 || beats % 4 !== 0) {
    throw new Error("barLength must produce a whole number of bars (beats >= 8, divisible by 4)");
  }
  const shape = (t: number): number => {
    const shaped = (options.curve ?? "sigmoid") === "quadratic" ? t * t : calculateSigmoidCurve(t);
    return options.fromFraction + (options.toFraction - options.fromFraction) * shaped;
  };

  if ((options.dropMode ?? "bar") === "instant") {
    const cutBeats = options.cutBeats ?? 0.02;
    if (!Number.isFinite(cutBeats) || cutBeats <= 0 || cutBeats >= 1) {
      throw new Error("cutBeats must be greater than 0 and less than 1 (beats)");
    }
    const steps: EnvelopeStep[] = [];
    for (let beat = 0; beat < beats - 1; beat += 1) {
      const t = beat / (beats - 1);
      steps.push({ start: beat, length: 1, value: fractionToValue(shape(t), parameter) });
    }
    // Peak held until the cut point, then the cut itself as the last step;
    // everything stays inside the clip (no step starts past its end).
    steps.push({
      start: beats - 1,
      length: 1 - cutBeats,
      value: fractionToValue(options.toFraction, parameter),
    });
    steps.push({
      start: beats - cutBeats,
      length: cutBeats,
      value: fractionToValue(options.dropFraction, parameter),
    });
    assertValidSteps(steps, { min: parameter.min, max: parameter.max });
    return steps;
  }

  const rampBeats = beats - 4;
  const steps: EnvelopeStep[] = [];
  for (let beat = 0; beat < rampBeats; beat += 1) {
    const t = rampBeats === 1 ? 1 : beat / (rampBeats - 1);
    steps.push({ start: beat, length: 1, value: fractionToValue(shape(t), parameter) });
  }
  steps.push({
    start: rampBeats,
    length: 4,
    value: fractionToValue(options.dropFraction, parameter),
  });
  assertValidSteps(steps, { min: parameter.min, max: parameter.max });
  return steps;
}

/**
 * Generate (and, with approval, write) the dub delay swell for the track
 * named `trackName` -- in this layout, "KIHACHI_Dub_Delay_Send".
 *
 * `barLength` is the section length in bars (4 or 8 in practice); the
 * envelope times are clip-internal beats of the Session clip at
 * deps.clipIndex, so a section that sits at arrangement beats 32-48 is
 * written to the clip whose own beat 0 is that section's start.
 */
export async function generateDubDelayAutomation(
  trackName: string,
  barLength: number,
  deps: GenerateDubDelayDeps,
): Promise<GenerateDubDelayResult> {
  try {
    if (!trackName) {
      throw new Error("trackName must be a non-empty string");
    }
    if (!Number.isInteger(barLength) || barLength < 2) {
      throw new Error("barLength must be an integer of at least 2 (bars)");
    }
    const beats = barLength * 4;
    const clipIndex = deps.clipIndex ?? 0;

    // -- 1. Find the track and the External Audio Effect (SDK reads) -------
    const { tracks } = await deps.reader.getTracks();
    const track = tracks.find((candidate) => candidate.name === trackName);
    if (!track) {
      const names = tracks.map((candidate) => candidate.name).join(", ");
      throw new Error(`track "${trackName}" not found; Live reports: ${names}`);
    }
    console.log(`${LOG} found track "${track.name}" at index ${track.index}`);

    const deviceState = await deps.reader.getTrackDevices({ track_index: track.index });
    const device = deviceState.devices.find((candidate) =>
      candidate.name.toLowerCase().includes("external audio effect"),
    );
    if (!device) {
      const names = deviceState.devices.map((candidate) => candidate.name).join(", ");
      throw new Error(
        `no External Audio Effect device on "${trackName}"; devices present: ${names}`,
      );
    }
    console.log(`${LOG} found device "${device.name}" at index ${device.index}`);

    // Feedback first, honestly: use it if this device ever exposes it.
    const feedback = device.parameters.find((parameter) =>
      parameter.name.toLowerCase().includes("feedback"),
    );
    const dryWet = device.parameters.find((parameter) =>
      parameter.name.toLowerCase().includes("dry/wet"),
    );
    let swellParameter: DeviceParameterShape;
    let viaFeedbackParameter: boolean;
    if (feedback) {
      swellParameter = feedback;
      viaFeedbackParameter = true;
      console.log(`${LOG} swelling the Feedback parameter "${feedback.name}"`);
    } else if (dryWet) {
      swellParameter = dryWet;
      viaFeedbackParameter = false;
      console.log(
        `${LOG} "${device.name}" exposes no Feedback parameter -- in the MW10 ` +
          `layout the feedback is the hardware loop itself, so the swell opens ` +
          `Dry/Wet ("${dryWet.name}") to feed the loop instead`,
      );
    } else {
      const names = device.parameters.map((parameter) => parameter.name).join(", ");
      throw new Error(
        `"${device.name}" has neither a Feedback nor a Dry/Wet parameter; parameters: ${names}`,
      );
    }

    // -- 2. Generate the curves --------------------------------------------
    const swellSteps = buildSwellSteps({
      beats,
      fromFraction: deps.swellFrom ?? 0.3,
      toFraction: deps.swellTo ?? 0.85,
      dropFraction: deps.dropTo ?? 0.25,
      parameter: swellParameter,
      ...(deps.curve !== undefined ? { curve: deps.curve } : {}),
      ...(deps.dropMode !== undefined ? { dropMode: deps.dropMode } : {}),
      ...(deps.cutBeats !== undefined ? { cutBeats: deps.cutBeats } : {}),
    });
    console.log(
      `${LOG} generated swell: ${swellSteps.length} steps over ${beats} beats, ` +
        `${swellSteps[0]?.value.toFixed(2)} -> ${swellSteps[swellSteps.length - 2]?.value.toFixed(2)} ` +
        `then drop to ${swellSteps[swellSteps.length - 1]?.value.toFixed(2)}`,
    );

    let filterSteps: EnvelopeStep[] | null = null;
    let filterTarget: { deviceIndex: number; parameterIndex: number } | null = null;
    if (deps.includeFilterSweep) {
      const resolved = await resolveFilterParameter(deps.reader, track.index);
      const range = { min: resolved.min, max: resolved.max };
      if (deps.filterMode === "dropCut") {
        filterSteps = buildFilterDropCutSteps({
          clipLengthBeats: beats,
          parameterRange: range,
          ...(deps.filterOpenFromHz !== undefined ? { openFromHz: deps.filterOpenFromHz } : {}),
          ...(deps.filterOpenToHz !== undefined ? { openToHz: deps.filterOpenToHz } : {}),
          ...(deps.filterClosedHz !== undefined ? { closedHz: deps.filterClosedHz } : {}),
          ...(deps.cutBeats !== undefined ? { cutBeats: deps.cutBeats } : {}),
        });
        console.log(
          `${LOG} generated filter drop-cut on "${resolved.deviceName}" / ` +
            `"${resolved.parameterName}": opens to ${deps.filterOpenToHz ?? 8000} Hz, ` +
            `slams to ${deps.filterClosedHz ?? 300} Hz at the drop`,
        );
      } else {
        filterSteps = buildFilterSweepSteps({
          clipLengthBeats: beats,
          stepBeats: 1,
          parameterRange: range,
        });
        console.log(
          `${LOG} generated filter sweep on "${resolved.deviceName}" / ` +
            `"${resolved.parameterName}": 300 Hz -> 4 kHz over ${beats} beats`,
        );
      }
      filterTarget = {
        deviceIndex: resolved.deviceIndex,
        parameterIndex: resolved.parameterIndex,
      };
    }

    let reverbSteps: EnvelopeStep[] | null = null;
    let reverbSendIndex: number | null = null;
    if (deps.includeReverbSpike) {
      if (deps.reverbSendIndex === undefined) {
        throw new Error(
          "includeReverbSpike needs reverbSendIndex: which send feeds the reverb " +
            "return is a fact about the Set and is never guessed",
        );
      }
      reverbSendIndex = deps.reverbSendIndex;
      reverbSteps = buildReverbSpikeSteps({
        clipLengthBeats: beats,
        ...(deps.reverbBaseline !== undefined ? { baseline: deps.reverbBaseline } : {}),
        ...(deps.reverbSpikeValue !== undefined ? { spikeValue: deps.reverbSpikeValue } : {}),
        ...(deps.reverbSpikeBeats !== undefined ? { spikeBeats: deps.reverbSpikeBeats } : {}),
      });
      console.log(
        `${LOG} generated reverb spike on send ${reverbSendIndex}: ` +
          `${deps.reverbSpikeValue ?? 1.0} for the first ${deps.reverbSpikeBeats ?? 0.02} beats ` +
          `of the drop clip, baseline ${deps.reverbBaseline ?? 0.1}`,
      );
    }

    const base: Omit<GenerateDubDelayResult, "status" | "writes"> = {
      track: { index: track.index, name: track.name },
      device: { index: device.index, name: device.name },
      swellParameter: {
        index: swellParameter.index,
        name: swellParameter.name,
        viaFeedbackParameter,
      },
      beats,
      swellSteps,
      filterSteps,
      reverbSteps,
    };

    // -- 3. Apply, only with explicit approval ----------------------------
    if (deps.approved !== true) {
      console.log(
        `${LOG} plan ready (planned_not_applied): review the steps, then ` +
          `re-call with approved: true to write them to Session clip ${clipIndex}`,
      );
      return { ...base, status: "planned_not_applied", writes: null };
    }
    if (!deps.bridge) {
      throw new Error("approved is true but no bridge was provided; nothing was written");
    }

    const writes: EnvelopeWriteResult[] = [];
    const swellWrite = await deps.bridge.call("set_clip_envelope", {
      track_index: track.index,
      clip_index: clipIndex,
      device_index: device.index,
      parameter_index: swellParameter.index,
      steps: swellSteps,
    });
    writes.push(assertReadbackVerified(swellWrite, "swell envelope"));
    console.log(`${LOG} swell envelope written and read back verified`);

    if (filterSteps && filterTarget) {
      const filterWrite = await deps.bridge.call("set_clip_envelope", {
        track_index: track.index,
        clip_index: clipIndex,
        device_index: filterTarget.deviceIndex,
        parameter_index: filterTarget.parameterIndex,
        steps: filterSteps,
      });
      writes.push(assertReadbackVerified(filterWrite, "filter envelope"));
      console.log(`${LOG} filter sweep written and read back verified`);
    }

    if (reverbSteps && reverbSendIndex !== null) {
      const spikeWrite = await deps.bridge.call("set_clip_envelope", {
        track_index: track.index,
        clip_index: deps.spikeClipIndex ?? clipIndex,
        send_index: reverbSendIndex,
        steps: reverbSteps,
      });
      writes.push(assertReadbackVerified(spikeWrite, "reverb spike envelope"));
      console.log(`${LOG} reverb spike envelope written and read back verified`);
    }

    return { ...base, status: "applied_verified", writes };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`${LOG} failed: ${message}`);
    throw error instanceof Error ? error : new Error(message);
  }
}

// ---------------------------------------------------------------------------
// Cue input: the shape a Mixer-side planner emits as data (KIHACHI's draft
// node writes exactly this into state["mixer_instructions"]["automation_cue"]).
// The cue is intent, not a Live call: its beats are arrangement-absolute
// (32.0 -> 48.0), while the writer works clip-internally, so the cue's span
// becomes the section length and the section's clip carries beats 0..span.
// Its "Feedback" parameter is likewise intent -- the executor resolves the
// real parameter at apply time (Dry/Wet on the External Audio Effect, per
// the header note) and reports which one it used.
// ---------------------------------------------------------------------------

export interface DubDelayCue {
  target_track: string;
  effect_type?: string;
  parameter?: string;
  curve_type: "sigmoid_with_drop_cut" | "sigmoid" | "quadratic";
  start_beat: number;
  end_beat: number;
  min_val: number;
  max_val: number;
  /** Level after the drop, as a fraction. Default 0.25. */
  drop_val?: number;
}

export interface CueTranslation {
  trackName: string;
  barLength: number;
  swellFrom: number;
  swellTo: number;
  dropTo: number;
  curve: SwellCurve;
  dropMode: DropMode;
}

export function translateDubDelayCue(cue: DubDelayCue): CueTranslation {
  if (!cue.target_track) {
    throw new Error("cue.target_track must be a non-empty string");
  }
  const span = cue.end_beat - cue.start_beat;
  if (!Number.isFinite(span) || span < 8 || span % 4 !== 0) {
    throw new Error(
      `cue span (end_beat - start_beat) must be a whole number of bars >= 2; got ${span} beats`,
    );
  }
  for (const [label, value] of [
    ["min_val", cue.min_val],
    ["max_val", cue.max_val],
  ] as const) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      throw new Error(`cue.${label} must be between 0.0 and 1.0`);
    }
  }
  if (cue.max_val <= cue.min_val) {
    throw new Error("cue.max_val must be greater than cue.min_val for a swell");
  }
  switch (cue.curve_type) {
    case "sigmoid_with_drop_cut":
      return {
        trackName: cue.target_track,
        barLength: span / 4,
        swellFrom: cue.min_val,
        swellTo: cue.max_val,
        dropTo: cue.drop_val ?? 0.25,
        curve: "sigmoid",
        dropMode: "instant",
      };
    case "sigmoid":
      return {
        trackName: cue.target_track,
        barLength: span / 4,
        swellFrom: cue.min_val,
        swellTo: cue.max_val,
        dropTo: cue.drop_val ?? 0.25,
        curve: "sigmoid",
        dropMode: "bar",
      };
    case "quadratic":
      return {
        trackName: cue.target_track,
        barLength: span / 4,
        swellFrom: cue.min_val,
        swellTo: cue.max_val,
        dropTo: cue.drop_val ?? 0.25,
        curve: "quadratic",
        dropMode: "bar",
      };
    default:
      throw new Error(`unsupported cue.curve_type: ${String(cue.curve_type)}`);
  }
}

/** Run a planner cue through the real executor (same approval gate). */
export async function generateDubDelayAutomationFromCue(
  cue: DubDelayCue,
  deps: GenerateDubDelayDeps,
): Promise<GenerateDubDelayResult> {
  const translated = translateDubDelayCue(cue);
  console.log(
    `${LOG} cue for "${translated.trackName}": beats ${cue.start_beat} -> ${cue.end_beat} ` +
      `become a ${translated.barLength}-bar section, curve ${translated.curve}, ` +
      `drop ${translated.dropMode}` +
      (cue.parameter
        ? ` (cue asks for "${cue.parameter}"; the executor resolves the real parameter)`
        : ""),
  );
  return generateDubDelayAutomation(translated.trackName, translated.barLength, {
    ...deps,
    swellFrom: translated.swellFrom,
    swellTo: translated.swellTo,
    dropTo: translated.dropTo,
    curve: translated.curve,
    dropMode: translated.dropMode,
  });
}
