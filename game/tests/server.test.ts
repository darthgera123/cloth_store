/* End-to-end: real HTTP + WebSocket against a spawned server process.
   Proves host authority, public/private separation, idempotent actions,
   undo, persistence across reconnect and host token enforcement. */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const PORT = 8123;
const BASE = `http://127.0.0.1:${PORT}`;
const tmp = mkdtempSync(path.join(tmpdir(), "game-night-"));

let server: ReturnType<typeof Bun.spawn>;

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const res = await fetch(`${BASE}/api/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await Bun.sleep(100);
  }
  throw new Error("server did not start");
}

/* Polling an external process: real time is the only available signal here. */
async function waitFor(predicate: () => boolean, label: string, timeout = 4000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return;
    await Bun.sleep(20);
  }
  throw new Error(`timed out waiting for ${label}`);
}

beforeAll(async () => {
  server = Bun.spawn(["bun", "run", "src/server/index.ts"], {
    cwd: path.join(import.meta.dir, ".."),
    env: {
      ...process.env,
      PORT: String(PORT),
      DB_PATH: path.join(tmp, "sessions.db"),
      QUESTIONS_DIR: path.join(import.meta.dir, "../questions"),
    },
    stdout: "ignore",
    stderr: "inherit",
  });
  await waitForServer();
});

afterAll(() => {
  server?.kill();
  rmSync(tmp, { recursive: true, force: true });
});

interface Answer {
  id: string;
  text: string | null;
  points: number | null;
  revealed: boolean;
}

interface HostPayload {
  session: {
    phase: string;
    code: string;
    feud: { revealed: string[]; pot: number; strikes: number } | null;
    scores: { teams: Record<string, number> };
  };
  questions: { id: string; answers?: Answer[] }[];
  canUndo: boolean;
}

interface DisplayPayload {
  phase: string;
  code: string;
  question: { answers?: Answer[] } | null;
}

interface Wire {
  type: string;
  payload?: HostPayload | DisplayPayload;
  error?: string;
}

function openSocket(code: string, token?: string) {
  const url = `ws://127.0.0.1:${PORT}/ws?code=${code}${token ? `&token=${token}` : ""}`;
  const socket = new WebSocket(url);
  const inbox: Wire[] = [];
  socket.addEventListener("message", (event) => inbox.push(JSON.parse(String(event.data))));
  return { socket, inbox };
}

const hostState = (inbox: Wire[]) => inbox.at(-1)?.payload as HostPayload | undefined;
const displayState = (inbox: Wire[]) => inbox.at(-1)?.payload as DisplayPayload | undefined;

describe("server", () => {
  test("creates a session, hides answers publicly and enforces the host token", async () => {
    const create = await fetch(`${BASE}/api/sessions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ names: ["Asha", "Ravi", "Meera", "Vikram"], teams: ["A", "B"] }),
    });
    expect(create.status).toBe(201);
    const { code, hostToken } = (await create.json()) as { code: string; hostToken: string };
    expect(code).toMatch(/^[A-Z0-9]{4}$/);

    expect((await fetch(`${BASE}/api/sessions/${code}/host`)).status).toBe(401);
    expect((await fetch(`${BASE}/api/sessions/${code}/host?token=nope`)).status).toBe(401);

    const { socket: host, inbox: hostInbox } = openSocket(code, hostToken);
    const { socket: display, inbox: displayInbox } = openSocket(code);
    await waitFor(() => hostInbox.length > 0 && displayInbox.length > 0, "initial states");

    const send = (action: object, actionId = crypto.randomUUID()) =>
      host.send(JSON.stringify({ actionId, action }));

    send({ type: "select_game", game: "family_feud" });
    await waitFor(() => hostState(hostInbox)?.session.phase === "GAME_INTRO", "game intro");

    send({ type: "start_round" });
    await waitFor(() => hostState(hostInbox)?.session.phase === "QUESTION_ACTIVE", "round start");
    await waitFor(() => displayState(displayInbox)?.phase === "QUESTION_ACTIVE", "display round");

    const hostView = hostState(hostInbox)!;
    const displayView = displayState(displayInbox)!;
    const answers = hostView.questions[0]?.answers ?? [];
    expect(answers.length).toBeGreaterThan(0);
    expect(displayView.question?.answers?.every((answer) => answer.text === null)).toBe(true);
    expect(JSON.stringify(displayView)).not.toContain(answers[0]!.text!);

    // duplicate action ids must not double-score; a later action proves the queue drained
    const envelope = JSON.stringify({
      actionId: "fixed-id-1",
      action: { type: "feud_reveal", answerId: answers[0]!.id },
    });
    host.send(envelope);
    host.send(envelope);
    send({ type: "feud_strike", delta: 1 });
    await waitFor(() => hostState(hostInbox)?.session.feud?.strikes === 1, "strike applied");

    const afterReveal = hostState(hostInbox)!;
    expect(afterReveal.session.feud?.revealed).toEqual([answers[0]!.id]);
    expect(afterReveal.session.feud?.pot).toBe(answers[0]!.points ?? 0);

    // undo walks back both accepted actions
    host.send(JSON.stringify({ type: "undo" }));
    host.send(JSON.stringify({ type: "undo" }));
    await waitFor(() => hostState(hostInbox)?.session.feud?.pot === 0, "undo");

    const afterUndo = hostState(hostInbox)!;
    expect(afterUndo.session.feud?.revealed).toEqual([]);

    // the display cannot drive the game
    display.send(JSON.stringify({ actionId: "x", action: { type: "reveal" } }));
    await waitFor(
      () => displayInbox.some((message) => message.type === "error"),
      "display rejection",
    );

    // state survives a reconnect
    host.close();
    display.close();
    await waitFor(() => host.readyState === WebSocket.CLOSED, "host close");
    const fresh = (await (await fetch(`${BASE}/api/sessions/${code}`)).json()) as {
      phase: string;
      code: string;
    };
    expect(fresh.phase).toBe("QUESTION_ACTIVE");
    expect(fresh.code).toBe(code);
  });

  test("unknown sessions 404 and stale actions are rejected", async () => {
    expect((await fetch(`${BASE}/api/sessions/ZZZZ`)).status).toBe(404);

    const create = await fetch(`${BASE}/api/sessions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ names: ["A", "B"] }),
    });
    const { code, hostToken } = (await create.json()) as { code: string; hostToken: string };

    const stale = await fetch(`${BASE}/api/sessions/${code}/actions`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-host-token": hostToken },
      body: JSON.stringify({ actionId: "a1", action: { type: "reveal" } }),
    });
    const body = (await stale.json()) as { ok: boolean; error?: string };
    expect(body.ok).toBe(false);
    expect(body.error).toContain("not allowed");
  });
});
