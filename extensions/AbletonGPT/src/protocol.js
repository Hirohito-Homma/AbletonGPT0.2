// Wire protocol for the AbletonGPT Extensions companion.
//
// One UTF-8 JSON object per line, in and out. Requests carry a fixed command name
// from an allowlist plus a shared token; the dispatcher verifies the token, looks the
// command up, and returns exactly one response object. It never evaluates arbitrary
// input -- params are only forwarded to typed provider methods.

import { timingSafeEqual } from "node:crypto";

export const PROTOCOL = "abletongpt.extensions.v1";

// Fixed command allowlist: command name -> handler(provider, params). No other command
// can reach Live. Keep this the single source of truth for what the companion exposes.
const COMMANDS = {
  ping: async () => ({ pong: true, protocol: PROTOCOL }),
  get_tempo: async (provider) => provider.getTempo(),
  get_tracks: async (provider) => provider.getTracks(),
  get_midi_clip_notes: async (provider, params) => provider.getMidiClipNotes(params),
  get_selected_context: async (provider) => provider.getSelectedContext(),
  create_midi_clip: async (provider, params) => provider.createMidiClip(params),
  apply_expression_to_clip: async (provider, params) => provider.applyExpressionToClip(params),
};

export function successResponse(result) {
  return { protocol: PROTOCOL, ok: true, result: result ?? null };
}

export function errorResponse(message) {
  return { protocol: PROTOCOL, ok: false, error: String(message) };
}

// Constant-time token comparison that tolerates differing lengths.
function tokensMatch(expected, provided) {
  const a = Buffer.from(String(expected), "utf8");
  const b = Buffer.from(String(provided ?? ""), "utf8");
  if (a.length !== b.length) {
    return false;
  }
  return timingSafeEqual(a, b);
}

export class Dispatcher {
  // `token` is the shared secret; an empty string disables the check (dev only).
  constructor(provider, { token = "" } = {}) {
    this.provider = provider;
    this.token = String(token);
  }

  async handle(request) {
    if (request === null || typeof request !== "object") {
      return errorResponse("malformed request");
    }
    if (request.protocol != null && request.protocol !== PROTOCOL) {
      return errorResponse("unsupported protocol version");
    }
    if (this.token && !tokensMatch(this.token, request.token)) {
      return errorResponse("unauthorized");
    }
    const handler = Object.prototype.hasOwnProperty.call(COMMANDS, request.command)
      ? COMMANDS[request.command]
      : null;
    if (!handler) {
      return errorResponse("unknown command");
    }
    try {
      const params = request.params && typeof request.params === "object" ? request.params : {};
      const result = await handler(this.provider, params);
      return successResponse(result);
    } catch (error) {
      return errorResponse(error?.message ?? error);
    }
  }
}

export const ALLOWED_COMMANDS = Object.freeze(Object.keys(COMMANDS));
