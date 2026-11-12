/* Stateless Game Night relay.
   Rooms live in memory only: no database, no files, no logs of session data.
   It forwards the same JSON messages the BroadcastChannel uses, so both
   transports stay interchangeable. Deploy separately from GitHub Pages. */

interface SocketData {
  code: string;
  role: "host" | "display";
}

const PORT = Number(process.env.PORT ?? 8092);
const MAX_MESSAGE_BYTES = 200_000;

const rooms = new Map<string, Set<Bun.ServerWebSocket<SocketData>>>();

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

const server = Bun.serve<SocketData>({
  port: PORT,
  fetch(req, srv) {
    const url = new URL(req.url);

    if (url.pathname === "/health") {
      return json({ ok: true, rooms: rooms.size });
    }

    if (url.pathname !== "/ws") return json({ error: "not found" }, 404);

    const code = (url.searchParams.get("code") ?? "").toUpperCase();
    const role = url.searchParams.get("role") === "host" ? "host" : "display";
    if (!/^[A-Z0-9]{4}$/.test(code)) return json({ error: "bad code" }, 400);

    if (srv.upgrade(req, { data: { code, role } })) return undefined;
    return json({ error: "upgrade failed" }, 400);
  },
  websocket: {
    open(socket) {
      const { code } = socket.data;
      let room = rooms.get(code);
      if (!room) {
        room = new Set();
        rooms.set(code, room);
      }
      room.add(socket);
    },
    message(socket, raw) {
      if (typeof raw !== "string" || raw.length > MAX_MESSAGE_BYTES) return;

      let message: { type?: unknown; code?: unknown };
      try {
        message = JSON.parse(raw);
      } catch {
        return;
      }
      const allowed = ["snapshot", "hello", "presence", "ended"];
      if (typeof message.type !== "string" || !allowed.includes(message.type)) return;
      if (typeof message.code !== "string") return;
      if (message.code.toUpperCase() !== socket.data.code) return;

      const room = rooms.get(socket.data.code);
      if (!room) return;
      for (const peer of room) {
        if (peer !== socket && peer.readyState === 1) peer.send(raw);
      }
    },
    close(socket) {
      const room = rooms.get(socket.data.code);
      if (!room) return;
      room.delete(socket);
      if (room.size === 0) rooms.delete(socket.data.code);
    },
  },
});

console.log(`Game Night relay on ws://127.0.0.1:${server.port}/ws`);
