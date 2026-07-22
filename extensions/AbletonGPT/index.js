#!/usr/bin/env node
// Entry point for the AbletonGPT Extensions companion.
//
// Reads localhost/token config from the environment (shared with the Python bridge),
// selects a Live provider, and starts the protocol server. The default provider is the
// in-memory mock, so `node index.js` runs without the Extensions SDK for wiring tests.
// Set ABLETONGPT_EXTENSIONS_PROVIDER=sdk once SdkLiveProvider is implemented in Live.

import { MockLiveProvider, SdkLiveProvider } from "./src/liveProvider.js";
import { startServer } from "./src/server.js";

function config() {
  const env = process.env;
  return {
    host: env.ABLETONGPT_EXTENSIONS_HOST || "127.0.0.1",
    port: Number(env.ABLETONGPT_EXTENSIONS_PORT || 9878),
    token: env.ABLETONGPT_EXTENSIONS_TOKEN || env.ABLETONGPT_TOKEN || "",
    provider: (env.ABLETONGPT_EXTENSIONS_PROVIDER || "mock").toLowerCase(),
  };
}

function makeProvider(name) {
  if (name === "sdk") {
    // The SDK handle is provided by the Extensions runtime inside Live; wire it here.
    return new SdkLiveProvider(globalThis.abletonExtensionsSdk);
  }
  return new MockLiveProvider();
}

async function main() {
  const { host, port, token, provider } = config();
  const server = await startServer(makeProvider(provider), { host, port, token });
  const address = server.address();
  const where = typeof address === "object" && address ? `${address.address}:${address.port}` : `${host}:${port}`;
  process.stderr.write(
    `AbletonGPT Extension companion listening on ${where} (provider: ${provider}, token: ${token ? "set" : "none"})\n`,
  );
  if (!token) {
    process.stderr.write("warning: no shared token configured; accepting any request on loopback\n");
  }
}

main().catch((error) => {
  process.stderr.write(`AbletonGPT Extension companion failed to start: ${error.message}\n`);
  process.exitCode = 1;
});
