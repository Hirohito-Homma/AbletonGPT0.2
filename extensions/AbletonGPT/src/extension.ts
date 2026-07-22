// Ableton Extension entry point.
//
// Live's Extension Host calls `activate` with an ActivationContext. We initialize the SDK
// and start the same localhost protocol server used by the mock companion, backed by a
// real SdkLiveProvider. The Python side (ExtensionsBridge / the `extensions` backend) then
// talks to it exactly as it does to the mock — only the provider differs.

import { initialize, type ActivationContext } from "@ableton-extensions/sdk";

import { startServer } from "./server.js";
import { SdkLiveProvider } from "./sdkLiveProvider.js";

function readConfig(): { host: string; port: number; token: string } {
  const env = process.env;
  return {
    host: env.ABLETONGPT_EXTENSIONS_HOST ?? "127.0.0.1",
    port: Number(env.ABLETONGPT_EXTENSIONS_PORT ?? 9878),
    token: env.ABLETONGPT_EXTENSIONS_TOKEN ?? env.ABLETONGPT_TOKEN ?? "",
  };
}

export function activate(activation: ActivationContext): void {
  const context = initialize(activation, "1.0.0");
  const provider = new SdkLiveProvider(context);
  const { host, port, token } = readConfig();

  startServer(provider, { host, port, token })
    .then((server) => {
      const address = server.address();
      const where =
        typeof address === "object" && address ? `${address.address}:${address.port}` : `${host}:${port}`;
      console.log(`AbletonGPT Extension listening on ${where} (token: ${token ? "set" : "none"})`);
      if (!token) {
        console.warn("AbletonGPT Extension: no shared token configured; accepting any request on loopback");
      }
    })
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`AbletonGPT Extension failed to start its server: ${message}`);
    });
}
