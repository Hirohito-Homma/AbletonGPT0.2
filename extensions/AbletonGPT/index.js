#!/usr/bin/env node
// Standalone MOCK companion for wiring tests.
//
// Runs the protocol server with the in-memory MockLiveProvider, so the whole wire
// contract can be exercised from the Python ExtensionsBridge without the Extensions SDK
// or a running Live. The real Live path runs inside Live's Extension Host from
// src/extension.ts (SdkLiveProvider), not from this file.

import { MockLiveProvider } from "./src/liveProvider.js";
import { startServer } from "./src/server.js";

function config() {
  const env = process.env;
  return {
    host: env.ABLETONGPT_EXTENSIONS_HOST || "127.0.0.1",
    port: Number(env.ABLETONGPT_EXTENSIONS_PORT || 9878),
    token: env.ABLETONGPT_EXTENSIONS_TOKEN || env.ABLETONGPT_TOKEN || "",
  };
}

async function main() {
  const { host, port, token } = config();
  const server = await startServer(new MockLiveProvider(), { host, port, token });
  const address = server.address();
  const where = typeof address === "object" && address ? `${address.address}:${address.port}` : `${host}:${port}`;
  process.stderr.write(
    `AbletonGPT mock companion listening on ${where} (token: ${token ? "set" : "none"})\n`,
  );
  if (!token) {
    process.stderr.write("warning: no shared token configured; accepting any request on loopback\n");
  }
}

main().catch((error) => {
  process.stderr.write(`AbletonGPT Extension companion failed to start: ${error.message}\n`);
  process.exitCode = 1;
});
