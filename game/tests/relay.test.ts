/* The relay is a dumb forwarder: no storage, no persistence across sockets. */

import { afterAll, beforeAll, expect, test } from "bun:test";
import path from "node:path";

const PORT = 8124;
const BASE = `http://127.0.0.1:${PORT}`;
let relay: ReturnType<typeof Bun.spawn>;

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      if ((await fetch(`${BASE}/health`)).ok) return;
    } catch {
      /* not up yet */
    }
    await Bun.sleep(100);
  }
  throw new Error("relay did not start");
}

/* Polling an external process: real time is the only available signal. */
async function waitFor(predicate: () => boolean, label: string, timeout = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return;
    await Bun.sleep(20);
  }
  throw new Error(`timed out waiting for ${label}`);
}

function open(code: string, role: "host" | "display") {
  const socket = new WebSocket(`ws://127.0.0.1:${PORT}/ws?code=${code}&role=${role}`);
  const inbox: unknown[] = [];
  socket.addEventListener("message", (event) => inbox.push(JSON.parse(String(event.data))));
  return { socket, inbox };
}

beforeAll(async () => {
  relay = Bun.spawn(["bun", "run", "relay/index.ts"], {
    cwd: path.join(import.meta.dir, ".."),
    env: { ...process.env, PORT: String(PORT) },
    stdout: "ignore",
    stderr: "inherit",
  });
  await waitForServer();
});

afterAll(() => {
  relay?.kill();
});

test("forwards messages inside a room only", async () => {
  const host = open("ABCD", "host");
  const display = open("ABCD", "display");
  const outsider = open("WXYZ", "display");

  await waitFor(
    () =>
      host.socket.readyState === WebSocket.OPEN &&
      display.socket.readyState === WebSocket.OPEN &&
      outsider.socket.readyState === WebSocket.OPEN,
    "sockets open",
  );

  host.socket.send(
    JSON.stringify({
      type: "snapshot",
      code: "ABCD",
      revision: 3,
      payload: { phase: "QUESTION_ACTIVE" },
    }),
  );

  await waitFor(() => display.inbox.length === 1, "snapshot delivered");
  expect(display.inbox[0]).toMatchObject({ revision: 3, code: "ABCD" });

  display.socket.send(JSON.stringify({ type: "hello", code: "ABCD", displayId: "d1" }));
  await waitFor(() => host.inbox.length === 1, "hello delivered");
  expect(host.inbox[0]).toMatchObject({ type: "hello", displayId: "d1" });

  // Negative assertion: give the outsider a bounded window to receive anything.
  await Bun.sleep(150);
  expect(outsider.inbox).toHaveLength(0);

  host.socket.close();
  display.socket.close();
  outsider.socket.close();
});

test("keeps nothing: a late display gets no replay", async () => {
  const early = open("EFGH", "host");
  await waitFor(() => early.socket.readyState === WebSocket.OPEN, "early open");
  early.socket.send(
    JSON.stringify({ type: "snapshot", code: "EFGH", revision: 1, payload: { phase: "LOBBY" } }),
  );
  early.socket.close();
  await waitFor(() => early.socket.readyState === WebSocket.CLOSED, "early closed");

  const late = open("EFGH", "display");
  await waitFor(() => late.socket.readyState === WebSocket.OPEN, "late open");
  late.socket.send(JSON.stringify({ type: "hello", code: "EFGH", displayId: "late" }));

  await Bun.sleep(150);
  expect(late.inbox).toHaveLength(0);
  late.socket.close();
});

test("ignores malformed and mismatched messages", async () => {
  const host = open("IJKL", "host");
  const display = open("IJKL", "display");
  await waitFor(
    () => host.socket.readyState === WebSocket.OPEN && display.socket.readyState === WebSocket.OPEN,
    "sockets open",
  );

  host.socket.send("not json");
  host.socket.send(JSON.stringify({ type: "snapshot", code: "ZZZZ", revision: 1 }));
  host.socket.send(JSON.stringify({ type: "unknown", code: "IJKL" }));
  await Bun.sleep(150);
  expect(display.inbox).toHaveLength(0);

  host.socket.send(JSON.stringify({ type: "presence", code: "IJKL" }));
  await waitFor(() => display.inbox.length === 1, "valid message forwarded");
  host.socket.close();
  display.socket.close();
});
