import { describe, expect, test } from "bun:test";
import {
  type Action,
  type FeudQuestion,
  type QuestionBank,
  type SessionState,
  defaultConfig,
} from "../src/lib/types";
import { RULES } from "../src/rules/slides";
import { EngineError, applyAction, createSession, projectPublic, rankPriceGuesses } from "../src/engine/engine";
import { herdGroups, normalizeAnswer } from "../src/lib/herd";
import engineBank from "./fixtures/engine-bank.json";
import { loadQuestionBank } from "../src/questions/bank";

const bank: QuestionBank = loadQuestionBank(engineBank);

const NAMES = ["Asha", "Ravi", "Meera", "Vikram", "Nisha", "Arjun", "Priya", "Karan"];
const TEAMS: [string, string] = ["Bride's Family", "Groom's Family"];

let clock = 1_000;
const tick = () => (clock += 10);

function session(overrides: Partial<SessionState["config"]> = {}) {
  clock = 1_000;
  return createSession(
    { names: NAMES, config: { ...defaultConfig, ...overrides } },
    "TEST",
    clock,
  );
}

/** Family Feud teams are configured inside the game, not in setup. */
function withFeudTeams(state: SessionState, bankOverride?: QuestionBank): SessionState {
  const assignment = Object.fromEntries(
    state.participants.map((person, index) => [person.id, index < 4 ? 0 : 1]),
  );
  const action: Action = {
    type: "feud_teams",
    names: ["Bride's Family", "Groom's Family"],
    assignment,
  };
  return bankOverride
    ? applyAction(state, action, bankOverride, tick(), () => 0)
    : act(state, action);
}

function act(state: SessionState, action: Action): SessionState {
  return applyAction(state, action, bank, tick(), () => 0);
}

function startGame(game: SessionState["game"], overrides: Partial<SessionState["config"]> = {}) {
  let s = session(overrides);
  s = act(s, { type: "select_game", game: game as NonNullable<typeof game> });
  s = act(s, { type: "rules_finish" });
  if (game === "family_feud") s = withFeudTeams(s);
  s = act(s, { type: "start_round" });
  return s;
}

const expectEngineError = (fn: () => unknown) => {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(EngineError);
    return error as EngineError;
  }
  throw new Error("expected an EngineError");
};

describe("session lifecycle", () => {
  test("starts in the lobby with players only and no teams", () => {
    const s = session();
    expect(s.phase).toBe("LOBBY");
    expect(s.participants).toHaveLength(8);
    expect(s.participants[0]).toMatchObject({ name: "Asha", teamId: null });
    expect(s.teams).toEqual([]);
    expect(Object.values(s.scores.participants)).toEqual(Array(8).fill(0));
  });

  test("rejects out-of-phase transitions", () => {
    const s = session();
    expectEngineError(() => act(s, { type: "start_round" }));
    expectEngineError(() => act(s, { type: "reveal" }));
  });

  test("family feud teams are created inside the game from the roster", () => {
    let s = act(session(), { type: "select_game", game: "family_feud" });
    s = act(s, { type: "rules_finish" });
    expect(s.teams).toEqual([]);
    expectEngineError(() => act(s, { type: "start_round" }));

    s = withFeudTeams(s);
    expect(s.teams.map((team) => team.name)).toEqual(["Bride's Family", "Groom's Family"]);
    expect(s.participants.slice(0, 4).every((person) => person.teamId === "t1")).toBe(true);
    expect(s.participants.slice(4).every((person) => person.teamId === "t2")).toBe(true);
    s = act(s, { type: "start_round" });
    expect(s.phase).toBe("QUESTION_ACTIVE");
  });

  test("configure replaces players and resets team state", () => {
    const s = act(session(), {
      type: "configure",
      participants: [{ name: "One" }, { name: "Two" }, { name: "Three" }],
    });
    expect(s.participants.map((p) => p.name)).toEqual(["One", "Two", "Three"]);
    expect(s.participants.every((p) => p.teamId === null)).toBe(true);
    expect(s.teams).toEqual([]);
    expect(s.scores.participants.p3).toBe(0);
  });
});

