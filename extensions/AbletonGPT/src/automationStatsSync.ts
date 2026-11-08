// Automation stats sync: aggregate a recorded ride and POST it to the
// MW10 gateway's /api/automation-log, which files it into the Obsidian
// session note (see 16_MW10ゲートウェイ/automation_log.py + app.py -- the
// payload field names below match that endpoint's model exactly).
//
// Corrections to the draft this is based on:
// - Duration was endTime - startTime taken from the FIRST and LAST array
//   elements, i.e. it silently assumed the points arrive sorted by time.
//   Aggregation here is order-independent (min/max over all times).
// - Math.min(...values) spreads the whole array as call arguments; a long
//   live recording (tens of thousands of CC samples) can exceed the
//   argument limit and throw. Aggregation is a single pass instead.
// - The endpoint is the not-yet-running gateway daemon, so the URL and
//   fetch are injectable, the gateway's optional X-Token is supported,
//   and the result is returned (not just logged) so a caller can tell
//   "synced" apart from "the daemon is not up yet".

export interface AutomationStatsPayload {
  session_id: string;
  track_name: string;
  parameter_name: string;
  total_events: number;
  duration_beats: number;
  min_value: number;
  max_value: number;
}

export interface RecordedPoint {
  time: number;
  value: number;
}

// Pure aggregation: one pass, no ordering assumption, no spread.
// Values are whatever unit the points carry -- for knobRecorder samples
// that is the normalized 0.0-1.0 knob position.
export function computeAutomationStats(
  sessionId: string,
  trackName: string,
  paramName: string,
  recordedPoints: RecordedPoint[],
): AutomationStatsPayload {
  if (recordedPoints.length === 0) {
    throw new Error("recordedPoints must not be empty");
  }
  let minTime = Number.POSITIVE_INFINITY;
  let maxTime = Number.NEGATIVE_INFINITY;
  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;
  for (const point of recordedPoints) {
    if (!Number.isFinite(point.time) || !Number.isFinite(point.value)) {
      throw new Error("recorded points must have finite time and value");
    }
    if (point.time < minTime) minTime = point.time;
    if (point.time > maxTime) maxTime = point.time;
    if (point.value < minValue) minValue = point.value;
    if (point.value > maxValue) maxValue = point.value;
  }
  return {
    session_id: sessionId,
    track_name: trackName,
    parameter_name: paramName,
    total_events: recordedPoints.length,
    duration_beats: Math.max(0, maxTime - minTime),
    min_value: minValue,
    max_value: maxValue,
  };
}

export interface StatsSyncOptions {
  /** Gateway endpoint. Default http://127.0.0.1:8000/api/automation-log. */
  endpoint?: string;
  /** Shared token, sent as X-Token when the gateway requires one. */
  token?: string;
  fetchImpl?: typeof fetch;
}

export type StatsSyncResult =
  | { sent: true; payload: AutomationStatsPayload; response: unknown }
  | { sent: false; reason: string; payload?: AutomationStatsPayload; status?: number };

const LOG = "[APC40 Stats]";
export const DEFAULT_AUTOMATION_LOG_URL = "http://127.0.0.1:8000/api/automation-log";

export async function sendApc40AutomationStatsToObsidian(
  sessionId: string,
  trackName: string,
  paramName: string,
  recordedPoints: RecordedPoint[],
  options: StatsSyncOptions = {},
): Promise<StatsSyncResult> {
  if (!recordedPoints || recordedPoints.length === 0) {
    console.warn(`${LOG} no recorded automation points to sync`);
    return { sent: false, reason: "no recorded points" };
  }
  const payload = computeAutomationStats(sessionId, trackName, paramName, recordedPoints);
  const endpoint = options.endpoint ?? DEFAULT_AUTOMATION_LOG_URL;
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  console.log(`${LOG} sending live performance automation metrics to ${endpoint}`, payload);
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
    console.log(`${LOG} Obsidian note updated with live performance history`, result);
    return { sent: true, payload, response: result };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`${LOG} failed to sync automation stats: ${message}`);
    return { sent: false, reason: message, payload };
  }
}
