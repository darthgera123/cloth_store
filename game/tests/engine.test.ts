import { describe, expect, test } from "bun:test";
import path from "node:path";
import {
  type Action,
  type FeudQuestion,
  type QuestionBank,
  type SessionState,
  defaultConfig,
} from "../src/lib/types";
import { RULES } from "../src/rules/slides";
import { EngineError, applyAction, createSession, projectPublic } from "../src/engine/engine";
import { herdGroups, normalizeAnswer } from "../src/lib/herd";
import { loadQuestionBank } from "../src/questions/bank";

const bank: QuestionBank = await loadQuestionBank(path.join(import.meta.dir, "../questions"));

const NAMES = ["Asha", "Ravi", "Meera", "Vikram", "Nisha", "Arjun", "Priya", "Karan"];
const TEAMS: [string, string] = ["Bride's Family", "Groom's Family"];

let clock = 1_000;
const tick = () => (clock += 10);

function session(overrides: Partial<SessionState["config"]> = {}) {
  clock = 1_000;
  return createSession(
    { names: NAMES, teams: TEAMS, config: { ...defaultConfig, ...overrides } },
    "TEST",
    clock,
  );
}

function act(state: SessionState, action: Action): SessionState {
  return applyAction(state, action, bank, tick());
}

function startGame(game: SessionState["game"], overrides: Partial<SessionState["config"]> = {}) {
  let s = session(overrides);
  s = act(s, { type: "select_game", game: game as NonNullable<typeof game> });
  s = act(s, { type: "rules_finish" });
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
  test("starts in the lobby with zeroed scores", () => {
    const s = session();
    expect(s.phase).toBe("LOBBY");
    expect(s.participants).toHaveLength(8);
    expect(s.participants[0]).toMatchObject({ name: "Asha", teamId: "t1" });
    expect(s.participants[1]).toMatchObject({ name: "Ravi", teamId: "t2" });
    expect(Object.values(s.scores.participants)).toEqual(Array(8).fill(0));
  });

  test("rejects out-of-phase transitions", () => {
    const s = session();
    expectEngineError(() => act(s, { type: "start_round" }));
    expectEngineError(() => act(s, { type: "reveal" }));
  });

  test("explicit team picks override the alternating default", () => {
    const s = createSession(
      {
        names: ["Pulkit", "Lavani", "Rajat", "Bindu"],
        teams: ["Bride's Family", "Groom's Family"],
        participantTeams: [1, 1, 0, 0],
      },
      "TEAM",
      clock,
    );
    expect(s.participants.map((person) => person.teamId)).toEqual(["t2", "t2", "t1", "t1"]);
  });

  test("configure replaces participants and keeps config valid", () => {
    const s = act(session(), {
      type: "configure",
      participants: [{ name: "One" }, { name: "Two" }, { name: "Three", team: 1 }],
      teams: ["A", "B"],
    });
    expect(s.participants.map((p) => p.name)).toEqual(["One", "Two", "Three"]);
    expect(s.participants[2]?.teamId).toBe("t2");
    expect(s.scores.participants.p3).toBe(0);

    const swapped = act(s, {
      type: "configure",
      participants: [
        { name: "One", team: 1 },
        { name: "Two", team: 0 },
        { name: "Three", team: 1 },
      ],
      teams: ["A", "B"],
    });
    expect(swapped.participants.map((person) => person.teamId)).toEqual(["t2", "t1", "t2"]);
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
    const before = { pot: s.feud?.pot, revealed: s.feud?.revealed, scores: { ...s.scores.teams } };

    s = act(s, { type: "open_rules" });
    expect(s.phase).toBe("RULES");
    expect(s.rulesReturn).toBe("QUESTION_ACTIVE");

    s = act(s, { type: "rules_next" });
    const pub = projectPublic(s, bank);
    expect(pub.rulesSlide).toBe(1);

    s = act(s, { type: "rules_finish" });
    expect(s.phase).toBe("QUESTION_ACTIVE");
    expect(s.feud?.pot).toBe(before.pot);
    expect(s.feud?.revealed).toEqual(before.revealed!);
    expect(s.scores.teams).toEqual(before.scores);
  });

  test("rules reopen from the round result as well", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    s = act(s, { type: "feud_reveal", answerId: "a3" });
    s = act(s, { type: "feud_reveal", answerId: "a4" });
    s = act(s, { type: "feud_award" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "open_rules" });
    s = act(s, { type: "rules_finish" });
    expect(s.phase).toBe("ROUND_RESULT");
  });
});