describe("rules", () => {
  const openRules = () => act(session(), { type: "select_game", game: "family_feud" });

  test("selecting a game opens the rules at the first slide", () => {
    const s = openRules();
    expect(s.phase).toBe("RULES");
    expect(s.rulesSlide).toBe(0);
    expect(s.rulesReturn).toBeNull();
  });

  test("slides advance and clamp at both ends", () => {
    let s = openRules();
    s = act(s, { type: "rules_prev" });
    expect(s.rulesSlide).toBe(0);

    for (let i = 0; i < 10; i += 1) s = act(s, { type: "rules_next" });
    expect(s.rulesSlide).toBe(RULES.family_feud.length - 1);
  });

  test("finishing rules moves on to the game intro and resets the slide", () => {
    const s = act(openRules(), { type: "rules_finish" });
    expect(s.phase).toBe("GAME_INTRO");
    expect(s.rulesSlide).toBe(0);
    expect(s.rulesReturn).toBeNull();
  });

  test("skipping rules jumps straight to the round", () => {
    const s = act(openRules(), { type: "rules_skip" });
    expect(s.phase).toBe("ROUND_READY");
    expect(s.rulesReturn).toBeNull();
  });

  test("skipping reopened rules returns to the round in progress", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "open_rules" });
    s = act(s, { type: "rules_skip" });
    expect(s.phase).toBe("QUESTION_ACTIVE");
  });

  test("rules cannot be opened from the lobby", () => {
    expectEngineError(() => act(session(), { type: "open_rules" }));
  });

  test("reopening rules keeps the round intact and returns to it", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    const before = { revealed: s.feud?.revealed, scores: { ...s.scores.teams } };

    s = act(s, { type: "open_rules" });
    expect(s.phase).toBe("RULES");
    expect(s.rulesReturn).toBe("QUESTION_ACTIVE");

    s = act(s, { type: "rules_next" });
    const pub = projectPublic(s, bank);
    expect(pub.rulesSlide).toBe(1);

    s = act(s, { type: "rules_finish" });
    expect(s.phase).toBe("QUESTION_ACTIVE");
    expect(s.feud?.revealed).toEqual(before.revealed!);
    expect(s.scores.teams).toEqual(before.scores);
  });

  test("rules reopen from the round result as well", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    s = act(s, { type: "feud_reveal", answerId: "a3" });
    s = act(s, { type: "feud_reveal", answerId: "a4" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "open_rules" });
    s = act(s, { type: "rules_finish" });
    expect(s.phase).toBe("ROUND_RESULT");
  });
});

describe("question order", () => {
  const answers = [34, 27, 19, 12, 8];
  const corpus: QuestionBank = {
    ...bank,
    family_feud: Array.from({ length: 13 }, (_, index) => ({
      id: `ff-${index + 1}`,
      game: "family_feud" as const,
      question: `Question ${index + 1}`,
      hindi: `Sawaal ${index + 1}`,
      answers: answers.map((points, answerIndex) => ({
        id: `a${answerIndex + 1}`,
        text: `Answer ${answerIndex + 1}`,
        hindi: `Jawab ${answerIndex + 1}`,
        points,
      })),
    })),
  };

  test("a new game samples ten unique questions", () => {
    const s = applyAction(session(), { type: "select_game", game: "family_feud" }, corpus, tick());
    expect(s.questionOrder).toHaveLength(10);
    expect(new Set(s.questionOrder).size).toBe(10);
    expect(s.questionOrder.every((id) => corpus.family_feud.some((q) => q.id === id))).toBe(true);
  });

  test("the selected order survives rounds and is not public", () => {
    let s = applyAction(session(), { type: "select_game", game: "family_feud" }, corpus, tick());
    const order = [...s.questionOrder];
    s = applyAction(s, { type: "rules_finish" }, corpus, tick());
    s = withFeudTeams(s, corpus);
    s = applyAction(s, { type: "start_round" }, corpus, tick());
    expect(s.questionOrder).toEqual(order);
    expect(Object.keys(projectPublic(s, corpus))).not.toContain("questionOrder");
  });

  test("Price Is Right mixes cheap and expensive products for 10, 15 or 20 rounds", () => {
    const products = Array.from({ length: 26 }, (_, index) => ({
      id: `PIR-${index + 1}`,
      game: "price_is_right" as const,
      item: `Item ${index + 1}`,
      description: `Description ${index + 1}`,
      image: `products/pir-${index + 1}.jpg`,
      actualPrice: (index + 1) * 100,
      currency: "INR",
      priceUnit: "item",
    }));
    const pirBank: QuestionBank = { ...bank, price_is_right: products };

    for (const rounds of [10, 15, 20] as const) {
      const s = applyAction(
        session({ roundsPerGame: rounds }),
        { type: "select_game", game: "price_is_right" },
        pirBank,
        tick(),
        () => 0,
      );
      expect(s.questionOrder).toHaveLength(rounds);
      expect(new Set(s.questionOrder).size).toBe(rounds);
      const prices = s.questionOrder
        .map((id) => products.find((product) => product.id === id)?.actualPrice ?? 0)
        .sort((a, b) => a - b);
      // Cheap (≤900), mid (≤1800) and expensive thirds all appear.
      expect(prices.filter((price) => price <= 900).length).toBeGreaterThanOrEqual(3);
      expect(prices.filter((price) => price > 900 && price <= 1800).length).toBeGreaterThanOrEqual(
        rounds === 10 ? 3 : 5,
      );
      expect(prices.filter((price) => price > 1800).length).toBeGreaterThanOrEqual(
        rounds === 10 ? 3 : 5,
      );
    }
  });

  test("other games keep ten rounds even when the setting says otherwise", () => {
    const answers = [34, 27, 19, 12, 8];
    const corpus: QuestionBank = {
      ...bank,
      family_feud: Array.from({ length: 26 }, (_, index) => ({
        id: `ff-${index + 1}`,
        game: "family_feud" as const,
        question: `Question ${index + 1}`,
        hindi: `Sawaal ${index + 1}`,
        answers: answers.map((points, answerIndex) => ({
          id: `a${answerIndex + 1}`,
          text: `Answer ${answerIndex + 1}`,
          hindi: `Jawab ${answerIndex + 1}`,
          points,
        })),
      })),
    };
    const s = applyAction(
      session({ roundsPerGame: 20 }),
      { type: "select_game", game: "family_feud" },
      corpus,
      tick(),
      () => 0,
    );
    expect(s.questionOrder).toHaveLength(10);
  });

  test("the bank uses every question when fewer than ten exist", () => {
    const s = act(session(), { type: "select_game", game: "family_feud" });
    expect(s.questionOrder).toHaveLength(bank.family_feud.length);
    expect(new Set(s.questionOrder).size).toBe(bank.family_feud.length);
  });

  test("an empty bank blocks the game", () => {
    const empty: QuestionBank = { ...bank, family_feud: [] };
    expectEngineError(() =>
      applyAction(session(), { type: "select_game", game: "family_feud" }, empty, tick()),
    );
  });
});

