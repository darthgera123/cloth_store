/* Authoritative game engine. Pure functions over SessionState: the server only
   validates, snapshots and persists what these return. */

import {
  type Action,
  type FeudQuestion,
  type GameId,
  type FeudOutcome,
  type GameStanding,
  type Participant,
  type HerdResult,
  type HerdState,
  type Phase,
  type PriceQuestion,
  type PublicAnswer,
  type PublicState,
  type Question,
  type QuestionBank,
  type Scores,
  type SessionConfig,
  type SessionState,
  type Team,
  configSchema,
  defaultConfig,
} from "../lib/types";
import { herdGroups, normalizeAnswer } from "../lib/herd";

export class EngineError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function fail(message: string, code = "invalid"): never {
  throw new EngineError(code, message);
}

export const questionsFor = (bank: QuestionBank, game: GameId): Question[] =>
  bank[game] as Question[];

export function currentQuestion(state: SessionState, bank: QuestionBank): Question | null {
  if (!state.game) return null;
  const id =
    state.feud?.questionId ??
    state.herd?.questionId ??
    state.ml?.questionId ??
    state.pir?.questionId ??
    null;
  const list = questionsFor(bank, state.game);
  if (id) return list.find((q) => q.id === id) ?? null;
  const ordered = state.questionOrder[state.questionIndex];
  return list.find((q) => q.id === ordered) ?? list[state.questionIndex] ?? null;
}

function shuffled<T>(items: T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    const a = copy[i];
    const b = copy[j];
    if (a !== undefined && b !== undefined) {
      copy[i] = b;
      copy[j] = a;
    }
  }
  return copy;
}

/* ---------- creation ---------- */

export function createSession(
  input: {
    names: string[];
    teams: [string, string] | null;
    config?: Partial<SessionConfig>;
    participantTeams?: (0 | 1 | null)[];
  },
  code: string,
  now: number,
): SessionState {
  const names = input.names.map((n) => n.trim()).filter(Boolean);
  if (names.length < 2) fail("At least two participants are required");

  const teams: Team[] = input.teams
    ? [
        { id: "t1", name: input.teams[0].trim() },
        { id: "t2", name: input.teams[1].trim() },
      ]
    : [];

  const participants: Participant[] = names.map((name, index) => ({
    id: `p${index + 1}`,
    name,
    teamId: teams.length
      ? (input.participantTeams?.[index] ?? (index % 2 === 0 ? 0 : 1)) === 0
        ? "t1"
        : "t2"
      : null,
  }));

  const config: SessionConfig = { ...defaultConfig, ...input.config };
  configSchema.parse(config);

  return {
    id: crypto.randomUUID(),
    code,
    createdAt: now,
    updatedAt: now,
    status: "lobby",
    phase: "LOBBY",
    paused: false,
    game: null,
    round: 0,
    questionIndex: 0,
    usedQuestionIds: [],
    questionOrder: [],
    participants,
    teams,
    config,
    scores: emptyScores(participants, teams),
    feud: null,
    herd: null,
    ml: null,
    pir: null,
    timer: null,
    results: [],
    roundAwards: [],
  };
}

function emptyScores(participants: Participant[], teams: Team[]): Scores {
  return {
    participants: Object.fromEntries(participants.map((p) => [p.id, 0])),
    teams: Object.fromEntries(teams.map((t) => [t.id, 0])),
  };
}

/* ---------- helpers ---------- */

const needPhase = (state: SessionState, phases: Phase[]) => {
  if (!phases.includes(state.phase)) {
    fail(`Action not allowed in ${state.phase} (expected ${phases.join(", ")})`, "phase");
  }
};

const needGame = (state: SessionState, game: GameId) => {
  if (state.game !== game) fail(`No ${game} game is active`, "game");
};

const teamIds = (state: SessionState): [string, string] => {
  const a = state.teams[0];
  const b = state.teams[1];
  if (!a || !b) fail("This game needs two teams");
  return [a.id, b.id];
};

function feudQuestionOf(state: SessionState, bank: QuestionBank): FeudQuestion | null {
  const question = currentQuestion(state, bank);
  return question && question.game === "family_feud" ? question : null;
}

