/* Host orchestration for Price Is Right phone teams: mirrors the host's round
   state to Realtime Database and folds phone joins/guesses into the engine. */

import { useEffect, useRef, useState } from "react";
import type { Action, PriceQuestion, Question, SessionState } from "../lib/types";
import { firebaseConfigured } from "./config";
import { friendlyFirebaseError } from "./errors";
import {
  ensureSession,
  removeSession,
  removeTeamRemote,
  renameTeam,
  subscribeGuesses,
  subscribeTeams,
  writeBoard,
  writeGuessForTeam,
  type PartyBoard,
  type PartyTeam,
} from "./priceParty";

export interface PricePartyApi {
  enabled: boolean;
  error: string | null;
  setManualGuess(teamId: string, value: number): void;
  removeTeam(teamId: string): void;
  rename(teamId: string, name: string): void;
  endRemoteSession(): Promise<void>;
}

export function usePriceParty(options: {
  session: SessionState | null;
  question: PriceQuestion | null;
  questions: Question[];
  send: (action: Action) => void;
}): PricePartyApi {
  const { session, question, questions, send } = options;

  // Between rounds the engine still points at the last question, so the board
  // is primed with the upcoming item to reset the phones.
  const upcoming =
    session?.phase === "ROUND_READY"
      ? (questions[session.questionIndex] as PriceQuestion | undefined) ?? null
      : null;
  const enabled = Boolean(session?.pir?.party) && firebaseConfigured();
  const code = session?.code ?? null;
  const roundId = question?.id ?? null;

  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const teamsRef = useRef<Record<string, PartyTeam>>({});
  const lastBoardRef = useRef<string>("");

  useEffect(() => {
    if (!enabled || !code) return;
    let cancelled = false;
    let unsubscribeTeams = () => {};
    let unsubscribeGuesses = () => {};

    void (async () => {
      try {
        // Same reason as client.ts: keep the Firebase SDK out of the initial
        // bundle when phone teams are disabled.
        const { getFirebase } = await import("./client");
        const { uid } = await getFirebase();
        await ensureSession(code, uid);
        if (cancelled) return;

        unsubscribeTeams = subscribeTeams(code, (teams) => {
          teamsRef.current = teams;
          setError(null);
          const live = sessionRef.current;
          if (!live?.pir?.party) return;
          for (const [teamId, team] of Object.entries(teams)) {
            const existing = live.pir.party.teams[teamId];
            if (!existing || existing.name !== team.name) {
              send({ type: "pir_team_add", teamId, name: String(team.name) });
            }
          }
        }, (subscribeError) => setError(friendlyFirebaseError(subscribeError)));

        unsubscribeGuesses = subscribeGuesses(code, (guesses) => {
          const live = sessionRef.current;
          if (!live?.pir?.party || !roundId) return;
          if (live.pir.party.locked || live.pir.party.revealed) return;

          for (const [teamId, rounds] of Object.entries(guesses ?? {})) {
            const value = rounds?.[roundId];
            if (typeof value !== "number") continue;

            if (!live.pir.party.teams[teamId]) {
              const team = teamsRef.current[teamId];
              if (!team) continue;
              send({ type: "pir_team_add", teamId, name: String(team.name) });
            }
            if (live.pir.party.guesses[teamId] !== value) {
              send({ type: "pir_set_guess", entityId: teamId, value });
            }
          }
        }, (subscribeError) => setError(friendlyFirebaseError(subscribeError)));
      } catch (connectionError) {
        if (cancelled) return;
        setError(friendlyFirebaseError(connectionError));
      }
    })();

    return () => {
      cancelled = true;
      unsubscribeTeams();
      unsubscribeGuesses();
    };
  }, [enabled, code, roundId, send]);

  useEffect(() => {
    const boardQuestion = upcoming ?? question;
    if (!enabled || !code || !boardQuestion) return;
    const party = sessionRef.current?.pir?.party;
    if (!party) return;

    const primed = Boolean(upcoming);
    const board: PartyBoard = {
      roundId: boardQuestion.id,
      index: session?.questionIndex ?? 0,
      item: boardQuestion.item,
      description: boardQuestion.description,
      image: boardQuestion.image,
      currency: session?.config.currency || boardQuestion.currency,
      priceUnit: boardQuestion.priceUnit,
      mode: party.mode,
      capacity: party.capacity,
      locked: primed ? false : party.locked,
      revealed: primed ? false : party.revealed,
      priceRevealed: primed ? false : party.priceRevealed,
      leaderboardRevealed: primed ? false : party.leaderboardRevealed,
      price: !primed && party.priceRevealed ? boardQuestion.actualPrice : null,
      scores: party.scores,
      podium: primed ? [] : party.podium,
    };

    const signature = JSON.stringify(board);
    if (signature === lastBoardRef.current) return;
    lastBoardRef.current = signature;

    void (async () => {
      try {
        // The board write is authorised by the host uid stored in meta, so the
        // session must exist first.
        const { getFirebase } = await import("./client");
        const { uid } = await getFirebase();
        await ensureSession(code, uid);
        await writeBoard(code, board);
      } catch (writeError) {
        lastBoardRef.current = "";
        setError(friendlyFirebaseError(writeError));
      }
    })();
  }, [
    enabled,
    code,
    question,
    upcoming,
    session?.config.currency,
    session?.questionIndex,
    session?.phase,
    session?.pir?.party,
  ]);

  useEffect(() => {
    lastBoardRef.current = "";
    // A new session (or a reopened one) starts with a clean slate; errors from
    // the previous Firebase listener must not linger.
    setError(null);
  }, [code]);

  // A finished Price Is Right game cleans up its temporary session data.
  useEffect(() => {
    if (!code || !firebaseConfigured()) return;
    if (session?.game !== "price_is_right") return;
    if (!session.pir?.party) return;
    if (session.phase !== "GAME_RESULT") return;
    void removeSession(code).catch(() => undefined);
  }, [code, session?.game, session?.pir?.party, session?.phase]);

  return {
    enabled,
    error,
    setManualGuess(teamId, value) {
      send({ type: "pir_set_guess", entityId: teamId, value });
      if (code && roundId) void writeGuessForTeam(code, teamId, roundId, value);
    },
    removeTeam(teamId) {
      send({ type: "pir_team_remove", teamId });
      if (code) void removeTeamRemote(code, teamId);
    },
    rename(teamId, name) {
      send({ type: "pir_team_add", teamId, name });
      if (code) void renameTeam(code, teamId, name);
    },
    async endRemoteSession() {
      if (!code) return;
      await removeSession(code).catch(() => undefined);
    },
  };
}