describe("family feud", () => {
  const feudQuestion: FeudQuestion = {
    id: "ff-main",
    game: "family_feud",
    question: "Five answers?",
    hindi: "Paanch jawaab?",
    answers: [
      { id: "a1", text: "One", hindi: "Ek", points: 40 },
      { id: "a2", text: "Two", hindi: "Do", points: 30 },
      { id: "a3", text: "Three", hindi: "Teen", points: 20 },
      { id: "a4", text: "Four", hindi: "Chaar", points: 6 },
      { id: "a5", text: "Five", hindi: "Paanch", points: 4 },
    ],
  };
  const feudBank: QuestionBank = { ...bank, family_feud: [feudQuestion, ...bank.family_feud] };

  const startWith = (questionBank: QuestionBank) => {
    let s = applyAction(session(), { type: "select_game", game: "family_feud" }, questionBank, tick(), () => 0);
    s = applyAction(s, { type: "rules_finish" }, questionBank, tick(), () => 0);
    s = withFeudTeams(s, questionBank);
    s = applyAction(s, { type: "start_round" }, questionBank, tick(), () => 0);
    return s;
  };

  const onBank = (state: SessionState, action: Action, questionBank: QuestionBank) =>
    applyAction(state, action, questionBank, tick(), () => 0);

  test("a correct answer scores immediately and keeps the turn", () => {
    let s = startWith(feudBank);
    expect(s.feud?.activeTeamId).toBe("t1");

    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank);
    expect(s.scores.teams.t1).toBe(40);
    expect(s.scores.teams.t2).toBe(0);
    expect(s.feud?.credited.a1).toBe("t1");
    expect(s.feud?.activeTeamId).toBe("t1");
    expect(s.feud?.strikes).toBe(0);

    s = onBank(s, { type: "feud_reveal", answerId: "a2" }, feudBank);
    expect(s.scores.teams.t1).toBe(70);
    expect(s.feud?.activeTeamId).toBe("t1");
  });

  test("two strikes pass the turn and reset the strikes", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t1");
    expect(s.feud?.strikes).toBe(1);

    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t2");
    expect(s.feud?.strikes).toBe(0);
    expect(s.feud?.turnsPlayed).toBe(2);
    expect(s.feud?.ended).toBe(false);

    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t2");
    expect(s.feud?.strikes).toBe(1);
  });

  test("the round closes after both families have had a turn", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank);
    expect(s.scores.teams.t1).toBe(40);

    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t2");

    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);

    expect(s.feud?.ended).toBe(true);
    expect(s.phase).toBe("REVEAL");
    expect(s.feud?.revealed.sort()).toEqual(["a1", "a2", "a3", "a4", "a5"]);
    // Only the guessed answer scored; the reveal is for the board, not points.
    expect(s.scores.teams).toEqual({ t1: 40, t2: 0 });
    expect(Object.keys(s.feud?.credited ?? {})).toEqual(["a1"]);
  });

  test("a correct guess on the new turn scores for that team", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t2");
    s = onBank(s, { type: "feud_reveal", answerId: "a3" }, feudBank);
    expect(s.scores.teams.t2).toBe(20);
    expect(s.scores.teams.t1).toBe(0);
    expect(s.feud?.activeTeamId).toBe("t2");
  });

  test("a strike can be corrected without changing the turn", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.strikes).toBe(1);
    s = onBank(s, { type: "feud_strike", delta: -1 }, feudBank);
    expect(s.feud?.strikes).toBe(0);
    expect(s.feud?.activeTeamId).toBe("t1");
    expect(s.phase).toBe("QUESTION_ACTIVE");
  });

  test("the round ends once every answer is on the board", () => {
    let s = startWith(feudBank);
    for (const answer of feudQuestion.answers.slice(0, 4)) {
      s = onBank(s, { type: "feud_reveal", answerId: answer.id }, feudBank);
    }
    expect(s.feud?.ended).toBe(false);
    expect(s.phase).toBe("QUESTION_ACTIVE");

    s = onBank(s, { type: "feud_reveal", answerId: "a5" }, feudBank);
    expect(s.feud?.ended).toBe(true);
    expect(s.phase).toBe("REVEAL");
    expect(s.scores.teams.t1).toBe(100);
    expect(Object.keys(s.feud ?? {})).not.toContain("pot");

    // No award step: the round result is available straight away.
    expectEngineError(() => onBank(s, { type: "next_round" }, feudBank));
    s = onBank(s, { type: "round_result" }, feudBank);
    s = onBank(s, { type: "next_round" }, feudBank);
    expect(s.phase).toBe("ROUND_READY");
  });

  test("the starting team alternates each round and scores carry over", () => {
    let s = startWith(feudBank);
    expect(s.feud?.startingTeamId).toBe("t1");
    for (const answer of feudQuestion.answers) {
      s = onBank(s, { type: "feud_reveal", answerId: answer.id }, feudBank);
    }
    s = onBank(s, { type: "round_result" }, feudBank);
    s = onBank(s, { type: "next_round" }, feudBank);
    s = onBank(s, { type: "start_round" }, feudBank);

    expect(s.feud?.startingTeamId).toBe("t2");
    expect(s.feud?.activeTeamId).toBe("t2");
    expect(s.scores.teams.t1).toBe(100);

    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank);
    expect(s.scores.teams.t2).toBe(40);
    expect(s.scores.teams.t1).toBe(100);
  });

  test("all five answers close the round before any strikes", () => {
    let s = startWith(feudBank);
    for (const answer of feudQuestion.answers) {
      s = onBank(s, { type: "feud_reveal", answerId: answer.id }, feudBank);
    }
    expect(s.feud?.ended).toBe(true);
    expect(s.feud?.turnsPlayed).toBe(1);
    expect(s.phase).toBe("REVEAL");
    expect(projectPublic(s, feudBank).feud?.roundPoints).toEqual({ t1: 100 });
  });

  test("the round summary counts guessed answers only", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank); // t1 +40
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank); // t2's turn
    s = onBank(s, { type: "feud_reveal", answerId: "a2" }, feudBank); // t2 +30
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank); // round ends

    const pub = projectPublic(s, feudBank);
    expect(pub.feud?.ended).toBe(true);
    expect(pub.feud?.roundPoints).toEqual({ t1: 40, t2: 30 });
    expect(pub.scores.teams).toEqual({ t1: 40, t2: 30 });
  });

  test("grace points award five to the active team without revealing or striking", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_grace" }, feudBank);

    expect(s.scores.teams).toEqual({ t1: 5, t2: 0 });
    expect(s.feud?.strikes).toBe(0);
    expect(s.feud?.revealed).toEqual([]);
    expect(s.feud?.activeTeamId).toBe("t1");
    expect(s.feud?.grace).toHaveLength(1);

    const pub = projectPublic(s, feudBank);
    expect(pub.feud?.roundPoints).toEqual({ t1: 5 });
    expect(pub.feud?.graceCount).toBe(1);
    expect(pub.feud?.graceTeamId).toBe("t1");
    expect(pub.question?.answers?.every((answer) => !answer.revealed)).toBe(true);

    // Projecting again (Firebase snapshots) does not duplicate the award.
    expect(projectPublic(s, feudBank).feud?.graceCount).toBe(1);
    expect(s.scores.teams.t1).toBe(5);
  });

  test("grace points stack and never count as a strike", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_grace" }, feudBank);
    s = onBank(s, { type: "feud_grace" }, feudBank);
    expect(s.scores.teams.t1).toBe(10);

    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.strikes).toBe(1);
    expect(s.feud?.activeTeamId).toBe("t1");
    expect(s.scores.teams.t1).toBe(10);

    s = onBank(s, { type: "feud_grace" }, feudBank);
    expect(s.scores.teams.t1).toBe(15);
    expect(s.feud?.strikes).toBe(1);
    expect(projectPublic(s, feudBank).feud?.graceCount).toBe(3);
  });

  test("grace points on the second family's turn credit the other team", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    expect(s.feud?.activeTeamId).toBe("t2");

    s = onBank(s, { type: "feud_grace" }, feudBank);
    expect(s.scores.teams).toEqual({ t1: 0, t2: 5 });
    expect(s.feud?.activeTeamId).toBe("t2");
    expect(s.feud?.strikes).toBe(0);
    expect(projectPublic(s, feudBank).feud?.roundPoints).toEqual({ t2: 5 });
  });

  test("grace points are refused outside an active turn", () => {
    let s = startWith(feudBank);
    for (const answer of feudQuestion.answers) {
      s = onBank(s, { type: "feud_reveal", answerId: answer.id }, feudBank);
    }
    expect(s.phase).toBe("REVEAL");
    expectEngineError(() => onBank(s, { type: "feud_grace" }, feudBank));

    s = onBank(s, { type: "round_result" }, feudBank);
    expectEngineError(() => onBank(s, { type: "feud_grace" }, feudBank));
  });

  test("grace points join the round summary and cumulative score", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank); // t1 +40
    s = onBank(s, { type: "feud_grace" }, feudBank);
    s = onBank(s, { type: "feud_grace" }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank); // t2's turn
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank);
    s = onBank(s, { type: "feud_strike", delta: 1 }, feudBank); // round closes

    const pub = projectPublic(s, feudBank);
    expect(pub.feud?.ended).toBe(true);
    expect(pub.feud?.roundPoints).toEqual({ t1: 50 });
    expect(s.scores.teams.t1).toBe(50);
    expect(s.scores.teams.t2).toBe(0);
  });

  test("grace points appear in the final standings", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_grace" });
    const total = bank.family_feud.length;
    for (let round = 0; round < total; round += 1) {
      if (round > 0) s = act(s, { type: "start_round" });
      const question = bank.family_feud.find((item) => item.id === s.feud?.questionId);
      if (!question) throw new Error("missing question");
      for (const answer of question.answers) {
        s = act(s, { type: "feud_reveal", answerId: answer.id });
      }
      s = act(s, { type: "round_result" });
      s = act(s, { type: "next_round" });
    }
    expect(s.phase).toBe("GAME_RESULT");
    // The opening family alternates, so Brides fully guess rounds 1, 3, …
    const official = bank.family_feud
      .filter((_, index) => index % 2 === 0)
      .reduce(
        (sum, question) => sum + question.answers.reduce((points, answer) => points + answer.points, 0),
        0,
      );
    const bride = s.results[0]?.standings.find((row) => row.label === "Bride's Family");
    expect(bride?.points).toBe(official + 5);
  });

  test("restarting a round rolls back grace points too", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_grace" }, feudBank);
    expect(s.scores.teams.t1).toBe(5);
    s = onBank(s, { type: "restart_round" }, feudBank);
    expect(s.scores.teams.t1).toBe(0);
    expect(s.phase).toBe("ROUND_READY");
  });

  test("the undo snapshot keeps the pre-grace score", () => {
    const before = startWith(feudBank);
    const after = onBank(before, { type: "feud_grace" }, feudBank);
    expect(before.scores.teams.t1).toBe(0);
    expect(before.feud?.grace).toEqual([]);
    expect(after.scores.teams.t1).toBe(5);
  });

  test("restarting a round rolls back its immediate points", () => {
    let s = startWith(feudBank);
    s = onBank(s, { type: "feud_reveal", answerId: "a1" }, feudBank);
    expect(s.scores.teams.t1).toBe(40);
    s = onBank(s, { type: "restart_round" }, feudBank);
    expect(s.scores.teams.t1).toBe(0);
    expect(s.phase).toBe("ROUND_READY");
    expect(s.feud).toBeNull();
  });

  test("game ends with cumulative team standings after the last question", () => {
    let s = startGame("family_feud");
    const total = bank.family_feud.length;
    for (let round = 0; round < total; round += 1) {
      if (round > 0) s = act(s, { type: "start_round" });
      const question = bank.family_feud.find((item) => item.id === s.feud?.questionId);
      if (!question) throw new Error("missing question");
      for (const answer of question.answers) {
        s = act(s, { type: "feud_reveal", answerId: answer.id });
      }
      s = act(s, { type: "round_result" });
      s = act(s, { type: "next_round" });
    }
    expect(s.phase).toBe("GAME_RESULT");
    expect(s.results).toHaveLength(1);
    const standings = s.results[0]?.standings ?? [];
    expect(standings.map((row) => row.label)).toEqual(["Bride's Family", "Groom's Family"]);
    expect(Math.max(...standings.map((row) => row.points))).toBeGreaterThan(0);
  });
});

