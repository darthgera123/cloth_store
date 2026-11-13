/* Realtime Database helpers for The Price Is Right phone teams.
   The host is the only writer of the board and scores; phones write their own
   team record and guess. */

import { getFirebase } from "./client";
import {
  boardPath,
  guessPath,
  metaPath,
  sessionPath,
  teamPath,
  teamsPath,
  teamGuessesPath,
} from "./paths";

export interface PartyBoard {
  roundId: string;
  index: number;
  item: string;
  description: string;
  image: string;
  currency: string;
  priceUnit: string;
  mode: "teams" | "individual";
  capacity: number;
  locked: boolean;
  revealed: boolean;
  priceRevealed: boolean;
  leaderboardRevealed: boolean;
  price: number | null;
  scores: Record<string, number>;
  podium: { entryId: string; rank: number; points: number; distance: number }[];
}

export interface PartyTeam {
  name: string;
  uid: string;
  joinedAt: number;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const PARTY_SLOTS = {
  teams: ["t1", "t2", "t3"],
  individual: ["p1", "p2", "p3", "p4", "p5", "p6"],
} as const;

export type PartyMode = keyof typeof PARTY_SLOTS;

export async function ensureSession(code: string, uid: string): Promise<void> {
  const firebase = await getFirebase();
  const meta = await firebase.get(metaPath(code));
  if (!meta) {
    await firebase.set(metaPath(code), { hostUid: uid, createdAt: Date.now() });
  }
}

export async function writeBoard(code: string, board: PartyBoard): Promise<void> {
  const firebase = await getFirebase();
  await firebase.set(boardPath(code), board);
}

export async function removeSession(code: string): Promise<void> {
  const firebase = await getFirebase();
  await firebase.remove(sessionPath(code));
}

export async function readSessionMeta(code: string): Promise<{ createdAt: number } | null> {
  const firebase = await getFirebase();
  const meta = await firebase.get(metaPath(code));
  if (!meta) return null;
  return { createdAt: Number(meta.createdAt ?? 0) };
}

export async function readBoard(code: string): Promise<PartyBoard | null> {
  const firebase = await getFirebase();
  const board = await firebase.get(boardPath(code));
  return board ? (board as unknown as PartyBoard) : null;
}

export function subscribeTeams(
  code: string,
  callback: (teams: Record<string, PartyTeam>) => void,
  onError?: (error: unknown) => void,
): () => void {
  let unsubscribe = () => {};
  void getFirebase()
    .then((firebase) => {
      unsubscribe = firebase.subscribe(
        teamsPath(code),
        (value) => {
          callback(asRecord(value) as unknown as Record<string, PartyTeam>);
        },
        onError,
      );
    })
    .catch((error) => onError?.(error));
  return () => unsubscribe();
}

export function subscribeGuesses(
  code: string,
  callback: (guesses: Record<string, Record<string, number>>) => void,
  onError?: (error: unknown) => void,
): () => void {
  let unsubscribe = () => {};
  void getFirebase()
    .then((firebase) => {
      unsubscribe = firebase.subscribe(
        `${sessionPath(code)}/guesses`,
        (value) => {
          callback(asRecord(value) as unknown as Record<string, Record<string, number>>);
        },
        onError,
      );
    })
    .catch((error) => onError?.(error));
  return () => unsubscribe();
}

export function subscribeBoard(
  code: string,
  callback: (board: PartyBoard | null) => void,
  onError?: (error: unknown) => void,
): () => void {
  let unsubscribe = () => {};
  void getFirebase()
    .then((firebase) => {
      unsubscribe = firebase.subscribe(
        boardPath(code),
        (value) => {
          callback(value ? (value as unknown as PartyBoard) : null);
        },
        onError,
      );
    })
    .catch((error) => onError?.(error));
  return () => unsubscribe();
}

export function subscribeOwnGuess(
  code: string,
  teamId: string,
  roundId: string,
  callback: (value: number | null) => void,
  onError?: (error: unknown) => void,
): () => void {
  let unsubscribe = () => {};
  void getFirebase()
    .then((firebase) => {
      unsubscribe = firebase.subscribe(
        guessPath(code, teamId, roundId),
        (value) => {
          callback(typeof value === "number" ? value : null);
        },
        onError,
      );
    })
    .catch((error) => onError?.(error));
  return () => unsubscribe();
}

export function subscribeOwnTeam(
  code: string,
  teamId: string,
  callback: (team: PartyTeam | null) => void,
  onError?: (error: unknown) => void,
): () => void {
  let unsubscribe = () => {};
  void getFirebase()
    .then((firebase) => {
      unsubscribe = firebase.subscribe(
        teamPath(code, teamId),
        (value) => {
          callback(value ? (value as unknown as PartyTeam) : null);
        },
        onError,
      );
    })
    .catch((error) => onError?.(error));
  return () => unsubscribe();
}

/** Claim the first free slot atomically; concurrent phones never share one. */
export async function claimSlot(
  code: string,
  mode: PartyMode,
  uid: string,
  name: string,
): Promise<{ slot: string; team: PartyTeam } | { full: true }> {
  const firebase = await getFirebase();
  for (const slot of PARTY_SLOTS[mode]) {
    const claimed = await firebase.transaction(teamPath(code, slot), (current) => {
      if (current && typeof current === "object") return undefined; // taken: abort
      return { name, uid, joinedAt: Date.now() };
    });
    if (claimed && typeof claimed === "object") {
      return { slot, team: claimed as PartyTeam };
    }
  }
  return { full: true };
}

export async function renameTeam(code: string, teamId: string, name: string): Promise<void> {
  const firebase = await getFirebase();
  await firebase.update(teamPath(code, teamId), { name });
}

export async function submitGuess(
  code: string,
  teamId: string,
  roundId: string,
  value: number,
): Promise<void> {
  const firebase = await getFirebase();
  await firebase.set(guessPath(code, teamId, roundId), value);
}

export async function writeGuessForTeam(
  code: string,
  teamId: string,
  roundId: string,
  value: number,
): Promise<void> {
  const firebase = await getFirebase();
  await firebase.set(guessPath(code, teamId, roundId), value);
}

export async function removeTeamRemote(code: string, teamId: string): Promise<void> {
  const firebase = await getFirebase();
  await firebase.remove(teamPath(code, teamId));
  await firebase.remove(teamGuessesPath(code, teamId));
}
