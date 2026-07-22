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
  async getMixSnapshot() {
    throw new Error("not implemented");
  }
  async addNativeDevice(_params) {
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
    // Canned devices per track index, with mutable parameter values.
    this.deviceState = {
      0: [
        {
          name: "Reverb",
          parameters: [
            { name: "Device On", value: 1, min: 0, max: 1, is_quantized: true, value_items: ["Off", "On"] },
            { name: "Dry/Wet", value: 0.3, min: 0, max: 1, is_quantized: false, default_value: 0.5 },
          ],
        },
      ],
    };
  }

  static _paramState(index, parameter) {
    const { min, max, value } = parameter;
    const state = {
      index,
      name: parameter.name,
      value,
      normalized_value: max === min ? 0 : (value - min) / (max - min),
      min,
      max,
      is_quantized: parameter.is_quantized,
    };
    if (parameter.is_quantized) {
      state.value_items = parameter.value_items.slice();
    } else {
      state.default_value = parameter.default_value;
    }
    return state;
  }

  _requireDevice(trackIndex, deviceIndex) {
    const track = this._track(trackIndex);
    const di = Number(deviceIndex);
    if (!Number.isInteger(di) || di < 0) {
      throw new Error("device_index must be a non-negative integer");
    }
    const device = (this.deviceState[track.index] || [])[di];
    if (!device) {
      throw new Error("device_index is out of range");
    }
    return device;
  }

  _requireParameter(trackIndex, deviceIndex, parameterIndex) {
    const device = this._requireDevice(trackIndex, deviceIndex);
    const pi = Number(parameterIndex);
    if (!Number.isInteger(pi) || pi < 0) {
      throw new Error("parameter_index must be a non-negative integer");
    }
    const parameter = device.parameters[pi];
    if (!parameter) {
      throw new Error("parameter_index is out of range");
    }
    return { device, parameter, index: pi };
  }

  async getTrackDevices(params) {
    const track = this._track(params.track_index);
    const devices = (this.deviceState[track.index] || []).map((device, index) => ({
      index,
      name: device.name,
      parameters: device.parameters.map((parameter, parameterIndex) =>
        MockLiveProvider._paramState(parameterIndex, parameter),
      ),
    }));
    return { track_index: Number(params.track_index), track: track.name, devices };
  }

  async setDeviceParameter(params) {
    const { device, parameter, index } = this._requireParameter(
      params.track_index,
      params.device_index,
      params.parameter_index,
    );
    let value = Number(params.value);
    if (params.normalized) {
      value = parameter.min + value * (parameter.max - parameter.min);
    }
    if (value < parameter.min || value > parameter.max) {
      throw new Error("parameter value out of range");
    }
    parameter.value = value;
    return { device: device.name, parameter: MockLiveProvider._paramState(index, parameter) };
  }

  async resetDeviceParameter(params) {
    const { device, parameter, index } = this._requireParameter(
      params.track_index,
      params.device_index,
      params.parameter_index,
    );
    if (parameter.is_quantized) {
      throw new Error("quantized parameters do not expose a reliable default value");
    }
    parameter.value = parameter.default_value;
    return { device: device.name, parameter: MockLiveProvider._paramState(index, parameter) };
  }

  async setDevicePower(params) {
    const device = this._requireDevice(params.track_index, params.device_index);
    const parameter = device.parameters[0];
    if (!parameter) {
      throw new Error("device has no power parameter");
    }
    parameter.value = params.enabled ? 1 : 0;
    return {
      device: device.name,
      enabled: parameter.value >= 0.5,
      parameter: MockLiveProvider._paramState(0, parameter),
    };
  }

  async getTempo() {
    return { tempo: this.tempo };
  }

  async getTracks() {
    return { tracks: this.tracks };
  }

  async getState() {
    // Matches SdkLiveProvider.getState: no is_playing / signature (no SDK API for them).
    return {
      tempo: this.tempo,
      scene_count: 8,
      tracks: this.tracks.map((track) => ({
        index: track.index,
        name: track.name,
        volume: 0.85,
        mute: false,
        solo: false,
        arm: false,
        clip_slots: 8,
      })),
    };
  }

  async getSelectedContext() {
    return { track_index: 0, clip_index: null, scene_index: 0 };
  }

  static _mixState(index, track) {
    return {
      index,
      name: track.name,
      volume: typeof track.volume === "number" ? track.volume : 0.85,
      pan: typeof track.pan === "number" ? track.pan : 0,
      mute: Boolean(track.mute),
      solo: Boolean(track.solo),
      // The Extensions SDK exposes no meter, so parity keeps this null (the snapshot
      // builder drops the momentary meter anyway).
      output_meter_level: null,
      sends: (track.sends || []).map((value, sendIndex) => ({ index: sendIndex, value })),
    };
  }

  async getMixSnapshot() {
    return {
      tracks: this.tracks.map((track, index) => MockLiveProvider._mixState(index, track)),
      returns: [
        MockLiveProvider._mixState(0, { name: "A-Reverb", volume: 0.5, pan: 0, sends: [] }),
      ],
      master: MockLiveProvider._mixState(-1, { name: "Master", volume: 0.85, pan: 0, sends: [] }),
      meter_note: "no meter in the Extensions SDK; output_meter_level is null",
    };
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

  async addNativeDevice(params) {
    const track = this._track(params.track_index);
    const name = String(params.device_name ?? "").trim();
    if (!name || name.length > 200) {
      throw new Error("device_name must contain 1 to 200 characters");
    }
    let index = params.index === undefined ? -1 : Number(params.index);
    if (!Number.isInteger(index) || index < -1) {
      throw new Error("index must be -1 or a non-negative integer");
    }
    const devices = this.deviceState[track.index] || (this.deviceState[track.index] = []);
    const before = devices.length;
    if (index > before) {
      throw new Error("device insertion index out of range");
    }
    const device = {
      name,
      parameters: [
        { name: "Device On", value: 1, min: 0, max: 1, is_quantized: true, value_items: ["Off", "On"] },
      ],
    };
    if (index === -1) {
      devices.push(device);
      index = before;
    } else {
      devices.splice(index, 0, device);
    }
    return { track: track.name, index, name, device_count: devices.length };
  }

  _track(index) {
    const i = Number(index);
    if (!Number.isInteger(i) || i < 0) {
      throw new Error("track_index must be a non-negative integer");
    }
    const track = this.tracks[i];
    if (!track) {
      throw new Error("track_index is out of range");
    }
    return track;
  }

  async setTempo(params) {
    const bpm = Number(params.bpm);
    if (!(bpm > 0)) {
      throw new Error("bpm must be positive");
    }
    this.tempo = bpm;
    return { tempo: this.tempo };
  }

  async setTrackVolume(params) {
    const track = this._track(params.track_index);
    track.volume = Number(params.volume);
    return { track: track.name, volume: track.volume };
  }

  async setTrackPan(params) {
    const track = this._track(params.track_index);
    track.pan = Number(params.pan);
    return { track: track.name, pan: track.pan };
  }

  async setTrackMute(params) {
    const track = this._track(params.track_index);
    track.mute = Boolean(params.muted);
    return { track: track.name, muted: track.mute };
  }

  async setTrackSolo(params) {
    const track = this._track(params.track_index);
    track.solo = Boolean(params.soloed);
    return { track: track.name, soloed: track.solo };
  }

  async setTrackArm(params) {
    const track = this._track(params.track_index);
    track.arm = Boolean(params.armed);
    return { track: track.name, arm: track.arm };
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
