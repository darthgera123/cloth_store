/* Client transport: one message shape over two stateless carriers.
   - BroadcastChannel for windows on the same device (Mode A).
   - WebSocket relay for the TV / another device (Mode B); the relay keeps
     rooms in memory only and stores nothing.
   The host is the only writer of game state. */

import type { PublicState } from "../lib/types";

export interface SnapshotMessage {
  type: "snapshot";
  code: string;
  revision: number;
  payload: PublicState;
}

export interface HelloMessage {
  type: "hello";
  code: string;
  displayId: string;
}

export interface PresenceMessage {
  type: "presence";
  code: string;
}

export interface EndedMessage {
  type: "ended";
  code: string;
}

export type GameMessage = SnapshotMessage | HelloMessage | PresenceMessage | EndedMessage;

export type LinkStatus = "off" | "connecting" | "online" | "error";

export interface HostLinkStatus {
  sameDevice: boolean;
  relay: LinkStatus;
  relayConfigured: boolean;
  displays: number;
}

export interface DisplayLinkStatus {
  sameDevice: boolean;
  relay: LinkStatus;
  relayConfigured: boolean;
}

/** ws(s):// origin for the relay, or null when the build has no relay. */
export function relayOrigin(): string | null {
  const raw = import.meta.env?.VITE_RELAY_URL?.trim();
  if (!raw) return null;
  const normalized = raw.replace(/^http/, "ws").replace(/\/+$/, "");
  try {
    const url = new URL(normalized);
    if (url.protocol === "https:") url.protocol = "wss:";
    if (url.protocol === "http:") url.protocol = "ws:";
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

const channelName = (code: string) => `game-night:${code.toUpperCase()}`;

function relaySocket(code: string, role: "host" | "display"): WebSocket | null {
  const origin = relayOrigin();
  if (!origin) return null;
  const url = `${origin}/ws?code=${encodeURIComponent(code)}&role=${role}`;
  try {
    return new WebSocket(url);
  } catch {
    return null;
  }
}

function parseMessage(raw: unknown): GameMessage | null {
  try {
    const data = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!data || typeof data !== "object") return null;
    const type = (data as { type?: unknown }).type;
    if (type !== "snapshot" && type !== "hello" && type !== "presence" && type !== "ended") {
      return null;
    }
    return data as GameMessage;
  } catch {
    return null;
  }
}

export interface HostLink {
  publish(payload: PublicState, revision: number): void;
  endSession(): void;
  close(): void;
}

export function createHostLink(options: {
  code: string;
  onHello: () => void;
  onStatus: (status: HostLinkStatus) => void;
}): HostLink {
  const code = options.code.toUpperCase();
  const seen = new Map<string, number>();
  let relay: LinkStatus = relayOrigin() ? "connecting" : "off";
  let relaySocketRef: WebSocket | null = null;
  let closed = false;
  let retry = 0;
  let retryTimer: number | undefined;
  let latest: { payload: PublicState; revision: number } | null = null;

  const channel =
    typeof BroadcastChannel === "function" ? new BroadcastChannel(channelName(code)) : null;

  const status = (): HostLinkStatus => {
    const cutoff = Date.now() - 10_000;
    for (const [id, at] of seen) if (at < cutoff) seen.delete(id);
    const result = {
      sameDevice: Boolean(channel),
      relay,
      relayConfigured: Boolean(relayOrigin()),
      displays: seen.size,
    };
    options.onStatus(result);
    return result;
  };

  const send = (message: GameMessage) => {
    if (closed) return;
    try {
      channel?.postMessage(message);
    } catch {
      /* channel closed */
    }
    if (relaySocketRef?.readyState === WebSocket.OPEN) {
      relaySocketRef.send(JSON.stringify(message));
    }
  };

  const handle = (message: GameMessage) => {
    if (message.code !== code) return;
    if (message.type === "hello") {
      seen.set(message.displayId, Date.now());
      options.onHello();
      status();
    }
  };

  if (channel) channel.onmessage = (event) => {
    const message = parseMessage(event.data);
    if (message) handle(message);
  };

  const connect = () => {
    if (closed) return;
    const socket = relaySocket(code, "host");
    if (!socket) {
      status();
      return;
    }
    relaySocketRef = socket;
    relay = "connecting";
    status();

    socket.onopen = () => {
      relay = "online";
      retry = 0;
      status();
      if (latest) socket.send(JSON.stringify({ ...latest, type: "snapshot", code }));
    };
    socket.onmessage = (event) => {
      const message = parseMessage(event.data);
      if (message) handle(message);
    };
    socket.onclose = () => {
      relaySocketRef = null;
      relay = "error";
      status();
      if (closed) return;
      const delay = Math.min(8000, 500 * 2 ** retry);
      retry += 1;
      retryTimer = window.setTimeout(connect, delay);
    };
    socket.onerror = () => {
      relay = "error";
      status();
    };
  };

  connect();

  const heartbeat = window.setInterval(() => {
    send({ type: "presence", code });
    status();
  }, 2500);
  send({ type: "presence", code });

  return {
    publish(payload, revision) {
      latest = { payload, revision };
      send({ type: "snapshot", code, revision, payload });
    },
    endSession() {
      send({ type: "ended", code });
      latest = null;
    },
    close() {
      closed = true;
      window.clearInterval(heartbeat);
      if (retryTimer) window.clearTimeout(retryTimer);
      channel?.close();
      relaySocketRef?.close();
      relaySocketRef = null;
    },
  };
}

export interface DisplayLink {
  requestSnapshot(): void;
  close(): void;
}

export function createDisplayLink(options: {
  code: string;
  displayId: string;
  onSnapshot: (message: SnapshotMessage) => void;
  onPresence: () => void;
  onEnded: () => void;
  onStatus: (status: DisplayLinkStatus) => void;
}): DisplayLink {
  const code = options.code.toUpperCase();
  let relay: LinkStatus = relayOrigin() ? "connecting" : "off";
  let socketRef: WebSocket | null = null;
  let closed = false;
  let retry = 0;
  let retryTimer: number | undefined;

  const channel =
    typeof BroadcastChannel === "function" ? new BroadcastChannel(channelName(code)) : null;

  const status = () =>
    options.onStatus({
      sameDevice: Boolean(channel),
      relay,
      relayConfigured: Boolean(relayOrigin()),
    });

  const send = (message: GameMessage) => {
    if (closed) return;
    try {
      channel?.postMessage(message);
    } catch {
      /* channel closed */
    }
    if (socketRef?.readyState === WebSocket.OPEN) socketRef.send(JSON.stringify(message));
  };

  const handle = (message: GameMessage) => {
    if (message.code !== code) return;
    if (message.type === "snapshot") options.onSnapshot(message);
    else if (message.type === "presence") options.onPresence();
    else if (message.type === "ended") options.onEnded();
  };

  if (channel) {
    channel.onmessage = (event) => {
      const message = parseMessage(event.data);
      if (message) handle(message);
    };
  }

  const connect = () => {
    if (closed) return;
    const socket = relaySocket(code, "display");
    if (!socket) {
      status();
      return;
    }
    socketRef = socket;
    relay = "connecting";
    status();

    socket.onopen = () => {
      relay = "online";
      retry = 0;
      status();
      socket.send(JSON.stringify({ type: "hello", code, displayId: options.displayId }));
    };
    socket.onmessage = (event) => {
      const message = parseMessage(event.data);
      if (message) handle(message);
    };
    socket.onclose = () => {
      socketRef = null;
      relay = "error";
      status();
      if (closed) return;
      const delay = Math.min(8000, 500 * 2 ** retry);
      retry += 1;
      retryTimer = window.setTimeout(connect, delay);
    };
  };

  connect();

  const hello = () => send({ type: "hello", code, displayId: options.displayId });
  hello();
  const helloInterval = window.setInterval(hello, 3000);
  status();

  return {
    requestSnapshot: hello,
    close() {
      closed = true;
      window.clearInterval(helloInterval);
      if (retryTimer) window.clearTimeout(retryTimer);
      channel?.close();
      socketRef?.close();
      socketRef = null;
    },
  };
}