describe("herd mentality", () => {
  const answer = (state: SessionState, id: string, text: string) =>
    act(state, { type: "herd_set_answer", participantId: id, text });

  test("normalisation folds case, punctuation and spacing", () => {
    expect(normalizeAnswer("  Paneer  Tikka!! ")).toBe("paneer tikka");
  });

  test("unique largest group scores; ties score nobody by default", () => {
    let s = startGame("herd_mentality");
    s = answer(s, "p1", "biryani");
    s = answer(s, "p2", "Biryani");
    s = answer(s, "p3", "biryani");
    s = answer(s, "p4", "paneer");
    s = answer(s, "p5", "paneer");
    s = answer(s, "p6", "dal");

    s = act(s, { type: "reveal" });
    expect(s.herd?.result?.groups[0]?.participantIds).toEqual(["p1", "p2", "p3"]);
    expect(s.herd?.result?.winners).toEqual(["p1", "p2", "p3"]);
    expect(s.scores.participants.p1).toBe(1);
    expect(s.scores.participants.p4).toBe(0);
  });

  test("ties award nobody unless configured, and merging can break the tie", () => {
    const setup = () => {
      let s = startGame("herd_mentality");
      s = answer(s, "p1", "samosa");
      s = answer(s, "p2", "samosa");
      s = answer(s, "p3", "kebab");
      s = answer(s, "p4", "kebab");
      return s;
    };

    const tie = act(setup(), { type: "reveal" });
    expect(tie.herd?.result?.tied).toBe(true);
    expect(tie.herd?.result?.winners).toEqual([]);
    expect(tie.scores.participants.p1).toBe(0);

    const merged = setup();
    const groups = herdGroups(merged.herd!, merged.participants);
    expect(groups).toHaveLength(2);

    let s = act(merged, { type: "herd_merge", from: "kebab", to: "samosa" });
    s = act(s, { type: "reveal" });
    expect(s.herd?.result?.winners).toEqual(["p1", "p2", "p3", "p4"]);
    expect(s.scores.participants.p4).toBe(1);
  });

  test("tieAwards configuration pays every tied group", () => {
    let s = startGame("herd_mentality", { herdTieAwards: true });
    s = answer(s, "p1", "tea");
    s = answer(s, "p2", "coffee");
    s = act(s, { type: "reveal" });
    expect(s.herd?.result?.tied).toBe(true);
    expect(s.herd?.result?.winners.sort()).toEqual(["p1", "p2"]);
    expect(s.scores.participants.p1).toBe(1);
    expect(s.scores.participants.p2).toBe(1);
  });

  test("merging after reveal moves points only when restarting", () => {
    let s = startGame("herd_mentality");
    s = answer(s, "p1", "a");
    s = answer(s, "p2", "b");
    s = act(s, { type: "reveal" });
    expectEngineError(() => act(s, { type: "herd_merge", from: "a", to: "b" }));
  });

  test("private answers never reach the public payload before reveal", () => {
    let s = startGame("herd_mentality");
    s = answer(s, "p1", "secret samosa");
    s = act(s, { type: "begin_answering" });
    const pub = JSON.stringify(projectPublic(s, bank));
    expect(pub).not.toContain("secret samosa");
    expect(projectPublic(s, bank).herd?.answeredCount).toBe(1);
  });

  test("pink cow is excluded from winning when configured", () => {
    let s = startGame("herd_mentality", { pinkCowEnabled: true, pinkCowBlocksWin: true });
    s = answer(s, "p1", "cake");
    s = act(s, { type: "herd_set_pink_cow", participantId: "p1" });
    s = act(s, { type: "reveal" });
    expect(s.scores.participants.p1).toBe(1);
    s = act(s, { type: "end_game" });
    const top = s.results[0]?.standings.find((row) => row.label === "Asha");
    expect(top).toMatchObject({ blocked: true, winner: false });
  });
});

