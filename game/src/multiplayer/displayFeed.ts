/* Cross-device audience sync over Firebase Realtime Database.

   The host publishes the sanitized public state (projectPublic) at
   sessions/{code}/display; displays subscribe read-only. Presence heartbeats
   let a remote screen tell "host offline" apart from "session ended". The
   BroadcastChannel/relay link stays the same-device fast path. */

import type { PublicState } from "../lib/types";
import { getFirebase } from "./client";
import { firebaseConfigured } from "./config";
import {
  displayPath,
  displayPresencePath,
  metaPath,
} from "./paths";

const HEARTBEAT_MS = 5_000;
const RETRY_MS = 5_000;
const EXISTENCE_GRACE_MS = 2_500;

/**
 * Realtime Database drops empty arrays/objects, so a fresh session loses
 * `teams: []` or `scores: {}`. Fill them back before the display renders.
 */
export function normalizePublicState(raw: PublicState): PublicState {
  return {
    ...raw,
    participants: raw.participants ?? [],
    teams: raw.teams ?? [],
    scores: raw.scores ?? {},
    results: raw.results ?? [],
    question: raw.question
      ? { ...raw.question, answers: raw.question.answers ?? [] }
      : null,
    feud: raw.feud ? { ...raw.feud, strikes: raw.feud.strikes ?? {} } : null,
    ml: raw.ml ? { ...raw.ml, winners: raw.ml.winners ?? [] } : null,
    pir: raw.pir
      ? {
          ...raw.pir,
          guesses: raw.pir.guesses ?? null,
          winners: raw.pir.winners ?? [],
          party: raw.pir.party
            ? {
                ...raw.pir.party,
                teams: raw.pir.party.teams ?? [],
                scores: raw.pir.party.scores ?? {},
                podium: raw.pir.party.podium ?? [],
                guesses: raw.pir.party.guesses ?? null,
              }
            : null,
        }
      : null,
  };
}

export interface DisplayFeed {
  publish(state: PublicState, revision: number): void;
  end(): void;
  close(): void;
}

const NOOP: DisplayFeed = {
  publish() {},
  end() {},
  close() {},
};

/** Host side: ensure the session record exists and mirror public state. */
export function startDisplayFeed(code: string): DisplayFeed {
  if (!firebaseConfigured()) return NOOP;

  let closed = false;
  let ended = false;
  let timer: number | undefined;
  let retry: number | undefined;
  let latest: { state: PublicState; revision: number } | null = null;

  const beat = async () => {
    try {
      const firebase = await getFirebase();
      await firebase.set(displayPresencePath(code), { at: Date.now() });
    } catch {
      /* the next beat retries */
    }
  };

  const push = async (state: PublicState, revision: number) => {
    const firebase = await getFirebase();
    await firebase.update(displayPath(code), {
      revision,
      state,
      updatedAt: Date.now(),
      ended: false,
    });
  };

  const connect = async () => {
    if (closed) return;
    try {
      const firebase = await getFirebase();
      if (closed) return;
      const meta = await firebase.get(metaPath(code));
      if (!meta) {
        await firebase.set(metaPath(code), { hostUid: firebase.uid, createdAt: Date.now() });
      }
      if (closed) return;
      if (latest) await push(latest.state, latest.revision);
      await beat();
      if (closed) return;
      timer = window.setInterval(() => void beat(), HEARTBEAT_MS);
    } catch {
      if (closed) return;
      retry = window.setTimeout(() => void connect(), RETRY_MS);
    }
  };

  void connect();

  return {
    publish(state, revision) {
      if (ended) return;
      latest = { state, revision };
      if (closed) return;
      void push(state, revision).catch(() => undefined);
    },
    end() {
      ended = true;
      latest = null;
      void markDisplayEnded(code).catch(() => undefined);
    },
    close() {
      closed = true;
      if (timer) window.clearInterval(timer);
      if (retry) window.clearTimeout(retry);
      timer = undefined;
      retry = undefined;
    },
  };
}

/** Explicit end marker; the session record stays readable for displays. */
export async function markDisplayEnded(code: string): Promise<void> {
  const firebase = await getFirebase();
  await firebase.update(displayPath(code), {
    // Drop the public state too: no player names linger after the evening.
    state: null,
    ended: true,
    endedAt: Date.now(),
    updatedAt: Date.now(),
  });
}

export interface DisplayFeedHandlers {
  onState(state: PublicState, revision: number, freshAt: number): void;
  onEnded(): void;
  onWaiting(): void;
  onInvalid(): void;
  onSeen(): void;
}

/** Display side: read-only subscription with validity and ended detection. */
export function subscribeDisplayFeed(
  code: string,
  handlers: DisplayFeedHandlers,
): () => void {
  if (!firebaseConfigured()) return () => {};

  let closed = false;
  let unsubscribe = () => {};
  let existenceTimer: number | undefined;

  const checkExistence = () => {
    if (existenceTimer || closed) return;
    existenceTimer = window.setTimeout(async () => {
      existenceTimer = undefined;
      try {
        const firebase = await getFirebase();
        if (closed) return;
        const meta = await firebase.get(metaPath(code));
        if (closed) return;
        if (meta) handlers.onWaiting();
        else handlers.onInvalid();
      } catch {
        /* offline: keep waiting, the banner covers it */
      }
    }, EXISTENCE_GRACE_MS);
  };

  void getFirebase().then(
    (firebase) => {
      if (closed) return;
      unsubscribe = firebase.subscribe(
        displayPath(code),
        (value) => {
          if (closed) return;
          if (existenceTimer) {
            window.clearTimeout(existenceTimer);
            existenceTimer = undefined;
          }
          if (!value) {
            checkExistence();
            return;
          }
          const data = value as Record<string, unknown>;
          const revision = Number(data.revision ?? 0);
          const presence = (data.presence ?? {}) as Record<string, unknown>;
          // Heartbeats, not state edits, prove the host is still live.
          const freshAt = Number(presence.at ?? 0) || Number(data.updatedAt ?? 0);
          const state = data.state as PublicState | undefined;
          handlers.onSeen();
          if (state && revision > 0) handlers.onState(state, revision, freshAt);
          else if (!data.ended) handlers.onWaiting();
          if (data.ended) handlers.onEnded();
        },
        () => {
          /* keep the last public state; the offline banner explains it */
        },
      );
    },
    () => {
      /* no Firebase: the local/relay carriers still work */
    },
  );

  return () => {
    closed = true;
    if (existenceTimer) window.clearTimeout(existenceTimer);
    unsubscribe();
  };
}
