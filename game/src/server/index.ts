/* Game Night server: authoritative sessions, host/display websockets and the
   built client. Run with `bun run src/server/index.ts` (PORT, default 8091). */

import path from "node:path";
import { existsSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { z } from "zod";
import {
  type Action,
  type HostState,
  type PublicState,
  type Question,
  actionSchema,
  configSchema,
  defaultConfig,
} from "../lib/types";
import {
  EngineError,
  applyAction,
  createSession,
  projectPublic,
  questionsFor,
} from "./engine";
import { loadQuestionBank } from "./questions";
import { Store, type SessionRecord } from "./db";

const PORT = Number(process.env.PORT ?? 8091);
const ROOT = path.resolve(import.meta.dir, "../..");
const DIST = path.join(ROOT, "dist");
const QUESTIONS_DIR = process.env.QUESTIONS_DIR ?? path.join(ROOT, "questions");
const DB_PATH = process.env.DB_PATH ?? path.join(ROOT, ".data/sessions.db");

const bank = await loadQuestionBank(QUESTIONS_DIR);
const store = new Store(DB_PATH);
const cache = new Map<string, SessionRecord>();

const COUNTS = Object.fromEntries(
  Object.entries(bank).map(([game, list]) => [game, (list as Question[]).length]),
);
if (Object.values(COUNTS).some((count) => count === 0)) {
  console.warn("Question bank is missing a game:", COUNTS);
}

/* ---------- helpers ---------- */

function code4(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "";
  for (const byte of randomBytes(4)) out += alphabet[byte % alphabet.length];
  return out;
}

function newCode(): string {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const code = code4();
    if (!store.get(code)) return code;
  }
  throw new Error("Could not allocate a session code");
}

function load(code: string): SessionRecord | null {
  const cached = cache.get(code);
  if (cached) return cached;
  const record = store.get(code);
  if (record) cache.set(code, record);
  return record;
}

const ACTION_LABEL: Record<Action["type"], string> = {
  configure: "Setup changed",
  select_game: "Game selected",
  start_round: "Round started",
  begin_answering: "Answering started",
  reveal: "Answers revealed",
  round_result: "Round result shown",
  next_round: "Next round",
  end_game: "Game ended",
  back_to_lobby: "Back to lobby",
  set_paused: "Pause toggled",
  set_timer: "Timer set",
  clear_timer: "Timer cleared",
  edit_score: "Score edited",
  skip_question: "Question skipped",
  restart_round: "Round restarted",
  reset_session: "Session reset",
  feud_reveal: "Answer revealed",
  feud_strike: "Strike changed",
  feud_set_active: "Active team changed",
  feud_steal: "Steal resolved",
  feud_award: "Points awarded",
  herd_set_answer: "Answer recorded",
  herd_merge: "Answers grouped",
  herd_unmerge: "Group split",
  herd_set_pink_cow: "Pink Cow set",
  ml_set_votes: "Votes recorded",
  ml_clear_votes: "Votes cleared",
  pir_set_guess: "Guess recorded",
  pir_lock: "Guesses locked",
  pir_reveal_price: "Price revealed",
};

/* ---------- sockets ---------- */

interface SocketData {
  code: string;
  role: "host" | "display";
}

const socketsByCode = new Map<string, Set<Bun.ServerWebSocket<SocketData>>>();

function sockets(code: string): Set<Bun.ServerWebSocket<SocketData>> {
  let set = socketsByCode.get(code);
  if (!set) {
    set = new Set();
    socketsByCode.set(code, set);
  }
  return set;
}

function publicPayload(record: SessionRecord): PublicState {
  const hostConnected = [...sockets(record.state.code)].some(
    (socket) => socket.data.role === "host",
  );
  return projectPublic(record.state, bank, { hostConnected });
}

function hostPayload(record: SessionRecord): HostState {
  const game = record.state.game;
  return {
    session: record.state,
    questions: game ? questionsFor(bank, game) : [],
    canUndo: record.history.length > 0,
    undoLabel: record.history.at(-1)?.label ?? null,
    history: record.history
      .slice(-8)
      .reverse()
      .map((entry) => ({ label: entry.label, at: entry.at })),
  };
}