describe("who's most likely", () => {
  test("highest vote count wins and ties list every leader", () => {
    let s = startGame("whos_most_likely");
    s = act(s, { type: "ml_set_votes", participantId: "p1", votes: 3 });
    s = act(s, { type: "ml_set_votes", participantId: "p2", votes: 3 });
    s = act(s, { type: "ml_set_votes", participantId: "p3", votes: 1 });
    s = act(s, { type: "reveal" });
    expect(s.ml?.winners).toEqual(["p1", "p2"]);
    expect(s.scores.participants.p1).toBe(0);
  });

  test("competitive mode awards each winner once", () => {
    let s = startGame("whos_most_likely", { mlMode: "competitive", mlPoints: 2 });
    s = act(s, { type: "ml_set_votes", participantId: "p1", votes: 4 });
    s = act(s, { type: "reveal" });
    expect(s.scores.participants.p1).toBe(2);
    expectEngineError(() => act(s, { type: "reveal" }));
  });

  test("vote tally is private until reveal", () => {
    let s = startGame("whos_most_likely");
    s = act(s, { type: "ml_set_votes", participantId: "p1", votes: 7 });
    const hidden = projectPublic(s, bank);
    expect(hidden.ml?.votes).toBeNull();

    s = act(s, { type: "reveal" });
    const shown = projectPublic(s, bank);
    expect(shown.ml?.votes?.find((row) => row.participantId === "p1")?.votes).toBe(7);
  });
});

