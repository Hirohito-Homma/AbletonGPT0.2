// Real Live provider: maps the companion's command set onto the Ableton Extensions SDK.
//
// Implements the same interface as MockLiveProvider (src/liveProvider.js) so the protocol
// layer is backend-agnostic. Every method uses only the confirmed v1.0.0 SDK surface.

import {
  AudioClip,
  type Device,
  type DeviceParameter,
  type ExtensionContext,
  MidiClip,
  MidiTrack,
  type NoteDescription,
  Track,
} from "@ableton-extensions/sdk";

type ParameterState = {
  index: number;
  name: string;
  value: number;
  normalized_value: number;
  min: number;
  max: number;
  is_quantized: boolean;
  value_items?: string[];
  default_value?: number;
};

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
  expected_source_note_count?: number;
  allow_note_count_change?: boolean;
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

  private requireDevice(trackIndex: number, deviceIndex: number): Device<"1.0.0"> {
    const track = this.requireTrack(trackIndex);
    const index = Number(deviceIndex);
    if (!Number.isInteger(index) || index < 0) {
      throw new Error("device_index must be a non-negative integer");
    }
    const device = track.devices[index];
    if (!device) {
      throw new Error("device_index is out of range");
    }
    return device;
  }

  private requireParameter(
    trackIndex: number,
    deviceIndex: number,
    parameterIndex: number,
  ): { device: Device<"1.0.0">; parameter: DeviceParameter<"1.0.0">; index: number } {
    const device = this.requireDevice(trackIndex, deviceIndex);
    const index = Number(parameterIndex);
    if (!Number.isInteger(index) || index < 0) {
      throw new Error("parameter_index must be a non-negative integer");
    }
    const parameter = device.parameters[index];
    if (!parameter) {
      throw new Error("parameter_index is out of range");
    }
    return { device, parameter, index };
  }

  private async parameterState(
    index: number,
    parameter: DeviceParameter<"1.0.0">,
  ): Promise<ParameterState> {
    const min = parameter.min;
    const max = parameter.max;
    const value = await parameter.getValue();
    const state: ParameterState = {
      index,
      name: parameter.name,
      value,
      normalized_value: max === min ? 0 : (value - min) / (max - min),
      min,
      max,
      is_quantized: parameter.isQuantized,
    };
    if (parameter.isQuantized) {
      state.value_items = parameter.valueItems.map((item) => item.name);
    } else {
      state.default_value = parameter.defaultValue;
    }
    return state;
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

  private async mixState(index: number, track: Track<"1.0.0">): Promise<{
    index: number;
    name: string;
    volume: number;
    pan: number;
    mute: boolean;
    solo: boolean;
    output_meter_level: null;
    sends: Array<{ index: number; value: number }>;
  }> {
    const mixer = track.mixer;
    const sends = await Promise.all(
      mixer.sends.map(async (send, sendIndex) => ({
        index: sendIndex,
        value: await send.getValue(),
      })),
    );
    return {
      index,
      name: track.name,
      volume: await mixer.volume.getValue(),
      pan: await mixer.panning.getValue(),
      mute: safeBool(() => track.mute),
      solo: safeBool(() => track.solo),
      // The SDK exposes no meter; parity keeps this null (the snapshot builder drops the
      // momentary meter anyway). mainTrack has no mute/solo, hence the guarded reads above.
      output_meter_level: null,
      sends,
    };
  }

  async getMixSnapshot(): Promise<{
    tracks: Array<Awaited<ReturnType<SdkLiveProvider["mixState"]>>>;
    returns: Array<Awaited<ReturnType<SdkLiveProvider["mixState"]>>>;
    master: Awaited<ReturnType<SdkLiveProvider["mixState"]>>;
    meter_note: string;
  }> {
    const song = this.song;
    const tracks = await Promise.all(song.tracks.map((track, index) => this.mixState(index, track)));
    const returns = await Promise.all(
      song.returnTracks.map((track, index) => this.mixState(index, track)),
    );
    const master = await this.mixState(-1, song.mainTrack);
    return {
      tracks,
      returns,
      master,
      meter_note: "the Extensions SDK exposes no meter; output_meter_level is null",
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

  async getClipWarpMarkers(params: { track_index: number; clip_index: number }): Promise<{
    track: string;
    track_index: number;
    clip_index: number;
    clip: string;
    is_audio_clip: true;
    warping: boolean;
    warp_mode: number;
    marker_count: number;
    markers: Array<{ beat_time: number; sample_time: number }>;
    read_only: true;
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
    const slot = track.clipSlots[clipIndex];
    if (!slot) {
      throw new Error("clip_index is out of range");
    }
    const clip = slot.clip;
    if (clip === null) {
      throw new Error("target clip slot is empty");
    }
    if (!(clip instanceof AudioClip)) {
      throw new Error("target clip is not an audio clip");
    }
    const markers = clip.warpMarkers.map((marker) => ({
      beat_time: marker.beatTime,
      sample_time: marker.sampleTime,
    }));
    return {
      track: track.name,
      track_index: trackIndex,
      clip_index: clipIndex,
      clip: clip.name,
      is_audio_clip: true,
      warping: clip.warping,
      warp_mode: Number(clip.warpMode),
      marker_count: markers.length,
      markers,
      read_only: true,
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

  async getTrackDevices(params: { track_index: number }): Promise<{
    track_index: number;
    track: string;
    devices: Array<{ index: number; name: string; parameters: ParameterState[] }>;
  }> {
    const track = this.requireTrack(params.track_index);
    // The SDK Device exposes only name + parameters (no class_name / type / is_active).
    const devices = await Promise.all(
      track.devices.map(async (device, index) => ({
        index,
        name: device.name,
        parameters: await Promise.all(
          device.parameters.map((parameter, parameterIndex) =>
            this.parameterState(parameterIndex, parameter),
          ),
        ),
      })),
    );
    return { track_index: Number(params.track_index), track: track.name, devices };
  }

  async setDeviceParameter(params: {
    track_index: number;
    device_index: number;
    parameter_index: number;
    value: number;
    normalized?: boolean;
  }): Promise<{ device: string; parameter: ParameterState }> {
    const { device, parameter, index } = this.requireParameter(
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
    await parameter.setValue(value);
    return { device: device.name, parameter: await this.parameterState(index, parameter) };
  }

  async resetDeviceParameter(params: {
    track_index: number;
    device_index: number;
    parameter_index: number;
  }): Promise<{ device: string; parameter: ParameterState }> {
    const { device, parameter, index } = this.requireParameter(
      params.track_index,
      params.device_index,
      params.parameter_index,
    );
    if (parameter.isQuantized) {
      throw new Error("quantized parameters do not expose a reliable default value");
    }
    await parameter.setValue(parameter.defaultValue);
    return { device: device.name, parameter: await this.parameterState(index, parameter) };
  }

  async setDevicePower(params: {
    track_index: number;
    device_index: number;
    enabled: boolean;
  }): Promise<{ device: string; enabled: boolean; parameter: ParameterState }> {
    const device = this.requireDevice(params.track_index, params.device_index);
    // Live's "Device On" is the device's first parameter (mirrors the Remote Script).
    const parameter = device.parameters[0];
    if (!parameter) {
      throw new Error("device has no power parameter");
    }
    await parameter.setValue(params.enabled ? 1 : 0);
    const value = await parameter.getValue();
    return {
      device: device.name,
      enabled: value >= 0.5,
      parameter: await this.parameterState(0, parameter),
    };
  }

  async addNativeDevice(params: {
    track_index: number;
    device_name: string;
    index?: number;
  }): Promise<{ track: string; index: number; name: string; device_count: number }> {
    const track = this.requireTrack(params.track_index);
    const name = String(params.device_name ?? "").trim();
    if (!name || name.length > 200) {
      throw new Error("device_name must contain 1 to 200 characters");
    }
    let index = params.index === undefined ? -1 : Number(params.index);
    if (!Number.isInteger(index) || index < -1) {
      throw new Error("index must be -1 or a non-negative integer");
    }
    const before = track.devices.length;
    if (index > before) {
      throw new Error("device insertion index out of range");
    }
    // insertDevice loads a built-in Live device by name (third-party plug-ins are rejected
    // by the SDK) and returns the inserted Device; -1 appends at the end of the chain.
    const insertAt = index === -1 ? before : index;
    const device = await track.insertDevice(name, insertAt);
    const after = track.devices.length;
    if (after !== before + 1) {
      throw new Error("Live did not insert the requested device");
    }
    return { track: track.name, index: insertAt, name: device.name, device_count: after };
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
    source_note_count: number;
    note_count: number;
    note_count_changed: boolean;
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

    // Expression and other in-place edits preserve note count by default. Split is the
    // only current caller that opts into a count change, and it must send the reviewed
    // source count so a stale plan is rejected before the wholesale replacement.
    const sourceNoteCount = clip.notes.length;
    const incoming = Array.isArray(params.notes) ? params.notes : [];
    const notes = incoming.map(toNoteDescription);
    const allowNoteCountChange = params.allow_note_count_change === true;
    const expectedSourceNoteCount = Number(params.expected_source_note_count);
    if (
      params.expected_source_note_count != null &&
      (!Number.isInteger(expectedSourceNoteCount) || expectedSourceNoteCount < 0)
    ) {
      throw new Error("expected_source_note_count must be a non-negative integer");
    }
    if (params.expected_source_note_count != null && sourceNoteCount !== expectedSourceNoteCount) {
      throw new Error("source MIDI clip note count changed before apply");
    }
    if (sourceNoteCount !== notes.length && !allowNoteCountChange) {
      throw new Error("expression replacement must preserve the source note count");
    }
    if (allowNoteCountChange && params.expected_source_note_count == null) {
      throw new Error("note-count-changing replacement requires expected_source_note_count");
    }
    if (allowNoteCountChange && sourceNoteCount > 0 && notes.length === 0) {
      throw new Error("note-count-changing replacement may not clear the clip");
    }
    clip.notes = notes;

    return {
      track_index: trackIndex,
      clip_index: clipIndex,
      name: clip.name,
      length_beats: clip.duration,
      source_note_count: sourceNoteCount,
      note_count: notes.length,
      note_count_changed: sourceNoteCount !== notes.length,
    };
  }
}

// Read a boolean getter that may not exist on every track (e.g. mainTrack has no
// mute/solo), defaulting to false instead of throwing.
function safeBool(read: () => boolean): boolean {
  try {
    return Boolean(read());
  } catch {
    return false;
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
