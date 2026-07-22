// Types for the JavaScript transport (src/server.js), so the TypeScript extension entry
// can import it under `moduleResolution: nodenext` without enabling allowJs.

import type { Server } from "node:net";

export interface ServerOptions {
  host?: string;
  port?: number;
  token?: string;
}

export function createServer(provider: unknown, options?: { token?: string }): Server;
export function startServer(provider: unknown, options?: ServerOptions): Promise<Server>;
