/* Audience transport. Reads snapshots only; keeps nothing on disk except the
   last code used, and never requests or receives private host data.

   Three carriers deliver the same public snapshot:
   - BroadcastChannel for windows on the same device,
   - the optional WebSocket relay,
   - Firebase Realtime Database for screens on other devices.
   The display accepts the highest revision it has seen. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PublicState } from "../lib/types";
import {
  createDisplayLink,
  type DisplayLinkStatus,
  type SnapshotMessage,
} from "../transport/link";
import { normalizePublicState, subscribeDisplayFeed } from "../multiplayer/displayFeed";

const CODE_KEY = "gn:last-code";
/** No heartbeat for this long: the host screen is probably gone. */
const HOST_TIMEOUT_MS = 15_000;
/** No heartbeat for this long: treat the session as expired. */
const SESSION_EXPIRED_MS = 10 * 60_000;

export interface DisplaySessionApi {
  code: string | null;
  publicState: PublicState | null;
  hostOnline: boolean;
  ended: boolean;
  invalid: boolean;
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
  const [invalid, setInvalid] = useState(false);
  const [link, setLink] = useState<DisplayLinkStatus>({
    sameDevice: false,
    relay: "off",
    relayConfigured: false,
  });

  const revisionRef = useRef(0);
  const lastSeenRef = useRef(0);
  const stateRef = useRef<PublicState | null>(null);
  stateRef.current = publicState;
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    revisionRef.current = 0;
    lastSeenRef.current = 0;
    setHostOnline(false);
    setEnded(false);
    setInvalid(false);

    const link = createDisplayLink({
      code,
      displayId: crypto.randomUUID(),
      onSnapshot: (message: SnapshotMessage) => {
        if (message.revision <= revisionRef.current) {
          lastSeenRef.current = Date.now();
          setHostOnline(true);
          return;
        }
        revisionRef.current = message.revision;
        lastSeenRef.current = Date.now();
        setPublicState(normalizePublicState(message.payload));
        setHostOnline(true);
        setEnded(false);
        setInvalid(false);
        setError(null);
      },
      onPresence: () => {
        lastSeenRef.current = Date.now();
        setHostOnline(true);
      },
      onEnded: () => {
        setHostOnline(false);
        setEnded(true);
      },
      onStatus: setLink,
    });

    const unsubscribeFeed = subscribeDisplayFeed(code, {
      onSeen: () => {
        lastSeenRef.current = Date.now();
        setHostOnline(true);
      },
      onState: (state, revision, freshAt) => {
        lastSeenRef.current = Date.now();
        setHostOnline(true);
        setInvalid(false);
        // A screen opened long after the evening: the stored heartbeat is old.
        if (freshAt > 0 && Date.now() - freshAt > SESSION_EXPIRED_MS) {
          setPublicState(normalizePublicState(state));
          setEnded(true);
          return;
        }
        // A fresh heartbeat revives a display that timed out while the host
        // was away, even before the next game action changes the revision.
        setEnded(false);
        if (revision <= revisionRef.current) return;
        revisionRef.current = revision;
        setPublicState(normalizePublicState(state));
        setEnded(false);
        setError(null);
      },
      onEnded: () => {
        setHostOnline(false);
        setEnded(true);
      },
      onWaiting: () => {
        if (!stateRef.current) {
          setInvalid(false);
          setEnded(false);
        }
      },
      onInvalid: () => {
        // Only call an unknown session invalid while nothing was ever shown;
        // a dropped connection keeps the last board and the offline banner.
        if (!stateRef.current) setInvalid(true);
      },
    });

    const watch = window.setInterval(() => {
      const now = Date.now();
      if (lastSeenRef.current === 0) return;
      if (now - lastSeenRef.current > HOST_TIMEOUT_MS) setHostOnline(false);
      if (now - lastSeenRef.current > SESSION_EXPIRED_MS) setEnded(true);
    }, 1000);

    return () => {
      window.clearInterval(watch);
      unsubscribeFeed();
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
    setInvalid(false);
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
    setInvalid(false);
    setHostOnline(false);
    setPublicState(null);
    revisionRef.current = 0;
    lastSeenRef.current = 0;
    setCode(null);
    window.setTimeout(() => setCode(code), 0);
  }, [code]);

  return {
    code,
    publicState,
    hostOnline,
    ended,
    invalid,
    link,
    error,
    join,
    leave,
    retry,
  };
}
