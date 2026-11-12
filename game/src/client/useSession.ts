import { useCallback, useEffect, useRef, useState } from "react";
import type { Action, HostState, PublicState } from "../lib/types";

const HOST_KEY = "gn:host";
const CODE_KEY = "gn:code";

export type Role = "host" | "display";

interface HostCreds {
  code: string;
  token: string;
}

export interface SessionApi {
  role: Role;
  code: string | null;
  publicState: PublicState | null;
  hostState: HostState | null;
  connected: boolean;
  ready: boolean;
  error: string | null;
  createSession(input: {
    names: string[];
    teams: [string, string] | null;
    config?: Record<string, unknown>;
  }): Promise<boolean>;
  join(code: string): void;
  send(action: Action): void;
  undo(): void;
  forget(): void;
  clearError(): void;
}

function readHostCreds(): HostCreds | null {
  try {
    const raw = localStorage.getItem(HOST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as HostCreds;
    return parsed.code && parsed.token ? parsed : null;
  } catch {
    return null;
  }
}

function readStoredCode(): string | null {
  try {
    return localStorage.getItem(CODE_KEY);
  } catch {
    return null;
  }
}

export function useSession(role: Role): SessionApi {
  const hostCreds = useRef<HostCreds | null>(role === "host" ? readHostCreds() : null);
  const urlCode =
    role === "display" ? new URLSearchParams(window.location.search).get("code") : null;

  const [code, setCode] = useState<string | null>(() =>
    role === "host" ? (hostCreds.current?.code ?? null) : (urlCode?.toUpperCase() ?? readStoredCode()),
  );
  const [token, setToken] = useState<string | null>(hostCreds.current?.token ?? null);
  const [publicState, setPublicState] = useState<PublicState | null>(null);
  const [hostState, setHostState] = useState<HostState | null>(null);
  const [connected, setConnected] = useState(false);
  const [ready, setReady] = useState(role === "host" ? !code : !code);
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!code) {
      setReady(true);
      return;
    }

    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;

    const teardown = () => {
      if (retryTimer) window.clearTimeout(retryTimer);
      socket?.close();
      socket = null;
    };

    const connect = () => {
      if (cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const params = new URLSearchParams({ code });
      if (token) params.set("token", token);
      socket = new WebSocket(`${proto}://${window.location.host}/ws?${params.toString()}`);
      socketRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        let message: { type?: string; payload?: unknown; error?: string };
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (message.type === "state") {
          if (role === "host") setHostState(message.payload as HostState);
          else setPublicState(message.payload as PublicState);
          setReady(true);
          setError(null);
        } else if (message.type === "error") {
          setError(message.error ?? "Something went wrong");
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        const delay = Math.min(5000, 400 * 2 ** attempt);
        attempt += 1;
        retryTimer = window.setTimeout(connect, delay);
      };
    };

    const boot = async () => {
      const res = await fetch(`/api/sessions/${code}`);
      if (cancelled) return;
      if (!res.ok) {
        setReady(true);
        setError(
          res.status === 404 ? `No session ${code}. Check the code on the host screen.` : "Server error",
        );
        return;
      }

      if (role === "host") {
        const hostRes = await fetch(`/api/sessions/${code}/host?token=${encodeURIComponent(token ?? "")}`);
        if (cancelled) return;
        if (!hostRes.ok) {
          localStorage.removeItem(HOST_KEY);
          hostCreds.current = null;
          setToken(null);
          setHostState(null);
          setReady(true);
          setError("This device no longer has host access. Create a new session.");
          return;
        }
        setHostState((await hostRes.json()) as HostState);
      } else {
        setPublicState((await res.json()) as PublicState);
      }

      setReady(true);
      connect();
    };

    void boot();

    const onVisible = () => {
      if (document.visibilityState === "visible" && socket?.readyState !== WebSocket.OPEN) {
        attempt = 0;
        teardown();
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      teardown();
    };
  }, [code, token, role]);

  const send = useCallback((action: Action) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError("Not connected to the host server");
      return;
    }
    socket.send(JSON.stringify({ actionId: crypto.randomUUID(), action }));
  }, []);

  const undo = useCallback(() => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError("Not connected to the host server");
      return;
    }
    socket.send(JSON.stringify({ type: "undo" }));
  }, []);

  const createSession = useCallback(
    async (input: {
      names: string[];
      teams: [string, string] | null;
      config?: Record<string, unknown>;
    }) => {
      try {
        const res = await fetch("/api/sessions", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(input),
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as { error?: string };
          setError(body.error ?? "Could not create the session");
          return false;
        }
        const data = (await res.json()) as { code: string; hostToken: string };
        localStorage.setItem(HOST_KEY, JSON.stringify({ code: data.code, token: data.hostToken }));
        localStorage.setItem(CODE_KEY, data.code);
        hostCreds.current = { code: data.code, token: data.hostToken };
        setToken(data.hostToken);
        setCode(data.code);
        setReady(false);
        return true;
      } catch {
        setError("Could not reach the server");
        return false;
      }
    },
    [],
  );

  const join = useCallback((nextCode: string) => {
    const normalized = nextCode.trim().toUpperCase();
    if (!normalized) return;
    localStorage.setItem(CODE_KEY, normalized);
    const url = new URL(window.location.href);
    url.searchParams.set("code", normalized);
    window.history.replaceState(null, "", url);
    setCode(normalized);
    setReady(false);
  }, []);

  const forget = useCallback(() => {
    localStorage.removeItem(HOST_KEY);
    hostCreds.current = null;
    setHostState(null);
    setCode(null);
    setToken(null);
    setPublicState(null);
    setReady(true);
    setError(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    role,
    code,
    publicState,
    hostState,
    connected,
    ready,
    error,
    createSession,
    join,
    send,
    undo,
    forget,
    clearError,
  };
}
