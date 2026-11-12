/* Audience transport. Reads snapshots only; keeps nothing on disk except the
   last code used, and never requests or receives private host data. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PublicState } from "../lib/types";
import {
  createDisplayLink,
  type DisplayLinkStatus,
  type SnapshotMessage,
} from "../transport/link";

const CODE_KEY = "gn:last-code";
const HOST_TIMEOUT_MS = 7000;
const SESSION_LOST_MS = 20000;

export interface DisplaySessionApi {
  code: string | null;
  publicState: PublicState | null;
  hostOnline: boolean;
  ended: boolean;
  link: DisplayLinkStatus;
  error: string | null;
  join(code: string): void;
  leave(): void;
  retry(): void;
}

function codeFromLocation(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  const hashQuery = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const fromHash = new URLSearchParams(hashQuery).get("code");
  const fromQuery = new URLSearchParams(window.location.search).get("code");
  const code = fromQuery ?? fromHash;
  if (code) return code.trim().toUpperCase();
  try {
    return sessionStorage.getItem(CODE_KEY);
  } catch {
    return null;
  }
}

export function useDisplaySession(): DisplaySessionApi {
  const [code, setCode] = useState<string | null>(() => codeFromLocation());
  const [publicState, setPublicState] = useState<PublicState | null>(null);
  const [hostOnline, setHostOnline] = useState(false);
  const [ended, setEnded] = useState(false);
  const [link, setLink] = useState<DisplayLinkStatus>({
    sameDevice: false,
    relay: "off",
    relayConfigured: false,
  });

  const revisionRef = useRef(0);
  const lastSeenRef = useRef(0);
  const startedRef = useRef(Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    revisionRef.current = 0;
    lastSeenRef.current = 0;
    startedRef.current = Date.now();
    setHostOnline(false);
    setEnded(false);

    const link = createDisplayLink({
      code,
      displayId: crypto.randomUUID(),
      onSnapshot: (message: SnapshotMessage) => {
        if (message.revision <= revisionRef.current) return;
        revisionRef.current = message.revision;
        lastSeenRef.current = Date.now();
        setPublicState(message.payload);
        setHostOnline(true);
        setEnded(false);
        setError(null);
      },
      onPresence: () => {
        lastSeenRef.current = Date.now();
        setHostOnline(true);
      },
      onEnded: () => setEnded(true),
      onStatus: setLink,
    });

    const watch = window.setInterval(() => {
      const now = Date.now();
      if (lastSeenRef.current > 0) {
        if (now - lastSeenRef.current > HOST_TIMEOUT_MS) setHostOnline(false);
        if (now - lastSeenRef.current > SESSION_LOST_MS) setEnded(true);
      } else if (now - startedRef.current > SESSION_LOST_MS) {
        setEnded(true);
      }
    }, 1000);

    return () => {
      window.clearInterval(watch);
      link.close();
    };
  }, [code]);

  const join = useCallback((nextCode: string) => {
    const normalized = nextCode.trim().toUpperCase();
    if (normalized.length < 4) return;
    try {
      sessionStorage.setItem(CODE_KEY, normalized);
    } catch {
      /* storage disabled */
    }
    // Path routes keep the code in the query string; the hash fallback covers
    // the root URL.
    if (/\/display\/?$/.test(window.location.pathname)) {
      const url = new URL(window.location.href);
      url.searchParams.set("code", normalized);
      window.history.replaceState(null, "", url);
    } else {
      window.location.hash = `#/display?code=${normalized}`;
    }
    setPublicState(null);
    setError(null);
    setCode(normalized);
  }, []);

  const leave = useCallback(() => {
    try {
      sessionStorage.removeItem(CODE_KEY);
    } catch {
      /* storage disabled */
    }
    window.location.assign(`${import.meta.env.BASE_URL}display/`);
  }, []);

  const retry = useCallback(() => {
    setEnded(false);
    setHostOnline(false);
    revisionRef.current = 0;
    lastSeenRef.current = 0;
    startedRef.current = Date.now();
    setCode(null);
    window.setTimeout(() => setCode(code), 0);
  }, [code]);

  return {
    code,
    publicState,
    hostOnline,
    ended,
    link,
    error,
    join,
    leave,
    retry,
  };
}
