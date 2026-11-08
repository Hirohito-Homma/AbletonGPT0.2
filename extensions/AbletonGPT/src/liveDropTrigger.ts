// Live drop trigger: everything downstream of a button press, for firing
// the dub drop during a performance.
//
// What the draft this is based on asked for cannot be built as written,
// for two independent reasons:
//
// 1. There is no MIDI-input surface here. `LiveAPI.getMidiRemotes()` does
//    not exist, and more fundamentally the APC40 is owned by Live's
//    control-surface layer -- an extension gets no raw pad events from it.
//    So the press source is injectable, exactly like the pipeline stream
//    in mw10PipelineBridge.ts: when a real press path exists (a Remote
//    Script command that forwards a press, a companion app button, a
//    macro key), it plugs into attach() and everything below already works.
//
// 2. The draft's timing is causally backwards. It takes the press moment
//    as the drop and writes the build-up into the 16 beats BEFORE it --
//    beats that have already played, onto an Arrangement timeline no API
//    can write automation to anyway. A build-up written at press time can
//    only ever cover the FUTURE. So a press here schedules the drop at
//    the next section boundary that leaves a full build-up ahead of it,
//    and the envelopes go onto that section's Session clips, which is the
//    one place envelopes can live.
//
// On approval: the cue template (track, curve, levels) is authored by
// KIHACHI in advance, and the press is KIHACHI's own performance act --
// the same position as launching a prepared clip. So with a bridge
// configured, a press plans AND writes (read-back verified, as always);
// the unattended-message case in mw10PipelineBridge.ts is different and
// still holds its cues for a separate approval. Without a bridge, a press
// only plans.

import {
  generateDubDelayAutomationFromCue,
  translateDubDelayCue,
  type DubDelayCue,
  type DubDelayLiveReader,
  type GenerateDubDelayDeps,
  type GenerateDubDelayResult,
} from "./dubDelaySendAutomation.js";
import type { BridgeCall } from "./dubDelayAutomation.js";

const LOG = "[APC40 Live Trigger]";

export interface DropSchedule {
  /** First beat of the build-up section. */
  buildStartBeat: number;
  /** Beat the drop lands on: buildStartBeat + the cue's span. */
  dropBeat: number;
  /** The cue re-anchored to that section (all other fields from the template). */
  cue: DubDelayCue;
}

// Pure beat math: the drop goes to the first section boundary that is at
// least one full build-up ahead of now, so the section the envelopes land
// on has not started playing yet.
export function scheduleDrop(template: DubDelayCue, currentBeat: number): DropSchedule {
  if (!Number.isFinite(currentBeat) || currentBeat < 0) {
    throw new Error("currentBeat must be a finite beat position >= 0");
  }
  const span = template.end_beat - template.start_beat;
  translateDubDelayCue(template); // validates the template's span and levels
  const dropBeat = Math.ceil((currentBeat + span) / span) * span;
  const buildStartBeat = dropBeat - span;
  return {
    buildStartBeat,
    dropBeat,
    cue: { ...template, start_beat: buildStartBeat, end_beat: dropBeat },
  };
}

export interface TransportReader {
  /** Current song position in beats (the read-only get_transport_state). */
  getCurrentBeat(): Promise<number>;
}

// Default transport reader over the real bridge: get_transport_state is
// the read-only way to ask Live where the playhead is.
export function createBridgeTransportReader(bridge: BridgeCall): TransportReader {
  return {
    async getCurrentBeat(): Promise<number> {
      const state = (await bridge.call("get_transport_state", {})) as {
        current_song_time?: unknown;
      };
      if (typeof state.current_song_time !== "number") {
        throw new Error("get_transport_state did not report a numeric current_song_time");
      }
      return state.current_song_time;
    },
  };
}

/** Anything that can deliver a press: a future MIDI forwarder, a UI button... */
export type PressSource = (onPress: () => void) => { close(): void };

export interface LiveDropTriggerOptions {
  /** The pre-authored cue template; its beats are recomputed per press. */
  cueTemplate: DubDelayCue;
  reader: DubDelayLiveReader;
  transport: TransportReader;
  /** When given, a press writes (the press is the approval act). */
  bridge?: BridgeCall;
  /** Extra executor options (filter, spike, clip indices...). */
  executor?: Omit<GenerateDubDelayDeps, "reader" | "bridge" | "approved">;
  onPlanned?: (schedule: DropSchedule, result: GenerateDubDelayResult) => void;
}

export interface LiveDropTrigger {
  /** Fire one press now. Returns the schedule and the plan/write result. */
  press(): Promise<{ schedule: DropSchedule; result: GenerateDubDelayResult }>;
  /** Attach an external press source; returns a detach function. */
  attach(source: PressSource): () => void;
}

export function createLiveDropTrigger(options: LiveDropTriggerOptions): LiveDropTrigger {
  translateDubDelayCue(options.cueTemplate); // fail fast on a bad template
  let inFlight = false;

  const press = async (): Promise<{ schedule: DropSchedule; result: GenerateDubDelayResult }> => {
    if (inFlight) {
      throw new Error("a previous press is still being processed");
    }
    inFlight = true;
    try {
      const currentBeat = await options.transport.getCurrentBeat();
      const schedule = scheduleDrop(options.cueTemplate, currentBeat);
      console.log(
        `${LOG} press at beat ${currentBeat}: build-up ${schedule.buildStartBeat} -> ` +
          `drop at ${schedule.dropBeat} on "${schedule.cue.target_track}"`,
      );
      const result = await generateDubDelayAutomationFromCue(schedule.cue, {
        reader: options.reader,
        ...(options.executor ?? {}),
        ...(options.bridge ? { bridge: options.bridge, approved: true } : {}),
      });
      console.log(
        `${LOG} drop ${options.bridge ? "written" : "planned"} (${result.status}): ` +
          `${result.swellSteps.length} swell steps on "${result.swellParameter.name}"`,
      );
      options.onPlanned?.(schedule, result);
      return { schedule, result };
    } finally {
      inFlight = false;
    }
  };

  return {
    press,
    attach(source: PressSource): () => void {
      const handle = source(() => {
        void press().catch((error: unknown) => {
          const message = error instanceof Error ? error.message : String(error);
          console.error(`${LOG} press failed: ${message}`);
        });
      });
      console.log(`${LOG} press source attached (template pre-authored, press fires the drop)`);
      return () => handle.close();
    },
  };
}
