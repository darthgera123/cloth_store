/* Host-side game session. The host browser owns the state: it applies actions
   locally, persists the session in sessionStorage and publishes a public
   snapshot over BroadcastChannel and the optional relay. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { applyAction, createSession, projectPublic, questionsFor } from "../engine/engine";
import { ACTION_LABEL } from "../lib/actionLabel";
import type {
  Action,
  HostState,
  QuestionBank,
  SessionConfig,
  SessionState,
} from "../lib/types";
import {
  createHostLink,
  type HostLink,
  type HostLinkStatus,
} from "../transport/link";

const STORAGE_KEY = "gn:host-session:v1";
const HISTORY_LIMIT = 12;

export interface HostSnapshot {
  label: string;
  at: number;
  state: SessionState;
}

interface PersistedSession {
  code: string;
  revision: number;
  state: SessionState;
  history: HostSnapshot[];
}

export interface HostGameApi {
  ready: boolean;
  code: string | null;
  hostState: HostState | null;
  link: HostLinkStatus;
  error: string | null;
  createSession(input: {
    names: string[];
    teams: [string, string] | null;
    config?: Partial<SessionConfig>;
    participantTeams?: (0 | 1 | null)[];
  }): Promise<boolean>;
  send(action: Action): void;
  undo(): void;
  endSession(): void;
  clearError(): void;
}

function readPersisted(): PersistedSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedSession;
    if (!parsed?.code || !parsed.state?.code || !parsed.state?.phase) return null;
    if (!Array.isArray(parsed.history)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function persist(session: PersistedSession | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage may be full or disabled; the evening continues in memory */
  }
}

const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function randomCode(): string {
  let out = "";
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  for (const byte of bytes) out += CODE_ALPHABET[byte % CODE_ALPHABET.length];
  return out;
}

export function useHostGame(): HostGameApi {
  const [bank, setBank] = useState<QuestionBank | null>(null);
  const [session, setSessionState] = useState<PersistedSession | null>(() => readPersisted());
  const [link, setLink] = useState<HostLinkStatus>({
    sameDevice: false,
    relay: "off",
    relayConfigured: false,
    displays: 0,
  });
  const [error, setError] = useState<string | null>(null);

  const sessionRef = useRef<PersistedSession | null>(session);
  const bankRef = useRef<QuestionBank | null>(null);
  const linkRef = useRef<HostLink | null>(null);

  const setSession = useCallback((next: PersistedSession | null) => {
    sessionRef.current = next;
    setSessionState(next);
  }, []);

  useEffect(() => {
    let active = true;
    void import("../questions/bank").then((module) => {
      if (!active) return;
      try {
        const loaded = module.loadQuestionBank();
        bankRef.current = loaded;
        setBank(loaded);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Question bank failed to load");
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const publish = useCallback((snapshot: PersistedSession) => {
    const loaded = bankRef.current;
    if (!loaded) return;
    linkRef.current?.publish(projectPublic(snapshot.state, loaded), snapshot.revision);
  }, []);

  const commit = useCallback(
    (nextState: SessionState, label: string, previous: PersistedSession) => {
      const snapshot: PersistedSession = {
        code: previous.code,
        revision: previous.revision + 1,
        state: nextState,
        history: [
          { label, at: Date.now(), state: previous.state },
          ...previous.history,
        ].slice(0, HISTORY_LIMIT),
      };
      setSession(snapshot);
      persist(snapshot);
      publish(snapshot);
    },
    [publish, setSession],
  );

  const code = session?.code ?? null;

  useEffect(() => {
    if (!code || !bank) return;
    const current = sessionRef.current;
    if (!current) return;

    const hostLink = createHostLink({
      code,
      onHello: () => {
        const live = sessionRef.current;
        if (live && bankRef.current) {
          hostLink.publish(projectPublic(live.state, bankRef.current), live.revision);
        }
      },
      onStatus: setLink,
    });
    linkRef.current = hostLink;
    hostLink.publish(projectPublic(current.state, bank), current.revision);

    return () => {
      hostLink.close();
      linkRef.current = null;
    };
  }, [code, bank]);

  const create = useCallback(
    async (input: {
      names: string[];
      teams: [string, string] | null;
      config?: Partial<SessionConfig>;
      participantTeams?: (0 | 1 | null)[];
    }) => {
      const loaded = bankRef.current;
      if (!loaded) {
        setError("Question bank is still loading");
        return false;
      }
      try {
        const sessionCode = randomCode();
        const state = createSession(input, sessionCode, Date.now());
        const snapshot: PersistedSession = {
          code: sessionCode,
          revision: 1,
          state,
          history: [],
        };
        setSession(snapshot);
        persist(snapshot);
        return true;
      } catch (createError) {
        setError(createError instanceof Error ? createError.message : "Could not start the session");
        return false;
      }
    },
    [setSession],
  );

  const send = useCallback(
    (action: Action) => {
      const loaded = bankRef.current;
      const current = sessionRef.current;
      if (!loaded || !current) return;
      try {
        const next = applyAction(current.state, action, loaded, Date.now());
        commit(next, ACTION_LABEL[action.type] ?? action.type, current);
        setError(null);
      } catch (actionError) {
        setError(actionError instanceof Error ? actionError.message : "Action refused");
      }
    },
    [commit],
  );

  const undo = useCallback(() => {
    const current = sessionRef.current;
    if (!current || current.history.length === 0) return;
    const [entry, ...rest] = current.history;
    if (!entry) return;
    const next: PersistedSession = {
      code: current.code,
      revision: current.revision + 1,
      state: entry.state,
      history: rest,
    };
    setSession(next);
    persist(next);
    publish(next);
  }, [publish, setSession]);

  const endSession = useCallback(() => {
    linkRef.current?.endSession();
    setSession(null);
    persist(null);
  }, [setSession]);

  const clearError = useCallback(() => setError(null), []);

  const hostState = useMemo<HostState | null>(() => {
    if (!session || !bank) return null;
    return {
      session: session.state,
      questions: session.state.game ? questionsFor(bank, session.state.game) : [],
      canUndo: session.history.length > 0,
      undoLabel: session.history[0]?.label ?? null,
      history: session.history.slice(0, 8).map((entry) => ({
        label: entry.label,
        at: entry.at,
      })),
    };
  }, [session, bank]);

  return {
    ready: bank !== null,
    code,
    hostState,
    link,
    error,
    createSession: create,
    send,
    undo,
    endSession,
    clearError,
  };
}