function broadcast(code: string): void {
  const record = load(code);
  if (!record) return;
  const pub = JSON.stringify({ type: "state", payload: publicPayload(record) });
  const host = JSON.stringify({ type: "state", payload: hostPayload(record) });
  for (const socket of sockets(code)) {
    if (socket.readyState !== 1) continue;
    socket.send(socket.data.role === "host" ? host : pub);
  }
}

/* ---------- mutations ---------- */

function commit(record: SessionRecord, state: typeof record.state): void {
  record.state = state;
  store.save(record, state.updatedAt);
  broadcast(state.code);
}

function undo(code: string): { ok: true } | { ok: false; error: string } {
  const record = load(code);
  if (!record) return { ok: false, error: "Session not found" };
  const snapshot = record.history.pop();
  if (!snapshot) return { ok: false, error: "Nothing to undo" };
  const restored = { ...snapshot.state, updatedAt: Date.now() };
  record.state = restored;
  store.save(record, restored.updatedAt);
  broadcast(code);
  return { ok: true };
}

function perform(
  code: string,
  envelope: { actionId: string; action: Action },
  now = Date.now(),
): { ok: true } | { ok: false; error: string } {
  const record = load(code);
  if (!record) return { ok: false, error: "Session not found" };

  let next;
  try {
    next = applyAction(record.state, envelope.action, bank, now);
  } catch (error) {
    if (error instanceof EngineError) return { ok: false, error: error.message };
    throw error;
  }

  if (!store.markAction(record.state.id, envelope.actionId, now)) {
    return { ok: true };
  }

  record.history.push({
    label: ACTION_LABEL[envelope.action.type] ?? envelope.action.type,
    at: now,
    state: structuredClone(record.state),
  });
  commit(record, next);
  return { ok: true };
}

/* ---------- http ---------- */

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

const createBody = z.object({
  names: z.array(z.string().trim().min(1).max(24)).min(2).max(8).optional(),
  teams: z.tuple([z.string().trim().min(1).max(24), z.string().trim().min(1).max(24)]).nullish(),
  config: configSchema.partial().optional(),
});

const actionBody = z.object({
  actionId: z.string().min(1).max(64),
  action: actionSchema,
});

function tokenFrom(req: Request): string | null {
  const header = req.headers.get("x-host-token");
  if (header) return header;
  const url = new URL(req.url);
  return url.searchParams.get("token");
}

function staticResponse(url: URL): Response {
  const pathname = decodeURIComponent(url.pathname);
  const target = path.join(DIST, pathname === "/" ? "index.html" : pathname);
  const resolved = path.resolve(target);
  if (resolved.startsWith(DIST) && existsSync(resolved) && !resolved.endsWith("/")) {
    const file = Bun.file(resolved);
    if (file.size > 0) return new Response(file);
  }
  const index = Bun.file(path.join(DIST, "index.html"));
  if (existsSync(path.join(DIST, "index.html"))) {
    return new Response(index, { headers: { "content-type": "text/html; charset=utf-8" } });
  }
  return new Response("Client not built. Run `bun run build`.", { status: 503 });
}

