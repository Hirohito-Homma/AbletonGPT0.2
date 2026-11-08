// MW10 pipeline bridge: receive automation cues from the pipeline stream
// and turn them into dub delay automation on the real executor.
//
// Three corrections to the draft this is based on, all grounded in the
// verified record:
//
// 1. There is no server at http://127.0.0.1:8000/api/stream-mw10 yet. The
//    `com.kihachi.mw10gateway` FastAPI daemon is target-spec (v2.0), not
//    implemented; in this repo port 8000 is the MCP HTTP server. So the
//    stream source is injectable: when the daemon exists, point the URL
//    at it; until then anything that emits payloads can drive the same
//    handler. The draft's imported `applySigmoidAutomationWithDropCut`
//    from "./automationGenerator" also does not exist -- the real entry
//    point is generateDubDelayAutomationFromCue in dubDelaySendAutomation.ts.
//
// 2. EventSource is a browser API and is not guaranteed in the extension's
//    Node host, so the default source reads the SSE stream over fetch()
//    (injectable for the same reason).
//
// 3. A received cue is NEVER auto-applied. KIHACHI's Gateway rule -- kept
//    explicitly when the v2.0 spec was adopted -- is that Live writes go
//    proposal -> plan -> validation -> human approval -> write -> read
//    back. So this bridge plans on receipt and holds the cue as pending;
//    writing happens only through approvePending(), the explicit approval
//    step. The draft's "successfully applied on live timeline" log on
//    receipt would have broken that rule.

import {
  generateDubDelayAutomationFromCue,
  type DubDelayCue,
  type DubDelayLiveReader,
  type GenerateDubDelayResult,
} from "./dubDelaySendAutomation.js";
import type { BridgeCall } from "./dubDelayAutomation.js";

const LOG = "[MW10 Bridge]";
export const DEFAULT_MW10_STREAM_URL = "http://127.0.0.1:8000/api/stream-mw10";

