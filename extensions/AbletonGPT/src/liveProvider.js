// Live provider interface plus two implementations.
//
// `LiveProvider` is the seam between the transport/protocol layer and Ableton. Swap the
// implementation without touching the protocol:
//   - MockLiveProvider: canned data + in-memory mutations, so the companion runs and can
//     be exercised end-to-end WITHOUT the Extensions SDK or a running Live.
//   - SdkLiveProvider: the real adapter. Its methods are stubs to be filled in against
//     the Ableton Extensions SDK inside your Live 12 Suite Beta project.

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
}

// Real adapter skeleton. Construct it with whatever handle the Extensions SDK gives you
// for the Live Set, then implement each method with SDK calls. The method contracts
// (return shapes) must match MockLiveProvider so the Python side is backend-agnostic.
export class SdkLiveProvider extends LiveProvider {
  constructor(sdk) {
    super();
    if (!sdk) {
      throw new Error(
        "SdkLiveProvider requires the Ableton Extensions SDK handle; use MockLiveProvider without it",
      );
    }
    this.sdk = sdk;
  }

  async getTempo() {
    // TODO(beta): return { tempo: <Live Set tempo via this.sdk> }.
    throw new Error("SdkLiveProvider.getTempo is not implemented yet");
  }

  async getTracks() {
    // TODO(beta): return { tracks: [{ index, name, has_midi_input }, ...] }.
    throw new Error("SdkLiveProvider.getTracks is not implemented yet");
  }

  async getSelectedContext() {
    // TODO(beta): return the currently selected track/clip/scene indices.
    throw new Error("SdkLiveProvider.getSelectedContext is not implemented yet");
  }

  async createMidiClip(_params) {
    // TODO(beta): create a clip in the target empty slot and add the notes, then return
    // { track_index, clip_index, name, length_beats, note_count }. Keep it non-destructive
    // (refuse a non-empty slot), matching the Remote Script backend's guarantees.
    throw new Error("SdkLiveProvider.createMidiClip is not implemented yet");
  }
}