describe("question order", () => {
  test("shuffle keeps every question exactly once", () => {
    const s = act(session({ shuffleQuestions: true }), {
      type: "select_game",
      game: "family_feud",
    });
    expect(s.questionOrder.length).toBe(bank.family_feud.length);
    expect([...s.questionOrder].sort()).toEqual(
      bank.family_feud.map((question) => question.id).sort(),
    );
    expect(new Set(s.questionOrder).size).toBe(bank.family_feud.length);
  });
});

describe("family feud", () => {
  const tieQuestion: FeudQuestion = {
    id: "ff-tie",
    game: "family_feud",
    question: "Tie question?",
    answers: [
      { id: "a1", text: "One", points: 10 },
      { id: "a2", text: "Two", points: 10 },
    ],
  };
  const tieBank: QuestionBank = { ...bank, family_feud: [tieQuestion] };

  const startWith = (questionBank: QuestionBank) => {
    let s = act(session(), { type: "select_game", game: "family_feud" });
    s = applyAction(s, { type: "rules_finish" }, questionBank, tick());
    s = applyAction(s, { type: "start_round" }, questionBank, tick());
    return s;
  };

  test("correct answers build the pot without touching team scores", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });

    expect(s.feud?.pot).toBe(40);
    expect(s.scores.teams.t1).toBe(0);
    expect(s.scores.teams.t2).toBe(0);
    expect(s.feud?.credited.a1).toBe("t1");
    expect(s.phase).toBe("QUESTION_ACTIVE");
  });

  test("the default strike limit is two", () => {
    expect(session().config.strikeLimit).toBe(2);

    let s = startGame("family_feud");
    s = act(s, { type: "feud_strike", delta: 1 }); // t1
    s = act(s, { type: "feud_strike", delta: 1 }); // t2
    s = act(s, { type: "feud_strike", delta: 1 }); // t1 reaches two

    expect(s.feud?.strikes).toEqual({ t1: 2, t2: 1 });
    expect(s.feud?.ended).toBe(false);
    expect(s.feud?.activeTeamId).toBe("t2");
  });

  test("the active team alternates after every guess", () => {
    let s = startGame("family_feud");
    expect(s.feud?.activeTeamId).toBe("t1");

    s = act(s, { type: "feud_reveal", answerId: "a1" });
    expect(s.feud?.activeTeamId).toBe("t2");

    s = act(s, { type: "feud_strike", delta: 1 });
    expect(s.feud?.strikes.t2).toBe(1);
    expect(s.feud?.activeTeamId).toBe("t1");
  });

  test("strikes are counted per team and elimination does not end the round", () => {
    let s = startGame("family_feud", { strikeLimit: 3 });
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    // t1, t2, t1, t2, t1 → t1 reaches three and drops out
    for (let i = 0; i < 5; i += 1) s = act(s, { type: "feud_strike", delta: 1 });

    expect(s.feud?.strikes).toEqual({ t1: 3, t2: 2 });
    expect(s.feud?.ended).toBe(false);
    expect(s.phase).toBe("QUESTION_ACTIVE");
    expect(s.feud?.activeTeamId).toBe("t2");

    // the survivor's third strike ends the round by comparison
    s = act(s, { type: "feud_strike", delta: 1 });
    expect(s.feud?.ended).toBe(true);
    expect(s.phase).toBe("REVEAL");
    expect(s.feud?.outcome).toMatchObject({
      reason: "both_eliminated",
      winnerTeamId: "t1",
      credited: { t1: 40, t2: 30 },
    });
  });

  test("the last team standing takes the whole pot even with fewer points", () => {
    let s = startGame("family_feud", { strikeLimit: 3 });
    s = act(s, { type: "feud_reveal", answerId: "a1" }); // t1 +40
    s = act(s, { type: "feud_reveal", answerId: "a2" }); // t2 +30
    for (let i = 0; i < 5; i += 1) s = act(s, { type: "feud_strike", delta: 1 });

    // t1 is out; t2 keeps guessing alone and clears the board
    s = act(s, { type: "feud_reveal", answerId: "a3" }); // t2 +20
    s = act(s, { type: "feud_reveal", answerId: "a4" }); // t2 +10

    expect(s.feud?.ended).toBe(true);
    expect(s.feud?.outcome).toMatchObject({
      reason: "last_team_standing",
      winnerTeamId: "t2",
      credited: { t1: 40, t2: 60 },
    });

    s = act(s, { type: "feud_award" });
    expect(s.scores.teams.t2).toBe(100);
    expect(s.scores.teams.t1).toBe(0);
    expect(s.feud?.awardedTo).toBe("t2");
  });

  test("clearing the board compares the points each team revealed", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" }); // t1 +40
    s = act(s, { type: "feud_reveal", answerId: "a2" }); // t2 +30
    s = act(s, { type: "feud_reveal", answerId: "a3" }); // t1 +20

    expect(s.phase).toBe("QUESTION_ACTIVE");
    s = act(s, { type: "feud_reveal", answerId: "a4" }); // t2 +10, board clear

    expect(s.phase).toBe("REVEAL");
    expect(s.feud?.outcome).toMatchObject({
      reason: "answers_exhausted",
      winnerTeamId: "t1",
    });
    expect(s.feud?.outcome?.credited).toEqual({ t1: 60, t2: 40 });

    s = act(s, { type: "feud_award" });
    expect(s.scores.teams.t1).toBe(100);
  });

  test("a tied round waits for the host to choose the winner", () => {
    const onTie = (state: SessionState, action: Action) =>
      applyAction(state, action, tieBank, tick());
    let s = startWith(tieBank);
    s = onTie(s, { type: "feud_reveal", answerId: "a1" });
    s = onTie(s, { type: "feud_reveal", answerId: "a2" });

    expect(s.feud?.outcome).toMatchObject({ tied: true, winnerTeamId: null });
    expect(s.scores.teams.t1).toBe(0);

    expectEngineError(() => onTie(s, { type: "feud_award" }));
    s = onTie(s, { type: "feud_award", teamId: "t1" });
    expect(s.scores.teams.t1).toBe(20);
    expect(s.feud?.awarded).toBe(true);
    expectEngineError(() => onTie(s, { type: "feud_award", teamId: "t2" }));
  });

  test("the pot is multiplied at award time", () => {
    let s = startGame("family_feud", { roundMultiplier: 2 });
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    s = act(s, { type: "feud_reveal", answerId: "a3" });
    s = act(s, { type: "feud_reveal", answerId: "a4" });
    const winner = s.feud?.outcome?.winnerTeamId ?? "";
    s = act(s, { type: "feud_award" });
    expect(s.scores.teams[winner]).toBe(200);
  });

  test("next round is blocked until the pot is awarded", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    s = act(s, { type: "feud_reveal", answerId: "a3" });
    s = act(s, { type: "feud_reveal", answerId: "a4" });

    expectEngineError(() => act(s, { type: "next_round" }));
    s = act(s, { type: "feud_award" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "next_round" });
    expect(s.phase).toBe("ROUND_READY");
  });

  test("the opening team alternates every round", () => {
    let s = startGame("family_feud");
    expect(s.feud?.startingTeamId).toBe("t1");

    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    s = act(s, { type: "feud_reveal", answerId: "a3" });
    s = act(s, { type: "feud_reveal", answerId: "a4" });
    s = act(s, { type: "feud_award" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "next_round" });
    s = act(s, { type: "start_round" });

    expect(s.feud?.startingTeamId).toBe("t2");
    expect(s.feud?.activeTeamId).toBe("t2");
  });

  test("restarting a round rolls back its awarded points", () => {
    const onTie = (state: SessionState, action: Action) =>
      applyAction(state, action, tieBank, tick());
    let s = startWith(tieBank);
    s = onTie(s, { type: "feud_reveal", answerId: "a1" });
    s = onTie(s, { type: "feud_reveal", answerId: "a2" });
    s = onTie(s, { type: "feud_award", teamId: "t1" });
    expect(s.scores.teams.t1).toBe(20);

    s = onTie(s, { type: "restart_round" });
    expect(s.scores.teams.t1).toBe(0);
    expect(s.phase).toBe("ROUND_READY");
  });

  test("a team's strike can be corrected down without ending the round", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_strike", delta: 1 });
    expect(s.feud?.strikes.t1).toBe(1);
    s = act(s, { type: "feud_strike", delta: -1, teamId: "t1" });
    expect(s.feud?.strikes.t1).toBe(0);
    expect(s.phase).toBe("QUESTION_ACTIVE");
  });

  test("game ends with standings after the last question", () => {
    let s = startGame("family_feud");
    const total = bank.family_feud.length;
    for (let round = 0; round < total; round += 1) {
      if (round > 0) s = act(s, { type: "start_round" });
      const question = bank.family_feud[round]!;
      for (const answer of question.answers) {
        s = act(s, { type: "feud_reveal", answerId: answer.id });
      }
      s = act(s, { type: "feud_award" });
      s = act(s, { type: "round_result" });
      s = act(s, { type: "next_round" });
    }
    expect(s.phase).toBe("GAME_RESULT");
    expect(s.results).toHaveLength(1);
    const points = s.results[0]?.standings.map((row) => row.points) ?? [];
    expect(points).toHaveLength(2);
    expect(Math.max(...points)).toBeGreaterThan(0);
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
    let s = startGame("price_is_right");
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
    let s = startGame("price_is_right");
    const price = bank.price_is_right[0]!.actualPrice;
    s = guess(s, "p1", price + 500);
    s = guess(s, "p2", price + 50);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    expect(s.pir?.winners).toEqual(["p2"]);
  });

  test("ties award every equal winning guess", () => {
    let s = startGame("price_is_right");
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
    let s = startGame("price_is_right");
    s = guess(s, "p1", 900);
    const hidden = projectPublic(s, bank);
    expect(hidden.question?.actualPrice).toBeNull();
    expect(hidden.pir?.guesses).toBeNull();

    s = act(s, { type: "pir_lock" });
    expectEngineError(() => act(s, { type: "pir_set_guess", entityId: "p2", value: 5 }));
  });

  test("team mode scores teams rather than individuals", () => {
    let s = startGame("price_is_right", { pirMode: "team" });
    const price = bank.price_is_right[0]!.actualPrice;
    s = act(s, { type: "pir_set_guess", entityId: "t1", value: price - 10 });
    s = act(s, { type: "pir_set_guess", entityId: "t2", value: price + 10 });
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    expect(s.scores.teams.t1).toBe(1);
    expect(s.scores.teams.t2).toBe(0);
  });
});