// The stream's payload contract, as emitted by the gateway's
// /api/stream-mw10 and consumed below. The cue inside a Mixer payload
// is a full DubDelayCue (with parameter / beats_per_bar / curve_type),
// not just the five fields a progress display needs.
export interface Mw10PipelinePayload {
  status: "running" | "completed" | "error";
  node?: string;
  step?: string;
  progress?: number;
  message?: string;
  error?: string;
  data?: {
    session_id?: string;
    step?: string;
    progress?: number;
    midi_generation_range?: Record<string, unknown>;
    mixer_instructions?: {
      automation_cue?: DubDelayCue;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}

// A read-only view of one payload for progress displays. Handlers get
// every event (including "completed" / "error"); observing progress
// never plans or writes anything by itself.
export type Mw10ProgressHandler = (payload: Mw10PipelinePayload) => void;

// ---------------------------------------------------------------------------
// Payload -> cue
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

// Pull the automation cue out of a pipeline payload, or return null when
// the payload is not a Mixer-node message carrying one. Structural checks
// only; the cue's own numbers are validated by translateDubDelayCue when
// the cue is planned.
export function extractAutomationCue(payload: unknown): DubDelayCue | null {
  if (!isRecord(payload)) {
    return null;
  }
  if (payload.status !== "running" || payload.node !== "mixer") {
    return null;
  }
  const data = payload.data;
  if (!isRecord(data)) {
    return null;
  }
  const instructions = data.mixer_instructions;
  if (!isRecord(instructions)) {
    return null;
  }
  const cue = instructions.automation_cue;
  if (!isRecord(cue) || typeof cue.target_track !== "string") {
    return null;
  }
  return cue as unknown as DubDelayCue;
}

export type Mw10HandleResult =
  | { kind: "ignored"; reason: string }
  | { kind: "planned"; cue: DubDelayCue; result: GenerateDubDelayResult };

export interface Mw10HandlerDeps {
  reader: DubDelayLiveReader;
}

// Plan the cue from one payload. Planning is read-only against Live (track
// / device / parameter lookup) and never writes: the deps deliberately
// carry no bridge and no approval.
export async function handleMw10PipelinePayload(
  payload: unknown,
  deps: Mw10HandlerDeps,
): Promise<Mw10HandleResult> {
  const cue = extractAutomationCue(payload);
  if (!cue) {
    return { kind: "ignored", reason: "not a Mixer payload with an automation cue" };
  }
  console.log(`${LOG} received automation cue for "${cue.target_track}"`, cue);
  const result = await generateDubDelayAutomationFromCue(cue, { reader: deps.reader });
  console.log(
    `${LOG} plan ready (${result.status}): ${result.swellSteps.length} swell steps on ` +
      `"${result.swellParameter.name}" -- awaiting approval, nothing written`,
  );
  return { kind: "planned", cue, result };
}

// ---------------------------------------------------------------------------
// SSE source (fetch-based, injectable)
// ---------------------------------------------------------------------------

export interface SseFetchResponse {
  ok: boolean;
  status: number;
  body: {
    getReader(): {
      read(): Promise<{ done: boolean; value?: Uint8Array }>;
      cancel(): Promise<unknown>;
    };
  } | null;
}

export type SseFetch = (url: string) => Promise<SseFetchResponse>;

type SseStreamReader = ReturnType<
  NonNullable<SseFetchResponse["body"]>["getReader"]
>;

const defaultFetch: SseFetch = async (url) => {
  const response = await globalThis.fetch(url, {
    headers: { Accept: "text/event-stream" },
  });
  return response as unknown as SseFetchResponse;
};

// Minimal SSE parser: `data:` lines grouped by blank lines; comment lines
// (heartbeats starting with ":") and other fields are ignored; multi-line
// data is joined with "\n" per the SSE spec.
export class SseEventParser {
  private buffer = "";
  private dataLines: string[] = [];

  push(chunk: string): string[] {
    this.buffer += chunk;
    const completed: string[] = [];
    let newlineIndex = this.buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = this.buffer.slice(0, newlineIndex).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newlineIndex + 1);
      if (line === "") {
        if (this.dataLines.length > 0) {
          completed.push(this.dataLines.join("\n"));
          this.dataLines = [];
        }
      } else if (line.startsWith("data:")) {
        this.dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      newlineIndex = this.buffer.indexOf("\n");
    }
    return completed;
  }
}

export type Mw10PayloadSource = (
  emit: (payload: unknown) => void,
  onError: (error: unknown) => void,
) => { close(): void };

export function createFetchSseSource(options: {
  url: string;
  fetchImpl?: SseFetch;
  reconnectMs?: number;
}): Mw10PayloadSource {
  const fetchImpl = options.fetchImpl ?? defaultFetch;
  const reconnectMs = options.reconnectMs ?? 3000;
  return (emit, onError) => {
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let reader: SseStreamReader | null = null;

    const connect = async (): Promise<void> => {
      try {
        const response = await fetchImpl(options.url);
        if (!response.ok || !response.body) {
          throw new Error(`stream request failed with status ${response.status}`);
        }
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parser = new SseEventParser();
        for (;;) {
          const { done, value } = await reader.read();
          if (done || closed) {
            break;
          }
          const texts = parser.push(decoder.decode(value, { stream: true }));
          for (const text of texts) {
            try {
              emit(JSON.parse(text) as unknown);
            } catch {
              console.error(`${LOG} skipped a stream event that was not valid JSON`);
            }
          }
        }
      } catch (error) {
        if (!closed) {
          onError(error);
        }
      } finally {
        reader = null;
        if (!closed) {
          timer = setTimeout(() => {
            void connect();
          }, reconnectMs);
        }
      }
    };

    void connect();
    return {
      close(): void {
        closed = true;
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
        void reader?.cancel().catch(() => undefined);
      },
    };
  };
}

// ---------------------------------------------------------------------------
// Listener: plan on receipt, write only on explicit approval
// ---------------------------------------------------------------------------

export interface Mw10ListenerOptions {
  reader: DubDelayLiveReader;
  /** Bridge to the Remote Script writer. Only used by approvePending(). */
  bridge?: BridgeCall;
  /** Stream source. Defaults to the fetch SSE source at `url`. */
  source?: Mw10PayloadSource;
  url?: string;
  fetchImpl?: SseFetch;
  reconnectMs?: number;
  onPlan?: (planned: Extract<Mw10HandleResult, { kind: "planned" }>) => void;
  /** Progress display hook: called with every payload, before planning. */
  onProgress?: Mw10ProgressHandler;
}

export interface Mw10Listener {
  close(): void;
  /** The cue currently held for approval, if any. */
  pendingCue(): DubDelayCue | null;
  /**
   * The explicit approval step: write the pending cue's plan to Live and
   * return the read-back-verified result. Throws when nothing is pending
   * or no bridge was configured.
   */
  approvePending(): Promise<GenerateDubDelayResult>;
}

export function listenToMw10PipelineStream(options: Mw10ListenerOptions): Mw10Listener {
  const url = options.url ?? DEFAULT_MW10_STREAM_URL;
  const source =
    options.source ??
    createFetchSseSource({
      url,
      ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {}),
      ...(options.reconnectMs !== undefined ? { reconnectMs: options.reconnectMs } : {}),
    });
  console.log(`${LOG} connecting to pipeline stream: ${url}`);

  let pending: DubDelayCue | null = null;
  const handle = source(
    (payload) => {
      if (options.onProgress && isRecord(payload) && typeof payload.status === "string") {
        try {
          options.onProgress(payload as unknown as Mw10PipelinePayload);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          console.error(`${LOG} progress handler failed (continuing): ${message}`);
        }
      }
      void (async () => {
        try {
          const result = await handleMw10PipelinePayload(payload, { reader: options.reader });
          if (result.kind === "planned") {
            pending = result.cue;
            options.onPlan?.(result);
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          console.error(`${LOG} failed to plan a received cue: ${message}`);
        }
      })();
    },
    (error) => {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`${LOG} SSE connection error (will reconnect): ${message}`);
    },
  );

  return {
    close(): void {
      handle.close();
      console.log(`${LOG} stream listener closed`);
    },
    pendingCue(): DubDelayCue | null {
      return pending;
    },
    async approvePending(): Promise<GenerateDubDelayResult> {
      if (!pending) {
        throw new Error("no automation cue is pending approval");
      }
      if (!options.bridge) {
        throw new Error("cannot approve: no bridge was configured for this listener");
      }
      const cue = pending;
      const result = await generateDubDelayAutomationFromCue(cue, {
        reader: options.reader,
        bridge: options.bridge,
        approved: true,
      });
      pending = null;
      console.log(`${LOG} pending cue approved and written (${result.status})`);
      return result;
    },
  };
}
