/**
 * Adapter: bind the extension's real SDK provider to the MW10 readers.
 *
 * SdkLiveProvider (sdkLiveProvider.ts) already exposes exactly the two
 * read shapes the dub-delay automation needs — getTracks() and
 * getTrackDevices({ track_index }) — with parameter states carrying
 * index / name / value / min / max. This module binds them structurally
 * (no SDK import of its own, so it type-checks anywhere) and assembles
 * the dependency bundle the generators and the pipeline bridge consume:
 *
 *   const deps = createMw10Deps(new SdkLiveProvider(ctx), new BridgeClient());
 *   await generateDubDelayAutomation("MW10 Dub Send", 32, deps);
 *   const stream = listenToMw10PipelineStream(url, deps);
 *
 * Reads only: the provider is used exclusively through its get* methods.
 * All writes still go through the BridgeClient and the approval flow.
 */
import type { BridgeCall, TrackDevicesReader } from "./dubDelayAutomation";
import type {
  DubDelayLiveReader,
  GenerateDubDelayDeps,
} from "./dubDelaySendAutomation";

/** Structural view of SdkLiveProvider's read surface (sdkLiveProvider.ts). */
export interface SdkLiveProviderLike {
  getTracks(): Promise<{
    tracks: Array<{ index: number; name: string; has_midi_input: boolean }>;
  }>;
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

/** Wrap the SDK provider as the TrackDevicesReader the planners consume. */
export function createTrackDevicesReader(
  provider: SdkLiveProviderLike,
): TrackDevicesReader {
  return {
    getTrackDevices: (params) => provider.getTrackDevices(params),
  };
}

/** Wrap the SDK provider as the full DubDelayLiveReader (tracks + devices). */
export function createDubDelayLiveReader(
  provider: SdkLiveProviderLike,
): DubDelayLiveReader {
  return {
    getTracks: () => provider.getTracks(),
    getTrackDevices: (params) => provider.getTrackDevices(params),
  };
}

/**
 * Assemble the dependency bundle shared by generateDubDelayAutomation,
 * generateDubDelayAutomationFromCue and listenToMw10PipelineStream.
 */
export function createMw10Deps(
  provider: SdkLiveProviderLike,
  bridge: BridgeCall,
): GenerateDubDelayDeps {
  return { reader: createDubDelayLiveReader(provider), bridge };
}
