/* Bring a persisted host session forward when game rules change. */

import type { SessionState } from "./types";

/**
 * Sessions saved before the alternating-turn Family Feud rules carry a
 * per-team strike map and a pot. Resuming them would corrupt the new engine,
 * so the Feud round is restarted (teams, scores and the game itself stay).
 */
export function migrateLegacySession(state: SessionState): SessionState {
  const feud = state.feud as unknown as { strikes?: unknown } | null;
  if (state.game !== "family_feud" || !feud || typeof feud.strikes === "number") {
    return state;
  }
  const restartPhase =
    state.phase === "QUESTION_ACTIVE" ||
    state.phase === "REVEAL" ||
    state.phase === "ROUND_RESULT";
  return {
    ...state,
    feud: null,
    phase: restartPhase ? "ROUND_READY" : state.phase,
    paused: false,
    timer: null,
  };
}
