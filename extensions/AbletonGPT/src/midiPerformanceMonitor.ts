// MIDI performance monitor: aggregate played notes and sync the stats to
// the gateway's /api/midi-log (16_MW10ゲートウェイ), which files them into
// the Obsidian session note.
//
// The draft this is based on listened with targetTrack.on("midi_note_on").
// Tracks do not emit note events to an extension -- there is no live note
// stream in this host (the same wall as the APC40 pad/CC drafts). So the
// note source is injectable, and this module ships one source that exists
// today: the notes already recorded into a clip, read back through the
// bridge's get_midi_clip_notes. A future MIDI forwarder can feed the same
// monitor live.
//
// Two draft defects fixed: the flush function was stashed on `global`
// (one monitor would overwrite another's, and nothing could await it) --
// the monitor is a returned handle instead; and Math.min(...velocities)
// spreads an unbounded array, replaced by a single pass.

export interface MidiNoteEvent {
  note: number;
  velocity: number;
}

export interface MidiStatsPayload {
  session_id: string;
  track_name: string;
  total_notes: number;
  avg_velocity: number;
  min_velocity: number;
  max_velocity: number;
  /** Pitch histogram, note name -> hits (e.g. { "C3": 12, "G#3": 5 }). */
  note_distribution: Record<string, number>;
}

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

// MIDI number -> note name, sharps only. Octave convention is Ableton
// Live's own: middle C (60) is C3, note 0 is C-2, note 127 is G8 -- the
// names a Live user sees in the piano roll. (The Roland/scientific
// C4 = 60 convention would mislabel everything by one octave here.)
// The gateway's _note_sort_value in automation_log.py inverts THIS
// convention; the two must stay in sync.
export function midiNoteName(midiNumber: number): string {
  if (!Number.isInteger(midiNumber) || midiNumber < 0 || midiNumber > 127) {
    throw new Error(`MIDI note number must be an integer 0..127; got ${midiNumber}`);
  }
  const name = NOTE_NAMES[midiNumber % 12] as string;
  const octave = Math.floor(midiNumber / 12) - 2;
  return `${name}${octave}`;
}

// Pure aggregation over note-on velocities (a velocity-0 "note-on" is a
// note-off by MIDI convention and never reaches this function -- the
// monitor filters it). Average is rounded to 1 decimal, the precision the
// note renders at.
export function computeMidiStats(
  sessionId: string,
  trackName: string,
  notes: MidiNoteEvent[],
): MidiStatsPayload {
  if (notes.length === 0) {
    throw new Error("notes must not be empty");
  }
  let sum = 0;
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  const distribution: Record<string, number> = {};
  for (const event of notes) {
    if (!Number.isInteger(event.velocity) || event.velocity < 1 || event.velocity > 127) {
      throw new Error(`velocity must be an integer 1..127; got ${event.velocity}`);
    }
    sum += event.velocity;
    if (event.velocity < min) min = event.velocity;
    if (event.velocity > max) max = event.velocity;
    const name = midiNoteName(event.note);
    distribution[name] = (distribution[name] ?? 0) + 1;
  }
  return {
    session_id: sessionId,
    track_name: trackName,
    total_notes: notes.length,
    avg_velocity: Math.round((sum / notes.length) * 10) / 10,
    min_velocity: min,
    max_velocity: max,
    note_distribution: distribution,
  };
}

// Adapter for clip-note reads: the bridge's note objects carry their
// pitch under `pitch` (Live's naming); accept `note` too so either
// producer's shape works.
export function notesFromClipNotes(
  clipNotes: Array<{ pitch?: number; note?: number; velocity: number }>,
): MidiNoteEvent[] {
  return clipNotes.map((clipNote) => {
    const note = clipNote.pitch ?? clipNote.note;
    if (note === undefined) {
      throw new Error("clip note has neither a pitch nor a note field");
    }
    return { note, velocity: clipNote.velocity };
  });
}

export type MidiNoteSource = (emit: (event: MidiNoteEvent) => void) => { close(): void };

export type MidiFlushResult =
  | { sent: true; payload: MidiStatsPayload; response: unknown }
  | { sent: false; reason: string; payload?: MidiStatsPayload; status?: number };

export interface MidiPerformanceMonitorOptions {
  sessionId: string;
  trackName: string;
  /** Gateway endpoint. Default http://127.0.0.1:8000/api/midi-log. */
  endpoint?: string;
  token?: string;
  fetchImpl?: typeof fetch;
}

export interface MidiPerformanceMonitor {
  /** Feed one note-on event (velocity 0 is ignored as a note-off). */
  push(event: MidiNoteEvent): void;
  /** Attach an external note source; returns a detach function. */
  attach(source: MidiNoteSource): () => void;
  /** Notes captured so far. */
  count(): number;
  /** The stats as they would be sent now, or null when nothing played. */
  stats(): MidiStatsPayload | null;
  /** POST the stats to the gateway. Never throws; the result says why. */
  flush(): Promise<MidiFlushResult>;
}

const LOG = "[MIDI Monitor]";
export const DEFAULT_MIDI_LOG_URL = "http://127.0.0.1:8000/api/midi-log";

export function createMidiPerformanceMonitor(
  options: MidiPerformanceMonitorOptions,
): MidiPerformanceMonitor {
  const notes: MidiNoteEvent[] = [];
  const endpoint = options.endpoint ?? DEFAULT_MIDI_LOG_URL;
  console.log(`${LOG} initialized performance tracking for track: ${options.trackName}`);

  const currentStats = (): MidiStatsPayload | null =>
    notes.length === 0
      ? null
      : computeMidiStats(options.sessionId, options.trackName, notes);

  return {
    push(event: MidiNoteEvent): void {
      if (event.velocity > 0) {
        notes.push({ note: event.note, velocity: event.velocity });
      }
    },
    attach(source: MidiNoteSource): () => void {
      const handle = source((event) => {
        if (event.velocity > 0) {
          notes.push({ note: event.note, velocity: event.velocity });
        }
      });
      return () => handle.close();
    },
    count(): number {
      return notes.length;
    },
    stats(): MidiStatsPayload | null {
      return currentStats();
    },
    async flush(): Promise<MidiFlushResult> {
      const payload = currentStats();
      if (!payload) {
        console.log(`${LOG} no notes recorded to sync`);
        return { sent: false, reason: "no notes recorded" };
      }
      const fetchImpl = options.fetchImpl ?? globalThis.fetch;
      console.log(`${LOG} sending MIDI performance payload to ${endpoint}`, payload);
      try {
        const response = await fetchImpl(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(options.token !== undefined ? { "X-Token": options.token } : {}),
          },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          console.error(`${LOG} gateway answered HTTP ${response.status}`);
          return { sent: false, reason: `HTTP ${response.status}`, payload, status: response.status };
        }
        const result: unknown = await response.json();
        console.log(`${LOG} MIDI stats successfully synced to Obsidian`, result);
        return { sent: true, payload, response: result };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error(`${LOG} failed to sync MIDI stats: ${message}`);
        return { sent: false, reason: message, payload };
      }
    },
  };
}