describe("price phone teams", () => {
  const startParty = () => {
    let s = session({ pirPhoneTeams: true });
    s = act(s, { type: "select_game", game: "price_is_right" });
    s = act(s, { type: "rules_skip" });
    s = act(s, { type: "start_round" });
    return s;
  };

  const joinTeams = (state: SessionState) => {
    let s = act(state, { type: "pir_team_add", teamId: "t-a", name: "Alpha" });
    s = act(s, { type: "pir_team_add", teamId: "t-b", name: "Bravo" });
    s = act(s, { type: "pir_team_add", teamId: "t-c", name: "Charlie" });
    return s;
  };

  const guess = (state: SessionState, teamId: string, value: number) =>
    act(state, { type: "pir_set_guess", entityId: teamId, value });

  test("phone teams are off unless configured", () => {
    const s = startGame("price_is_right");
    expect(s.pir?.party).toBeNull();
  });

  test("up to three teams connect and are capped", () => {
    let s = joinTeams(startParty());
    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(3);
    expectEngineError(() =>
      act(s, { type: "pir_team_add", teamId: "t-d", name: "Delta" }),
    );
  });

  test("guesses stay private until the reveal and lock after", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1100);
    s = guess(s, "t-b", 1400);

    const hidden = projectPublic(s, bank);
    expect(hidden.pir?.party?.guesses).toBeNull();
    expect(hidden.pir?.party?.teams.find((team) => team.id === "t-a")?.submitted).toBe(true);

    s = act(s, { type: "reveal" });
    const shown = projectPublic(s, bank);
    expect(shown.pir?.party?.guesses).toEqual([
      { teamId: "t-a", value: 1100 },
      { teamId: "t-b", value: 1400 },
    ]);
  });

  test("closest without going over wins and the host confirms the point", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1100);
    s = guess(s, "t-b", 1400);
    s = guess(s, "t-c", 1600);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });

    expect(s.pir?.party?.winners).toEqual(["t-b"]);
    expect(s.pir?.party?.scores["t-b"]).toBe(0);

    s = act(s, { type: "pir_award" });
    expect(s.pir?.party?.scores["t-b"]).toBe(1);
    expectEngineError(() => act(s, { type: "pir_award" }));
  });

  test("the host can undo, override and re-award the point", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1400);
    s = guess(s, "t-b", 1400);
    s = guess(s, "t-c", 1600);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    s = act(s, { type: "pir_award" });

    expect(s.pir?.party?.winners.sort()).toEqual(["t-a", "t-b"]);
    expect(s.pir?.party?.scores["t-a"]).toBe(1);

    s = act(s, { type: "pir_undo_award" });
    expect(s.pir?.party?.scores["t-a"]).toBe(0);
    expect(s.pir?.party?.awarded).toBe(false);

    s = act(s, { type: "pir_override", teamIds: ["t-c"] });
    s = act(s, { type: "pir_award" });
    expect(s.pir?.party?.scores["t-c"]).toBe(1);
    expect(s.pir?.party?.scores["t-a"]).toBe(0);
  });

  test("teams and scores survive the next round, guesses do not", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1400);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    s = act(s, { type: "pir_award" });
    s = act(s, { type: "round_result" });
    s = act(s, { type: "next_round" });
    s = act(s, { type: "start_round" });

    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(3);
    expect(s.pir?.party?.scores["t-a"]).toBe(1);
    expect(s.pir?.party?.guesses).toEqual({});
    expect(s.pir?.party?.winners).toEqual([]);
  });

  test("restarting a round takes back its phone-team point", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1400);
    s = act(s, { type: "reveal" });
    s = act(s, { type: "pir_reveal_price" });
    s = act(s, { type: "pir_award" });
    expect(s.pir?.party?.scores["t-a"]).toBe(1);

    s = act(s, { type: "restart_round" });
    expect(s.pir?.party?.scores["t-a"]).toBe(0);
    expect(Object.keys(s.pir?.party?.teams ?? {})).toHaveLength(3);
  });

  test("a removed team loses its guess and score", () => {
    let s = joinTeams(startParty());
    s = guess(s, "t-a", 1400);
    s = act(s, { type: "pir_team_remove", teamId: "t-a" });
    expect(s.pir?.party?.teams["t-a"]).toBeUndefined();
    expect(s.pir?.party?.scores["t-a"]).toBeUndefined();
    expect(s.pir?.party?.guesses["t-a"]).toBeUndefined();
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