describe("the price is right", () => {
  const guess = (state: SessionState, id: string, value: number) =>
    act(state, { type: "pir_set_guess", entityId: id, value });

  test("closest without going over wins", () => {
    let s = startGame("price_is_right", { pirPhoneMode: "off" });
    const price = bank.price_is_right[0]!.actualPrice;
    s = guess(s, "p1", Math.round(price * 0.8));
    s = guess(s, "p2", price + 100);
    s = guess(s, "p3", Math.round(price * 0.95));
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    expect(s.pir?.winners).toEqual(["p3"]);
    expect(s.scores.participants.p3).toBe(1);
  });

  test("when every guess is over, nearest price wins", () => {
    let s = startGame("price_is_right", { pirPhoneMode: "off" });
    const price = bank.price_is_right[0]!.actualPrice;
    s = guess(s, "p1", price + 500);
    s = guess(s, "p2", price + 50);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    expect(s.pir?.winners).toEqual(["p2"]);
  });

  test("ties award every equal winning guess", () => {
    let s = startGame("price_is_right", { pirPhoneMode: "off" });
    const price = bank.price_is_right[0]!.actualPrice;
    s = guess(s, "p1", 800);
    s = guess(s, "p2", 800);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    expect(s.pir?.winners.sort()).toEqual(["p1", "p2"]);
    expect(s.scores.participants.p1).toBe(1);
    expect(s.scores.participants.p2).toBe(1);
  });

  test("the price stays private until revealed, and guesses lock", () => {
    let s = startGame("price_is_right", { pirPhoneMode: "off" });
    s = guess(s, "p1", 900);
    const hidden = projectPublic(s, bank);
    expect(hidden.question?.actualPrice).toBeNull();
    expect(hidden.pir?.guesses).toBeNull();

    s = act(s, { type: "pir_lock" });
    expectEngineError(() => act(s, { type: "pir_set_guess", entityId: "p2", value: 5 }));
  });
});

