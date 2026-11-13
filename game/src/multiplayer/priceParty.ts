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
  locked: boolean;
  revealed: boolean;
  priceRevealed: boolean;
  price: number | null;
  scores: Record<string, number>;
  winners: string[];
}

export interface PartyTeam {
  name: string;
  uid: string;
  joinedAt: number;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

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

export async function joinTeam(
  code: string,
  teamId: string,
  name: string,
  uid: string,
): Promise<void> {
  const firebase = await getFirebase();
  await firebase.set(teamPath(code, teamId), { name, uid, joinedAt: Date.now() });
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
