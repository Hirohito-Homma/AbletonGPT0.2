// Localhost TCP server speaking the newline-delimited JSON protocol.
//
// One request line -> one response line -> close. Binds to loopback only. It never opens
// files, spawns processes, or evaluates request content; requests only select a fixed
// command via the Dispatcher.

import net from "node:net";

import { Dispatcher, errorResponse } from "./protocol.js";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);
const MAX_LINE_BYTES = 1_000_000;

export function createServer(provider, { token = "" } = {}) {
  const dispatcher = new Dispatcher(provider, { token });

  const server = net.createServer((socket) => {
    let buffer = "";
    let finished = false;

    const reply = async (line) => {
      if (finished) {
        return;
      }
      finished = true;
      let response;
      try {
        response = await dispatcher.handle(JSON.parse(line));
      } catch {
        response = errorResponse("malformed JSON request");
      }
      socket.end(JSON.stringify(response) + "\n");
    };

    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      buffer += chunk;
      if (Buffer.byteLength(buffer, "utf8") > MAX_LINE_BYTES) {
        if (!finished) {
          finished = true;
          socket.end(JSON.stringify(errorResponse("request too large")) + "\n");
        }
        return;
      }
      const newlineIndex = buffer.indexOf("\n");
      if (newlineIndex !== -1) {
        reply(buffer.slice(0, newlineIndex));
      }
    });
    socket.on("error", () => socket.destroy());
  });

  return server;
}

export function startServer(provider, { host = "127.0.0.1", port = 9878, token = "" } = {}) {
  if (!LOOPBACK_HOSTS.has(host)) {
    throw new Error("Ableton Extensions companion must bind to a loopback host");
  }
  const server = createServer(provider, { token });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve(server));
  });
}