describe("price phone entries", () => {
  const startParty = (mode: "teams" | "individual" = "teams") => {
    let s = session({ pirPhoneMode: mode });
    s = act(s, { type: "select_game", game: "price_is_right" });
    s = act(s, { type: "rules_skip" });
    s = act(s, { type: "start_round" });
    return s;
  };

  const join = (state: SessionState, slot: string, name: string) =>
    act(state, { type: "pir_team_add", teamId: slot, name });

  const guess = (state: SessionState, slot: string, value: number) =>
    act(state, { type: "pir_set_guess", entityId: slot, value });

  const revealed = (state: SessionState) => {
    let s = act(state, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    return s;
  };

  test("phone mode defaults to three teams and is fixed per game", () => {
    expect(startGame("price_is_right").pir?.party).toMatchObject({
      mode: "teams",
      capacity: 3,
    });
    expect(startGame("price_is_right", { pirPhoneMode: "off" }).pir?.party).toBeNull();
    expect(startGame("price_is_right", { pirPhoneMode: "teams" }).pir?.party).toMatchObject({
      mode: "teams",
      capacity: 3,
    });
    expect(
      startGame("price_is_right", { pirPhoneMode: "individual" }).pir?.party,
    ).toMatchObject({ mode: "individual", capacity: 6 });
  });

  test("entries are limited to their mode's slots", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = join(s, "t2", "Bravo");
    s = join(s, "t3", "Charlie");
    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(3);
    expectEngineError(() => join(s, "t4", "Delta"));
    expectEngineError(() => join(s, "p1", "Player one"));

    let individual = startParty("individual");
    for (const slot of ["p1", "p2", "p3", "p4", "p5", "p6"]) {
      individual = join(individual, slot, `Player ${slot}`);
    }
    expect(Object.keys(individual.pir?.party?.teams ?? {})).toHaveLength(6);
    expectEngineError(() => join(individual, "p7", "Player seven"));
    expectEngineError(() => join(individual, "t1", "Team one"));
  });

  test("ranking is pure distance with shared ranks for ties", () => {
    const podium = rankPriceGuesses({ a: 1400, b: 1500, c: 1600, d: 1450 }, 1500);
    expect(podium.map((entry) => [entry.entryId, entry.rank, entry.points])).toEqual([
      ["b", 1, 30],
      ["d", 2, 20],
      ["a", 3, 10],
      ["c", 3, 10],
    ]);
  });

  test("price reveal shows no scores; the leaderboard awards 30/20/10", () => {
    let s = startParty("individual");
    for (const slot of ["p1", "p2", "p3", "p4"]) s = join(s, slot, slot);
    s = guess(s, "p1", 1450);
    s = guess(s, "p2", 1500);
    s = guess(s, "p3", 1600);
    s = guess(s, "p4", 1450);

    s = revealed(s);
    expect(s.pir?.party?.priceRevealed).toBe(true);
    expect(s.pir?.party?.leaderboardRevealed).toBe(false);
    expect(Object.values(s.pir?.party?.scores ?? {})).toEqual([0, 0, 0, 0]);
    expect(projectPublic(s, bank).pir?.party?.podium).toEqual([]);

    s = act(s, { type: "pir_leaderboard" });
    expect(s.pir?.party?.leaderboardRevealed).toBe(true);
    expect(s.pir?.party?.podium.map((entry) => [entry.entryId, entry.rank, entry.points])).toEqual([
      ["p2", 1, 30],
      ["p1", 2, 20],
      ["p4", 2, 20],
      ["p3", 4, 0],
    ]);
    expect(s.pir?.party?.scores).toEqual({ p1: 20, p2: 30, p3: 0, p4: 20 });
    expectEngineError(() => act(s, { type: "pir_leaderboard" }));
  });

  test("guesses stay private until revealed, the price until its reveal", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = join(s, "t2", "Bravo");
    s = guess(s, "t1", 1200);
    s = guess(s, "t2", 1800);

    const before = projectPublic(s, bank);
    expect(before.pir?.party?.guesses).toBeNull();
    expect(before.question?.actualPrice).toBeNull();
    expect(before.pir?.party?.teams.find((team) => team.id === "t1")?.submitted).toBe(true);

    s = act(s, { type: "reveal" });
    const guesses = projectPublic(s, bank);
    expect(guesses.pir?.party?.guesses).toHaveLength(2);
    expect(guesses.question?.actualPrice).toBeNull();

    s = act(s, { type: "pir_reveal_price" });
    const price = projectPublic(s, bank);
    expect(price.question?.actualPrice).toBe(1500);
  });

  test("a late phone guess is ingested before the leaderboard", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = join(s, "t2", "Bravo");
    s = guess(s, "t1", 1500);
    s = revealed(s);

    // The Firebase snapshot for Bravo lands after the lock/reveal.
    s = guess(s, "t2", 1400);
    expect(s.pir?.party?.guesses.t2).toBe(1400);

    s = act(s, { type: "pir_leaderboard" });
    expect(s.pir?.party?.podium.map((entry) => [entry.entryId, entry.rank, entry.points])).toEqual([
      ["t1", 1, 30],
      ["t2", 2, 20],
    ]);
    expectEngineError(() => guess(s, "t2", 1600));
  });

  test("the final result lists the teams that played, not the roster", () => {
    let s = startParty("teams");
    const roster = s.participants.map((person) => person.name);
    s = join(s, "t1", "Alpha");
    s = join(s, "t2", "Bravo");
    s = guess(s, "t1", 1500);
    s = guess(s, "t2", 1400);
    s = revealed(s);
    s = act(s, { type: "pir_leaderboard" });
    s = act(s, { type: "end_game" });

    const standings = s.results.at(-1)?.standings ?? [];
    expect(standings.map((row) => [row.label, row.points, row.winner])).toEqual([
      ["Alpha", 30, true],
      ["Bravo", 20, false],
    ]);
    expect(standings.map((row) => row.label)).not.toEqual(roster);
  });

  test("undo, override and re-award work together", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = join(s, "t2", "Bravo");
    s = join(s, "t3", "Charlie");
    s = guess(s, "t1", 1400);
    s = guess(s, "t2", 1600);
    s = guess(s, "t3", 1500);

    s = revealed(s);
    s = act(s, { type: "pir_leaderboard" });
    expect(s.pir?.party?.scores).toEqual({ t1: 20, t2: 20, t3: 30 });

    s = act(s, { type: "pir_undo_award" });
    expect(s.pir?.party?.scores).toEqual({ t1: 0, t2: 0, t3: 0 });
    expect(s.pir?.party?.awarded).toBe(false);

    s = act(s, { type: "pir_override", teamIds: ["t1", "t2", "t3"] });
    s = act(s, { type: "pir_award" });
    expect(s.pir?.party?.scores).toEqual({ t1: 30, t2: 20, t3: 10 });
  });

  test("teams and totals survive the next round", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = guess(s, "t1", 1500);
    s = revealed(s);
    s = act(s, { type: "pir_leaderboard" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "next_round" });
    s = act(s, { type: "start_round" });

    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(1);
    expect(s.pir?.party?.scores.t1).toBe(30);
    expect(s.pir?.party?.guesses).toEqual({});
    expect(s.pir?.party?.podium).toEqual([]);
    expect(s.pir?.party?.leaderboardRevealed).toBe(false);
  });

  test("restarting a round takes back its podium points", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = guess(s, "t1", 1500);
    s = revealed(s);
    s = act(s, { type: "pir_leaderboard" });
    expect(s.pir?.party?.scores.t1).toBe(30);

    s = act(s, { type: "restart_round" });
    expect(s.pir?.party?.scores.t1).toBe(0);
    expect(s.pir?.party?.podium).toEqual([]);
    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(1);
  });

  test("a removed entry loses its guess and score", () => {
    let s = startParty("teams");
    s = join(s, "t1", "Alpha");
    s = guess(s, "t1", 1400);
    s = act(s, { type: "pir_team_remove", teamId: "t1" });
    expect(s.pir?.party?.teams.t1).toBeUndefined();
    expect(s.pir?.party?.scores.t1).toBeUndefined();
    expect(s.pir?.party?.guesses.t1).toBeUndefined();
  });
});

describe("projection", () => {
  test("lobby payload carries no question or game state", () => {
    const pub = projectPublic(session(), bank);
    expect(pub.question).toBeNull();
    expect(pub.feud).toBeNull();
    expect(JSON.stringify(pub)).not.toContain("biryani");
  });

  test("host payload keeps answers that the public payload hides", () => {
    const s = startGame("family_feud");
    const pub = JSON.stringify(projectPublic(s, bank));
    for (const answer of bank.family_feud[0]!.answers) {
      expect(pub).not.toContain(answer.text);
    }
  });
});