function feudCreditedPoints(
  state: SessionState,
  bank: QuestionBank,
): Record<string, number> {
  const feud = state.feud;
  const question = feudQuestionOf(state, bank);
  const [a, b] = teamIds(state);
  const totals: Record<string, number> = { [a]: 0, [b]: 0 };
  if (!feud || !question) return totals;
  for (const [answerId, teamId] of Object.entries(feud.credited)) {
    const answer = question.answers.find((item) => item.id === answerId);
    if (answer) totals[teamId] = (totals[teamId] ?? 0) + answer.points;
  }
  return totals;
}

function finishFeudRound(
  state: SessionState,
  bank: QuestionBank,
  trigger: "answers_exhausted" | "both_eliminated",
) {
  const feud = state.feud;
  if (!feud || feud.ended) return;
  const [a, b] = teamIds(state);
  const credited = feudCreditedPoints(state, bank);
  const limit = state.config.strikeLimit;
  const alive = [a, b].filter((id) => (feud.strikes[id] ?? 0) < limit);

  let reason: FeudOutcome["reason"] = trigger;
  let winner: string | null = null;
  let tied = false;

  if (alive.length === 1) {
    // Only one team left in the round: it takes the whole pot (rule 7).
    reason = "last_team_standing";
    winner = alive[0] ?? null;
  } else if ((credited[a] ?? 0) === (credited[b] ?? 0)) {
    // Both alive with the board clear, or both eliminated: level on revealed
    // points, so the host decides (rule 8).
    tied = true;
  } else {
    winner = (credited[a] ?? 0) > (credited[b] ?? 0) ? a : b;
  }

  feud.ended = true;
  feud.outcome = { reason, winnerTeamId: winner, tied, credited };
  state.phase = "REVEAL";
}

/** Hand the next guess to the other team, unless it is already eliminated. */
function advanceFeudTurn(state: SessionState) {
  const feud = state.feud;
  if (!feud || feud.ended) return;
  const [a, b] = teamIds(state);
  const next = feud.activeTeamId === a ? b : a;
  if ((feud.strikes[next] ?? 0) < state.config.strikeLimit) feud.activeTeamId = next;
}

function computeHerdResult(herd: HerdState, state: SessionState): HerdResult {
  const groups = herdGroups(herd, state.participants);
  if (groups.length === 0) {
    return { groups, winners: [], tied: false, points: 0 };
  }

  const max = groups[0]?.participantIds.length ?? 0;
  const leaders = groups.filter((g) => g.participantIds.length === max);
  const tied = leaders.length > 1;
  const winners = tied
    ? state.config.herdTieAwards
      ? leaders.flatMap((g) => g.participantIds)
      : []
    : [...(leaders[0]?.participantIds ?? [])];

  return { groups, winners, tied, points: winners.length ? state.config.herdPoints : 0 };
}

function priceEntityIds(state: SessionState): string[] {
  return state.config.pirMode === "team"
    ? state.teams.map((t) => t.id)
    : state.participants.map((p) => p.id);
}

function computePriceWinners(state: SessionState, honestPrice: number): string[] {
  const guesses = state.pir?.guesses ?? {};
  const entries = Object.entries(guesses).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );
  if (entries.length === 0) return [];

  const under = entries.filter(([, value]) => value <= honestPrice);
  if (under.length > 0) {
    const best = Math.max(...under.map(([, value]) => value));
    return under.filter(([, value]) => value === best).map(([id]) => id);
  }

  if (state.config.pirAllOverFallback === "lowest") {
    const best = Math.min(...entries.map(([, value]) => value));
    return entries.filter(([, value]) => value === best).map(([id]) => id);
  }

  const best = Math.min(...entries.map(([, value]) => Math.abs(value - honestPrice)));
  return entries.filter(([, value]) => Math.abs(value - honestPrice) === best).map(([id]) => id);
}

function addPoints(
  state: SessionState,
  kind: "participant" | "team",
  id: string,
  points: number,
) {
  if (points === 0) return;
  const bucket = kind === "participant" ? state.scores.participants : state.scores.teams;
  bucket[id] = (bucket[id] ?? 0) + points;
  state.roundAwards.push({ kind, id, points });
}

