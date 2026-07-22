// Live provider interface and the mock implementation used by the standalone companion.
//
// `LiveProvider` is the seam between the transport/protocol layer and Ableton.
//   - MockLiveProvider (here): canned data + in-memory mutations, so the companion runs
//     and can be exercised end-to-end WITHOUT the Extensions SDK or a running Live.
//   - SdkLiveProvider (src/sdkLiveProvider.ts): the real adapter that drives Live through
//     the Extensions SDK, used by the extension entry (src/extension.ts).

export class LiveProvider {
  async getTempo() {
    throw new Error("not implemented");
  }
  async getTracks() {
    throw new Error("not implemented");
  }
  async getSelectedContext() {
    throw new Error("not implemented");
  }
  async createMidiClip(_params) {
    throw new Error("not implemented");
  }
}

export class MockLiveProvider extends LiveProvider {
  constructor() {
    super();
    this.tempo = 120;
    this.tracks = [
      { index: 0, name: "MIDI 1", has_midi_input: true },
      { index: 1, name: "Audio 1", has_midi_input: false },
    ];
    // Records clips created during a session so tests can assert on mutations.
    this.createdClips = [];
    // Records expression note-replacements applied to clips.
    this.appliedExpressions = [];
  }

  async getTempo() {
    return { tempo: this.tempo };
  }

  async getTracks() {
    return { tracks: this.tracks };
  }

  async getSelectedContext() {
    return { track_index: 0, clip_index: null, scene_index: 0 };
  }

  async getMidiClipNotes(params) {
    const trackIndex = Number(params.track_index);
    const clipIndex = Number(params.clip_index);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    if (!Number.isInteger(clipIndex) || clipIndex < 0) {
      throw new Error("clip_index must be a non-negative integer");
    }
    const track = this.tracks[trackIndex];
    const notes = [
      { pitch: 60, start_time: 0.0, duration: 0.5, velocity: 80, probability: 1.0 },
      { pitch: 62, start_time: 0.5, duration: 0.5, velocity: 80, probability: 1.0 },
      { pitch: 64, start_time: 1.0, duration: 0.5, velocity: 80, probability: 1.0 },
    ];
    return {
      track_index: trackIndex,
      track: track ? track.name : "MIDI 1",
      clip_index: clipIndex,
      clip: "Mock Clip",
      length_beats: 8.0,
      tempo: this.tempo,
      notes,
      note_count: notes.length,
      truncated: false,
    };
  }

  async createMidiClip(params) {
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
    const notes = Array.isArray(params.notes) ? params.notes : [];
    const record = {
      track_index: trackIndex,
      clip_index: clipIndex,
      name: String(params.name ?? "AI Clip"),
      length_beats: length,
      note_count: notes.length,
    };
    this.createdClips.push(record);
    return record;
  }

  async applyExpressionToClip(params) {
    const trackIndex = Number(params.track_index);
    const clipIndex = Number(params.clip_index);
    if (!Number.isInteger(trackIndex) || trackIndex < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    if (!Number.isInteger(clipIndex) || clipIndex < 0) {
      throw new Error("clip_index must be a non-negative integer");
    }
    const notes = Array.isArray(params.notes) ? params.notes : [];
    const record = {
      track_index: trackIndex,
      clip_index: clipIndex,
      note_count: notes.length,
    };
    this.appliedExpressions.push(record);
    return record;
  }
}
