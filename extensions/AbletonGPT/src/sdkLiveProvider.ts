// Real Live provider: maps the companion's command set onto the Ableton Extensions SDK.
//
// Implements the same interface as MockLiveProvider (src/liveProvider.js) so the protocol
// layer is backend-agnostic. Every method uses only the confirmed v1.0.0 SDK surface.

import { type ExtensionContext, MidiClip, MidiTrack, type NoteDescription, Track } from "@ableton-extensions/sdk";

// A note as it arrives over the wire from the Python side (snake_case).
export type IncomingNote = {
  pitch: number;
  start_time: number;
  duration: number;
  velocity?: number;
  probability?: number;
  mute?: boolean;
};

export type CreateMidiClipParams = {
  track_index: number;
  clip_index: number;
  name?: string;
  length_beats: number;
  notes?: IncomingNote[];
};

export type ApplyExpressionParams = {
  track_index: number;
  clip_index: number;
  length_beats?: number;
  notes?: IncomingNote[];
};

export class SdkLiveProvider {
  private readonly context: ExtensionContext<"1.0.0">;

  constructor(context: ExtensionContext<"1.0.0">) {
    this.context = context;
  }

  private get song() {
    return this.context.application.song;
  }

  private requireTrack(index: number): Track<"1.0.0"> {
    const trackIndex = Number(index);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    const track = this.song.tracks[trackIndex];
    if (!track) {
      throw new Error("track_index is out of range");
    }
    return track;
  }

  async getTempo(): Promise<{ tempo: number }> {
    return { tempo: this.song.tempo };
  }

  async getTracks(): Promise<{ tracks: Array<{ index: number; name: string; has_midi_input: boolean }> }> {
    const tracks = this.song.tracks.map((track, index) => ({
      index,
      name: track.name,
      has_midi_input: track instanceof MidiTrack,
    }));
    return { tracks };
  }

  async getState(): Promise<{
    tempo: number;
    scene_count: number;
    tracks: Array<{
      index: number;
      name: string;
      volume: number;
      mute: boolean;
      solo: boolean;
      arm: boolean;
      clip_slots: number;
    }>;
  }> {
    const song = this.song;
    const tracks = await Promise.all(
      song.tracks.map(async (track, index) => ({
        index,
        name: track.name,
        volume: await track.mixer.volume.getValue(),
        mute: track.mute,
        solo: track.solo,
        arm: track.arm,
        clip_slots: track.clipSlots.length,
      })),
    );
    // No is_playing / signature: the SDK exposes no transport state or Song-level time
    // signature (only per-scene signatures exist).
    return {
      tempo: song.tempo,
      scene_count: song.scenes.length,
      tracks,
    };
  }

  async getMidiClipNotes(params: { track_index: number; clip_index: number }): Promise<{
    track_index: number;
    track: string;
    clip_index: number;
    clip: string;
    length_beats: number;
    tempo: number;
    notes: Array<{
      pitch: number;
      start_time: number;
      duration: number;
      velocity: number;
      probability: number;
    }>;
    note_count: number;
    truncated: boolean;
  }> {
    const trackIndex = Number(params.track_index);
    const clipIndex = Number(params.clip_index);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    if (!Number.isInteger(clipIndex) || clipIndex < 0) {
      throw new Error("clip_index must be a non-negative integer");
    }

    const track = this.song.tracks[trackIndex];
    if (!track) {
      throw new Error("track_index is out of range");
    }
    if (!(track instanceof MidiTrack)) {
      throw new Error("target track is not a MIDI track");
    }
    const slot = track.clipSlots[clipIndex];
    if (!slot) {
      throw new Error("clip_index is out of range");
    }
    const clip = slot.clip;
    if (clip === null) {
      throw new Error("target clip slot is empty");
    }
    if (!(clip instanceof MidiClip)) {
      throw new Error("target clip is not a MIDI clip");
    }

    const source = clip.notes.slice(0, 4096);
    const notes = source.map((note) => ({
      pitch: note.pitch,
      start_time: note.startTime,
      duration: note.duration,
      velocity: note.velocity ?? 100,
      probability: note.probability ?? 1.0,
    }));
    return {
      track_index: trackIndex,
      track: track.name,
      clip_index: clipIndex,
      clip: clip.name,
      length_beats: clip.duration,
      tempo: this.song.tempo,
      notes,
      note_count: clip.notes.length,
      truncated: clip.notes.length > notes.length,
    };
  }

  async setTempo(params: { bpm: number }): Promise<{ tempo: number }> {
    const bpm = Number(params.bpm);
    if (!(bpm > 0)) {
      throw new Error("bpm must be positive");
    }
    this.song.tempo = bpm;
    return { tempo: this.song.tempo };
  }

  async setTrackVolume(params: { track_index: number; volume: number }): Promise<{ track: string; volume: number }> {
    const track = this.requireTrack(params.track_index);
    await track.mixer.volume.setValue(Number(params.volume));
    return { track: track.name, volume: await track.mixer.volume.getValue() };
  }