function standingsFor(state: SessionState): GameStanding[] {
  const herd = state.game === "herd_mentality" ? state.herd : null;
  const blocked =
    herd && state.config.pinkCowEnabled && state.config.pinkCowBlocksWin ? herd.pinkCow : null;

  const rows =
    state.game === "family_feud"
      ? state.teams.map((team) => ({
          id: team.id,
          label: team.name,
          points: state.scores.teams[team.id] ?? 0,
        }))
      : state.participants.map((person) => ({
          id: person.id,
          label: person.name,
          points: state.scores.participants[person.id] ?? 0,
        }));

  const best = Math.max(0, ...rows.filter((row) => row.id !== blocked).map((row) => row.points));

  return rows
    .sort((a, b) => b.points - a.points || a.label.localeCompare(b.label))
    .map((row) => ({
      label: row.label,
      points: row.points,
      winner: row.id !== blocked && row.points === best && best > 0,
      blocked: row.id === blocked,
    }));
}

/* ---------- round setup ---------- */

function initGameState(state: SessionState, question: Question) {
  state.usedQuestionIds = [...new Set([...state.usedQuestionIds, question.id])];

  if (question.game === "family_feud") {
    const [a, b] = teamIds(state);
    // Alternate the opening team every round; question index parity is stable
    // across restarts and undo.
    const starter = state.questionIndex % 2 === 0 ? a : b;
    state.feud = {
      questionId: question.id,
      revealed: [],
      credited: {},
      strikes: { [a]: 0, [b]: 0 },
      activeTeamId: starter,
      startingTeamId: starter,
      pot: 0,
      awarded: false,
      awardedTo: null,
      ended: false,
      outcome: null,
    };
    state.herd = null;
    state.ml = null;
    state.pir = null;
  } else if (question.game === "herd_mentality") {
    state.herd = {
      questionId: question.id,
      answers: Object.fromEntries(state.participants.map((p) => [p.id, ""])),
      merges: {},
      result: null,
      awarded: false,
      pinkCow: state.herd?.pinkCow ?? null,
    };
    state.feud = null;
    state.ml = null;
    state.pir = null;
  } else if (question.game === "whos_most_likely") {
    state.ml = {
      questionId: question.id,
      votes: Object.fromEntries(state.participants.map((p) => [p.id, 0])),
      revealed: false,
      winners: [],
      awarded: false,
    };
    state.feud = null;
    state.herd = null;
    state.pir = null;
  } else {
    state.pir = {
      questionId: question.id,
      guesses: Object.fromEntries(priceEntityIds(state).map((id) => [id, null])),
      locked: false,
      guessesRevealed: false,
      priceRevealed: false,
      winners: [],
      awarded: false,
    };
    state.feud = null;
    state.herd = null;
    state.ml = null;
  }

  state.round = state.questionIndex + 1;
}

/* ---------- reducer ---------- */

