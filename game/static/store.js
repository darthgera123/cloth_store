/* Game Night — shared state.
   One state object drives both the audience display and the host dashboard.
   Every open page writes through the same store; pages mirror each other via
   a BroadcastChannel (same browser profile) with localStorage as the durable
   copy, so a projector tab and a laptop tab stay in step without a server. */

const KEY = "game-night:state:v1";
const CHANNEL = "game-night";

export function blankState(data) {
  return {
    screen: "welcome",
    feud: {
      q: 0,
      active: 0,
      teams: [
        { name: data.teams[0], score: 0, strikes: 0 },
        { name: data.teams[1], score: 0, strikes: 0 },
      ],
      revealed: data.feud.questions.map((q) => q.answers.map(() => false)),
    },
  };
}

function readStored() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** Shape-check stored or broadcast state against the current question set. */
export function isValid(state, data) {
  if (!state || typeof state !== "object") return false;
  const { screen, feud } = state;
  if (!["welcome", "games", "feud"].includes(screen)) return false;
  if (!feud || !Array.isArray(feud.teams) || feud.teams.length !== 2) return false;
  if (!Number.isInteger(feud.q) || !data.feud.questions[feud.q]) return false;
  if (!Array.isArray(feud.revealed) || feud.revealed.length !== data.feud.questions.length) {
    return false;
  }
  return feud.revealed.every(
    (row, i) => Array.isArray(row) && row.length === data.feud.questions[i].answers.length,
  );
}

export function createStore(data, { writable = true } = {}) {
  const fallback = blankState(data);
  const stored = readStored();
  let state = isValid(stored, data) ? stored : fallback;

  const listeners = new Set();
  const channel =
    typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null;

  function emit() {
    for (const fn of listeners) fn(state);
  }

  /** Write, persist, publish. `foreign` marks state adopted from another tab. */
  function commit(next, foreign = false) {
    state = next;
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: keep the session in memory */
    }
    if (!foreign && channel) channel.postMessage(next);
    emit();
  }

  function adopt(candidate) {
    if (!isValid(candidate, data)) return;
    if (JSON.stringify(candidate) === JSON.stringify(state)) return;
    commit(candidate, true);
  }

  if (channel) channel.addEventListener("message", (event) => adopt(event.data));

  window.addEventListener("storage", (event) => {
    if (event.key !== KEY || !event.newValue) return;
    try {
      adopt(JSON.parse(event.newValue));
    } catch {
      /* ignore malformed values */
    }
  });

  return {
    get: () => state,
    subscribe(fn) {
      listeners.add(fn);
      fn(state);
      return () => listeners.delete(fn);
    },
    /** Mutate a draft copy and publish it. */
    update(mutator) {
      if (!writable) return;
      const draft = structuredClone(state);
      mutator(draft);
      commit(draft);
    },
    reset() {
      if (!writable) return;
      commit(blankState(data));
    },
  };
}