const server = Bun.serve<SocketData>({
  port: PORT,
  async fetch(req, srv) {
    const url = new URL(req.url);

    if (url.pathname === "/ws") {
      const code = (url.searchParams.get("code") ?? "").toUpperCase();
      const token = url.searchParams.get("token");
      const record = load(code);
      if (!record) return new Response("unknown session", { status: 404 });
      const role: SocketData["role"] =
        token && token === record.hostToken ? "host" : "display";
      if (token && role === "display") return new Response("invalid host token", { status: 403 });
      if (srv.upgrade(req, { data: { code, role } })) return undefined;
      return new Response("upgrade failed", { status: 400 });
    }

    if (url.pathname === "/api/health") {
      return json({ ok: true, games: COUNTS, uptime: process.uptime() });
    }

    if (url.pathname === "/api/sessions" && req.method === "POST") {
      const parsed = createBody.safeParse(await req.json().catch(() => ({})));
      if (!parsed.success) return json({ error: parsed.error.issues[0]?.message }, 400);

      const names = parsed.data.names ?? ["Player 1", "Player 2"];
      const code = newCode();
      const hostToken = randomBytes(24).toString("hex");
      const state = createSession(
        {
          names,
          teams: parsed.data.teams ?? null,
          config: { ...defaultConfig, ...(parsed.data.config ?? {}) },
        },
        code,
        Date.now(),
      );
      store.create(code, hostToken, state);
      cache.set(code, { state, history: [], hostToken });
      return json({ code, hostToken, state: publicPayload(cache.get(code)!) }, 201);
    }

    const sessionMatch = url.pathname.match(/^\/api\/sessions\/([A-Z0-9]+)(\/.*)?$/);
    if (sessionMatch) {
      const code = sessionMatch[1] ?? "";
      const rest = sessionMatch[2] ?? "";
      const record = load(code);
      if (!record) return json({ error: "Session not found" }, 404);

      if (rest === "" && req.method === "GET") {
        return json(publicPayload(record));
      }

      if (rest === "/host" && req.method === "GET") {
        const token = tokenFrom(req);
        if (!token || token !== record.hostToken) return json({ error: "Unauthorized" }, 401);
        return json(hostPayload(record));
      }

      if (rest === "/actions" && req.method === "POST") {
        const token = tokenFrom(req);
        if (!token || token !== record.hostToken) return json({ error: "Unauthorized" }, 401);
        const parsed = actionBody.safeParse(await req.json().catch(() => null));
        if (!parsed.success) return json({ error: parsed.error.issues[0]?.message }, 400);
        return json(perform(code, parsed.data));
      }

      if (rest === "/undo" && req.method === "POST") {
        const token = tokenFrom(req);
        if (!token || token !== record.hostToken) return json({ error: "Unauthorized" }, 401);
        return json(undo(code));
      }

      return json({ error: "Not found" }, 404);
    }

    if (req.method !== "GET" && req.method !== "HEAD") return json({ error: "Not found" }, 404);
    return staticResponse(url);
  },
  websocket: {
    open(socket) {
      const { code } = socket.data;
      sockets(code).add(socket);
      if (socket.data.role === "host") broadcast(code);
      else {
        const record = load(code);
        if (record) {
          socket.send(JSON.stringify({ type: "state", payload: publicPayload(record) }));
        }
      }
    },
    message(socket, raw) {
      const { code, role } = socket.data;
      if (role !== "host") {
        socket.send(JSON.stringify({ type: "error", error: "Host actions only" }));
        return;
      }
      let message: { type?: string; actionId?: string; action?: unknown };
      try {
        message = JSON.parse(String(raw));
      } catch {
        socket.send(JSON.stringify({ type: "error", error: "Malformed message" }));
        return;
      }

      if (message.type === "undo") {
        const result = undo(code);
        if (!result.ok) socket.send(JSON.stringify({ type: "error", error: result.error }));
        return;
      }

      const parsed = actionBody.safeParse(message);
      if (!parsed.success) {
        socket.send(
          JSON.stringify({ type: "error", error: parsed.error.issues[0]?.message ?? "Bad action" }),
        );
        return;
      }
      const result = perform(code, parsed.data);
      if (!result.ok) socket.send(JSON.stringify({ type: "error", error: result.error }));
    },
    close(socket) {
      const { code } = socket.data;
      const set = sockets(code);
      set.delete(socket);
      if (socket.data.role === "host") broadcast(code);
    },
  },
});

console.log(`Game Night server on http://127.0.0.1:${server.port}`);
console.log(
  `Questions: ${Object.entries(COUNTS)
    .map(([game, count]) => `${game}=${count}`)
    .join(" ")}`,
);