  async setTrackPan(params: { track_index: number; pan: number }): Promise<{ track: string; pan: number }> {
    const track = this.requireTrack(params.track_index);
    await track.mixer.panning.setValue(Number(params.pan));
    return { track: track.name, pan: await track.mixer.panning.getValue() };
  }

  async setTrackMute(params: { track_index: number; muted: boolean }): Promise<{ track: string; muted: boolean }> {
    const track = this.requireTrack(params.track_index);
    track.mute = Boolean(params.muted);
    return { track: track.name, muted: track.mute };
  }

  async setTrackSolo(params: { track_index: number; soloed: boolean }): Promise<{ track: string; soloed: boolean }> {
    const track = this.requireTrack(params.track_index);
    track.solo = Boolean(params.soloed);
    return { track: track.name, soloed: track.solo };
  }

  async setTrackArm(params: { track_index: number; armed: boolean }): Promise<{ track: string; arm: boolean }> {
    const track = this.requireTrack(params.track_index);
    track.arm = Boolean(params.armed);
    return { track: track.name, arm: track.arm };
  }

  async getSelectedContext(): Promise<never> {
    // The SDK exposes selection only through context-menu command arguments
    // (ArrangementSelection / ClipSlotSelection), not as an ambient query.
    throw new Error(
      "get_selected_context is not supported by the Extensions SDK; selection is delivered via context-menu commands only",
    );
  }

  async createMidiClip(params: CreateMidiClipParams): Promise<{
    track_index: number;
    clip_index: number;
    name: string;
    length_beats: number;
    note_count: number;
  }> {
    const trackIndex = Number(params.track_index);
    const clipIndex = Number(params.clip_index);
    const length = Number(params.length_beats);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    if (!Number.isInteger(clipIndex) || clipIndex < 0) {
      throw new Error("clip_index must be a non-negative integer");
    }
    if (!(length > 0)) {
      throw new Error("length_beats must be positive");
    }

    const track = this.song.tracks[trackIndex];
    if (!track) {
      throw new Error("track_index is out of range");
    }
    if (!(track instanceof MidiTrack)) {
      throw new Error("target track is not a MIDI track");
    }
    const slot = track.clipSlots[clipIndex];
    if (!slot) {
      throw new Error("clip_index is out of range");
    }
    if (slot.clip !== null) {
      // Non-destructive: never overwrite an existing clip.
      throw new Error("target clip slot is not empty");
    }

    const incoming = Array.isArray(params.notes) ? params.notes : [];
    const notes = incoming.map(toNoteDescription);

    const clip = await slot.createMidiClip(length);
    if (typeof params.name === "string" && params.name.length > 0) {
      clip.name = params.name;
    }
    if (notes.length > 0) {
      clip.notes = notes;
    }
    return {
      track_index: trackIndex,
      clip_index: clipIndex,
      name: clip.name,
      length_beats: length,
      note_count: notes.length,
    };
  }

  async applyExpressionToClip(params: ApplyExpressionParams): Promise<{
    track_index: number;
    clip_index: number;
    name: string;
    length_beats: number;
    note_count: number;
  }> {
    const trackIndex = Number(params.track_index);
    const clipIndex = Number(params.clip_index);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    if (!Number.isInteger(clipIndex) || clipIndex < 0) {
      throw new Error("clip_index must be a non-negative integer");
    }

    const track = this.song.tracks[trackIndex];
    if (!track) {
      throw new Error("track_index is out of range");
    }
    if (!(track instanceof MidiTrack)) {
      throw new Error("target track is not a MIDI track");
    }
    const slot = track.clipSlots[clipIndex];
    if (!slot) {
      throw new Error("clip_index is out of range");
    }
    const clip = slot.clip;
    if (clip === null) {
      throw new Error("target clip slot is empty");
    }
    if (!(clip instanceof MidiClip)) {
      throw new Error("target clip is not a MIDI clip");
    }

    // Replace the clip's notes wholesale; the setter overwrites the full note set, so the
    // note count is whatever the caller sends (the expression plan keeps it unchanged).
    const incoming = Array.isArray(params.notes) ? params.notes : [];
    const notes = incoming.map(toNoteDescription);
    clip.notes = notes;

    return {
      track_index: trackIndex,
      clip_index: clipIndex,
      name: clip.name,
      length_beats: clip.duration,
      note_count: notes.length,
    };
  }
}

// Build a NoteDescription, adding optional fields only when present so the result stays
// valid under `exactOptionalPropertyTypes`.
function toNoteDescription(note: IncomingNote): NoteDescription {
  const description: NoteDescription = {
    pitch: Number(note.pitch),
    startTime: Number(note.start_time),
    duration: Number(note.duration),
  };
  if (note.velocity != null) {
    description.velocity = Number(note.velocity);
  }
  if (note.probability != null) {
    description.probability = Number(note.probability);
  }
  if (note.mute != null) {
    description.muted = Boolean(note.mute);
  }
  return description;
}