export function applyAction(
  state: SessionState,
  action: Action,
  bank: QuestionBank,
  now: number,
): SessionState {
  const next: SessionState = structuredClone(state);

  switch (action.type) {
    case "configure": {
      needPhase(next, ["LOBBY"]);
      const names = action.participants.map((p) => p.name.trim()).filter(Boolean);
      if (names.length < 2) fail("At least two participants are required");

      const teams: Team[] = action.teams
        ? [
            { id: "t1", name: action.teams[0].trim() },
            { id: "t2", name: action.teams[1].trim() },
          ]
        : [];

      next.teams = teams;
      next.participants = action.participants.slice(0, names.length).map((p, index) => ({
        id: `p${index + 1}`,
        name: p.name.trim(),
        teamId: teams.length ? ((p.team ?? (index % 2 === 0 ? 0 : 1)) === 0 ? "t1" : "t2") : null,
      }));
      next.scores = emptyScores(next.participants, next.teams);
      next.config = configSchema.parse({ ...next.config, ...(action.config ?? {}) });
      break;
    }

    case "select_game": {
      needPhase(next, ["LOBBY"]);
      const questions = questionsFor(bank, action.game);
      if (questions.length === 0) fail("No questions loaded for that game");
      if (action.game === "family_feud" && next.teams.length !== 2) {
        fail("Family Feud needs two teams — set team names in setup");
      }
      next.game = action.game;
      next.phase = "GAME_INTRO";
      next.questionIndex = 0;
      next.round = 0;
      next.status = "active";
      next.roundAwards = [];
      next.questionOrder = (
        next.config.shuffleQuestions ? shuffled(questions) : questions
      ).map((question) => question.id);
      next.scores = emptyScores(next.participants, next.teams);
      next.feud = null;
      next.herd = null;
      next.ml = null;
      next.pir = null;
      next.usedQuestionIds = [];
      next.timer = null;
      break;
    }

    case "start_round": {
      needPhase(next, ["GAME_INTRO", "ROUND_READY"]);
      if (!next.game) fail("Select a game first");
      const questions = questionsFor(bank, next.game);
      const wanted = next.questionOrder[next.questionIndex];
      const question =
        questions.find((item) => item.id === wanted) ?? questions[next.questionIndex];
      if (!question) fail("No more questions — end the game");
      initGameState(next, question);
      next.phase = "QUESTION_ACTIVE";
      next.paused = false;
      next.status = "active";
      next.timer = null;
      next.roundAwards = [];
      break;
    }

    case "begin_answering": {
      needPhase(next, ["QUESTION_ACTIVE"]);
      needGame(next, "herd_mentality");
      next.phase = "ANSWERING";
      break;
    }

    case "reveal": {
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING"]);
      if (next.game === "family_feud") {
        fail("A Feud round ends when the board is clear or both teams are out");
      }
      if (next.game === "herd_mentality") {
        const herd = next.herd;
        if (!herd) fail("No herd round in progress");
        const result = computeHerdResult(herd, next);
        herd.result = result;
        if (!herd.awarded) {
          for (const id of result.winners) addPoints(next, "participant", id, result.points);
          herd.awarded = true;
        }
        next.phase = "REVEAL";
        break;
      }
      if (next.game === "whos_most_likely") {
        const ml = next.ml;
        if (!ml) fail("No round in progress");
        const max = Math.max(0, ...Object.values(ml.votes));
        ml.winners =
          max > 0
            ? Object.entries(ml.votes)
                .filter(([, votes]) => votes === max)
                .map(([id]) => id)
            : [];
        ml.revealed = true;
        if (!ml.awarded && next.config.mlMode === "competitive") {
          for (const id of ml.winners) addPoints(next, "participant", id, next.config.mlPoints);
          ml.awarded = true;
        }
        next.phase = "REVEAL";
        break;
      }
      const pir = next.pir;
      if (!pir) fail("No price round in progress");
      pir.guessesRevealed = true;
      pir.locked = true;
      next.phase = "REVEAL";
      break;
    }

    case "round_result": {
      needPhase(next, ["REVEAL"]);
      next.phase = "ROUND_RESULT";
      break;
    }

    case "next_round": {
      needPhase(next, ["ROUND_RESULT"]);
      if (!next.game) fail("No game");
      if (next.game === "family_feud" && next.feud?.ended && !next.feud.awarded) {
        fail("Award the pot before moving to the next round");
      }
      const questions = questionsFor(bank, next.game);
      if (next.questionIndex + 1 >= (next.questionOrder.length || questions.length)) {
        finishGame(next, now);
        break;
      }
      next.questionIndex += 1;
      next.round = next.questionIndex + 1;
      next.phase = "ROUND_READY";
      next.timer = null;
      next.roundAwards = [];
      break;
    }

    case "skip_question": {
      if (!next.game) fail("No game");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING", "REVEAL", "ROUND_READY", "ROUND_RESULT"]);
      if (next.game === "family_feud" && next.feud?.ended && !next.feud.awarded) {
        fail("Award the pot before skipping the round");
      }
      const questions = questionsFor(bank, next.game);
      if (next.questionIndex + 1 >= (next.questionOrder.length || questions.length)) {
        finishGame(next, now);
        break;
      }
      next.questionIndex += 1;
      next.round = next.questionIndex + 1;
      next.phase = "ROUND_READY";
      next.feud = null;
      next.herd = null;
      next.ml = null;
      next.pir = null;
      next.timer = null;
      next.roundAwards = [];
      break;
    }

    case "end_game": {
      if (!next.game) fail("No game");
      if (next.phase === "GAME_RESULT") break;
      finishGame(next, now);
      break;
    }

    case "back_to_lobby": {
      needPhase(next, ["GAME_RESULT"]);
      next.phase = "LOBBY";
      next.status = "lobby";
      next.game = null;
      next.feud = null;
      next.herd = null;
      next.ml = null;
      next.pir = null;
      next.round = 0;
      next.questionIndex = 0;
      next.paused = false;
      next.timer = null;
      break;
    }

    case "set_paused": {
      next.paused = action.paused;
      break;
    }

    case "set_timer": {
      if (action.seconds <= 0) {
        next.timer = null;
        break;
      }
      next.timer = {
        endsAt: now + action.seconds * 1000,
        seconds: action.seconds,
        label: action.label || "Time",
      };
      break;
    }

    case "clear_timer": {
      next.timer = null;
      break;
    }

    case "edit_score": {
      const bucket = action.kind === "participant" ? next.scores.participants : next.scores.teams;
      if (!(action.id in bucket)) fail("Unknown score holder");
      bucket[action.id] = action.value;
      break;
    }

    case "restart_round": {
      if (!next.game) fail("No game");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING", "REVEAL", "ROUND_RESULT"]);
      // rolling back points credited during this round keeps restarts honest
      for (const award of next.roundAwards) {
        const bucket =
          award.kind === "participant" ? next.scores.participants : next.scores.teams;
        bucket[award.id] = Math.max(0, (bucket[award.id] ?? 0) - award.points);
      }
      next.roundAwards = [];
      next.phase = "ROUND_READY";
      next.feud = null;
      next.herd = null;
      next.ml = null;
      next.pir = null;
      next.timer = null;
      break;
    }

    case "reset_session": {
      next.phase = "LOBBY";
      next.status = "lobby";
      next.game = null;
      next.round = 0;
      next.questionIndex = 0;
      next.usedQuestionIds = [];
      next.questionOrder = [];
      next.feud = null;
      next.herd = null;
      next.ml = null;
      next.pir = null;
      next.timer = null;
      next.paused = false;
      next.results = [];
      next.roundAwards = [];
      next.scores = emptyScores(next.participants, next.teams);
      break;
    }

    /* ---- Family Feud ---- */

    case "feud_reveal": {
      needGame(next, "family_feud");
      needPhase(next, ["QUESTION_ACTIVE"]);
      const feud = next.feud;
      const question = feudQuestionOf(next, bank);
      if (!feud || !question) fail("No Feud round");
      if (feud.ended) fail("The round is already over");
      const active = feud.activeTeamId;
      if ((feud.strikes[active] ?? 0) >= next.config.strikeLimit) {
        fail("That team is out of the round");
      }
      const answer = question.answers.find((item) => item.id === action.answerId);
      if (!answer) fail("Unknown answer");
      if (feud.revealed.includes(answer.id)) fail("Answer already revealed");

      feud.revealed = [...feud.revealed, answer.id];
      feud.credited[answer.id] = active;
      feud.pot += answer.points;

      if (feud.revealed.length >= question.answers.length) {
        finishFeudRound(next, bank, "answers_exhausted");
      } else {
        advanceFeudTurn(next);
      }
      break;
    }

    case "feud_strike": {
      needGame(next, "family_feud");
      needPhase(next, ["QUESTION_ACTIVE"]);
      const feud = next.feud;
      if (!feud) fail("No Feud round");
      if (feud.ended) fail("The round is already over");

      const [a, b] = teamIds(next);
      const team = action.teamId ?? feud.activeTeamId;
      if (team !== a && team !== b) fail("Unknown team");
      const current = feud.strikes[team] ?? 0;

      if (action.delta === -1) {
        feud.strikes[team] = Math.max(0, current - 1);
        break;
      }

      if (current >= next.config.strikeLimit) fail("That team is already out");
      feud.strikes[team] = current + 1;

      const alive = [a, b].filter((id) => (feud.strikes[id] ?? 0) < next.config.strikeLimit);
      if (alive.length === 0) {
        finishFeudRound(next, bank, "both_eliminated");
      } else if (alive.length === 1) {
        // One team is out; the survivor keeps guessing alone.
        feud.activeTeamId = alive[0] ?? feud.activeTeamId;
      } else if (team === feud.activeTeamId) {
        advanceFeudTurn(next);
      }
      break;
    }

    case "feud_award": {
      needGame(next, "family_feud");
      const feud = next.feud;
      if (!feud) fail("No Feud round");
      if (!feud.ended) fail("Finish the round before awarding the pot");
      if (feud.awarded) fail("The pot has already been awarded");

      const [a, b] = teamIds(next);
      const winner = action.teamId ?? feud.outcome?.winnerTeamId ?? null;
      if (!winner || (winner !== a && winner !== b)) {
        fail("Choose which team takes the pot");
      }

      addPoints(next, "team", winner, feud.pot * next.config.roundMultiplier);
      feud.awarded = true;
      feud.awardedTo = winner;
      break;
    }

    /* ---- Herd Mentality ---- */

    case "herd_set_answer": {
      needGame(next, "herd_mentality");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING"]);
      const herd = next.herd;
      if (!herd) fail("No herd round");
      if (!next.participants.some((p) => p.id === action.participantId)) fail("Unknown participant");
      herd.answers[action.participantId] = action.text;
      break;
    }

    case "herd_merge": {
      needGame(next, "herd_mentality");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING", "REVEAL"]);
      const herd = next.herd;
      if (!herd) fail("No herd round");
      if (herd.awarded) fail("Scores already awarded — restart the round to regroup");
      const from = normalizeAnswer(action.from);
      const to = normalizeAnswer(action.to);
      if (!from || !to) fail("Empty answer key");
      if (from === to) break;
      // avoid cycles
      let cursor = to;
      const seen = new Set<string>();
      for (;;) {
        const hop = herd.merges[cursor];
        if (!hop || seen.has(cursor)) break;
        seen.add(cursor);
        cursor = hop;
      }
      if (cursor === from) fail("That merge would create a loop");
      herd.merges[from] = to;
      if (herd.result) herd.result = computeHerdResult(herd, next);
      break;
    }

    case "herd_unmerge": {
      needGame(next, "herd_mentality");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING", "REVEAL"]);
      const herd = next.herd;
      if (!herd) fail("No herd round");
      if (herd.awarded) fail("Scores already awarded — restart the round to regroup");
      delete herd.merges[normalizeAnswer(action.key)];
      if (herd.result) herd.result = computeHerdResult(herd, next);
      break;
    }

    case "herd_set_pink_cow": {
      needGame(next, "herd_mentality");
      const herd = next.herd;
      if (!herd) fail("No herd round");
      if (!next.config.pinkCowEnabled) fail("Pink Cow is disabled in settings");
      if (action.participantId && !next.participants.some((p) => p.id === action.participantId)) {
        fail("Unknown participant");
      }
      herd.pinkCow = action.participantId;
      break;
    }

    /* ---- Who's Most Likely ---- */

    case "ml_set_votes": {
      needGame(next, "whos_most_likely");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING"]);
      const ml = next.ml;
      if (!ml) fail("No round");
      if (ml.revealed) fail("Votes already revealed");
      if (!next.participants.some((p) => p.id === action.participantId)) fail("Unknown participant");
      ml.votes[action.participantId] = action.votes;
      break;
    }

    case "ml_clear_votes": {
      needGame(next, "whos_most_likely");
      needPhase(next, ["QUESTION_ACTIVE", "ANSWERING"]);
      const ml = next.ml;
      if (!ml) fail("No round");
      if (ml.revealed) fail("Votes already revealed");
      for (const key of Object.keys(ml.votes)) ml.votes[key] = 0;
      break;
    }

    /* ---- Price Is Right ---- */

    case "pir_set_guess": {
      needGame(next, "price_is_right");
      needPhase(next, ["QUESTION_ACTIVE"]);
      const pir = next.pir;
      if (!pir) fail("No price round");
      if (pir.locked) fail("Guesses are locked");
      if (!(action.entityId in pir.guesses)) fail("Unknown guesser");
      pir.guesses[action.entityId] = action.value;
      break;
    }

    case "pir_lock": {
      needGame(next, "price_is_right");
      needPhase(next, ["QUESTION_ACTIVE"]);
      const pir = next.pir;
      if (!pir) fail("No price round");
      pir.locked = !pir.locked;
      break;
    }

    case "pir_reveal_price": {
      needGame(next, "price_is_right");
      needPhase(next, ["REVEAL"]);
      const pir = next.pir;
      const question = currentQuestion(next, bank) as PriceQuestion | null;
      if (!pir || !question || question.game !== "price_is_right") fail("No price round");
      if (pir.priceRevealed) fail("Price already revealed");
      pir.priceRevealed = true;
      pir.winners = computePriceWinners(next, question.actualPrice);
      if (!pir.awarded) {
        const kind = next.config.pirMode === "team" ? "team" : "participant";
        for (const id of pir.winners) addPoints(next, kind, id, next.config.pirPoints);
        pir.awarded = true;
      }
      break;
    }

    default: {
      const exhaustive: never = action;
      fail(`Unhandled action ${JSON.stringify(exhaustive)}`);
    }
  }

  next.updatedAt = now;
  return next;
}

function finishGame(state: SessionState, now: number) {
  if (!state.game) return;
  const standings = standingsFor(state);
  state.results = [
    ...state.results,
    { game: state.game, round: state.round, standings, at: now },
  ];
  state.phase = "GAME_RESULT";
  state.status = "ended";
  state.paused = false;
  state.timer = null;
}

/* ---------- projection ---------- */

function publicAnswers(question: FeudQuestion, revealed: string[]): PublicAnswer[] {
  return question.answers.map((answer) => {
    const isRevealed = revealed.includes(answer.id);
    return {
      id: answer.id,
      text: isRevealed ? answer.text : null,
      points: isRevealed ? answer.points : null,
      revealed: isRevealed,
    };
  });
}

export function projectPublic(state: SessionState, bank: QuestionBank): PublicState {
  const question = currentQuestion(state, bank);
  const showQuestion = state.phase !== "LOBBY" && question !== null;

  let pubQuestion: PublicState["question"] = null;
  if (showQuestion && question) {
    if (question.game === "family_feud") {
      pubQuestion = {
        game: question.game,
        text: question.question,
        answers: publicAnswers(question, state.feud?.revealed ?? []),
      };
    } else if (question.game === "price_is_right") {
      const revealed = state.pir?.priceRevealed ?? false;
      pubQuestion = {
        game: question.game,
        text: question.item,
        item: question.item,
        description: question.description,
        image: question.image,
        currency: state.config.currency || question.currency,
        priceUnit: question.priceUnit,
        actualPrice: revealed ? question.actualPrice : null,
      };
    } else {
      pubQuestion = { game: question.game, text: question.question };
    }
  }

  const feud = state.feud
    ? {
        activeTeamId: state.feud.activeTeamId,
        strikes: state.feud.strikes,
        strikeLimit: state.config.strikeLimit,
        pot: state.feud.pot,
        awarded: state.feud.awarded,
        awardedTo: state.feud.awardedTo,
        ended: state.feud.ended,
        outcome: state.feud.outcome,
      }
    : null;

  const herd = state.herd
    ? {
        answeredCount: Object.values(state.herd.answers).filter((a) => a.trim()).length,
        totalPlayers: state.participants.length,
        pinkCow: state.config.pinkCowEnabled ? state.herd.pinkCow : null,
        result: state.phase === "REVEAL" || state.phase === "ROUND_RESULT" ? state.herd.result : null,
      }
    : null;

  const ml = state.ml
    ? {
        voteCount: Object.values(state.ml.votes).reduce((a, b) => a + b, 0),
        revealed: state.ml.revealed,
        winners: state.ml.revealed ? state.ml.winners : [],
        votes: state.ml.revealed
          ? state.participants.map((p) => ({
              participantId: p.id,
              votes: state.ml?.votes[p.id] ?? 0,
            }))
          : null,
      }
    : null;

  const pir = state.pir
    ? {
        guesses: state.pir.guessesRevealed
          ? Object.entries(state.pir.guesses).map(([entityId, value]) => ({ entityId, value }))
          : null,
        locked: state.pir.locked,
        priceRevealed: state.pir.priceRevealed,
        winners: state.pir.winners,
        mode: state.config.pirMode,
      }
    : null;

  return {
    code: state.code,
    status: state.status,
    phase: state.phase,
    paused: state.paused,
    game: state.game,
    round: state.round,
    participants: state.participants,
    teams: state.teams,
    scores: state.scores,
    timer: state.timer,
    question: pubQuestion,
    feud,
    herd,
    ml,
    pir,
    results: state.results,
    updatedAt: state.updatedAt,
  };
}
