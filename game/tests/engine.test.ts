import { describe, expect, test } from "bun:test";
import path from "node:path";
import {
  type Action,
  type QuestionBank,
  type SessionState,
  defaultConfig,
} from "../src/lib/types";
import { EngineError, applyAction, createSession, projectPublic } from "../src/server/engine";
import { herdGroups, normalizeAnswer } from "../src/lib/herd";
import { loadQuestionBank } from "../src/server/questions";

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

  test("configure replaces participants and keeps config valid", () => {
    const s = act(session(), {
      type: "configure",
      participants: [{ name: "One" }, { name: "Two" }, { name: "Three", team: 1 }],
      teams: ["A", "B"],
    });
    expect(s.participants.map((p) => p.name)).toEqual(["One", "Two", "Three"]);
    expect(s.participants[2]?.teamId).toBe("t2");
    expect(s.scores.participants.p3).toBe(0);
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
  test("revealing answers builds the pot and private answers stay hidden", () => {
    let s = startGame("family_feud");
    expect(s.phase).toBe("QUESTION_ACTIVE");
    expect(s.feud?.pot).toBe(0);

    s = act(s, { type: "feud_reveal", answerId: "a1" });
    expect(s.feud?.pot).toBe(40);

    const pub = projectPublic(s, bank, { hostConnected: true });
    const answers = pub.question?.answers ?? [];
    expect(answers[0]).toMatchObject({ revealed: true, text: "Food", points: 40 });
    expect(answers[1]).toMatchObject({ revealed: false, text: null, points: null });
    expect(JSON.stringify(pub)).not.toContain("Clothes");
  });

  test("three strikes open a steal for the other team", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    for (let i = 0; i < 3; i += 1) s = act(s, { type: "feud_strike", delta: 1 });

    expect(s.feud?.steal.active).toBe(true);
    expect(s.feud?.steal.teamId).toBe("t2");
    expect(s.feud?.activeTeamId).toBe("t2");
  });

  test("successful steal awards the pot to the challenger only once", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_reveal", answerId: "a2" });
    for (let i = 0; i < 3; i += 1) s = act(s, { type: "feud_strike", delta: 1 });

    s = act(s, { type: "feud_steal", success: true });
    expect(s.scores.teams.t2).toBe(70);
    expect(s.scores.teams.t1).toBe(0);

    expectEngineError(() => act(s, { type: "feud_steal", success: true }));
    expectEngineError(() => act(s, { type: "feud_award", teamId: "t1" }));
    expect(s.scores.teams.t2).toBe(70);
  });

  test("failed steal awards the pot to the team that was playing", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    for (let i = 0; i < 3; i += 1) s = act(s, { type: "feud_strike", delta: 1 });
    s = act(s, { type: "feud_steal", success: false });
    expect(s.scores.teams.t1).toBe(40);
    expect(s.scores.teams.t2).toBe(0);
  });

  test("round multiplier applies at award time", () => {
    let s = startGame("family_feud", { roundMultiplier: 2 });
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_award", teamId: "t2" });
    expect(s.scores.teams.t2).toBe(80);
  });

  test("restarting a round rolls back the points it awarded", () => {
    let s = startGame("family_feud");
    s = act(s, { type: "feud_reveal", answerId: "a1" });
    s = act(s, { type: "feud_award", teamId: "t1" });
    expect(s.scores.teams.t1).toBe(40);

    s = act(s, { type: "restart_round" });
    expect(s.scores.teams.t1).toBe(0);
    expect(s.phase).toBe("ROUND_READY");
  });

  test("game ends with standings after the last question", () => {
    let s = startGame("family_feud");
    const total = bank.family_feud.length;
    for (let round = 0; round < total; round += 1) {
      if (round > 0) s = act(s, { type: "start_round" });
      const q = bank.family_feud[round]!;
      s = act(s, { type: "feud_reveal", answerId: q.answers[0]!.id });
      s = act(s, { type: "feud_award", teamId: "t1" });
      s = act(s, { type: "reveal" });
      s = act(s, { type: "round_result" });
      s = act(s, { type: "next_round" });
    }
    expect(s.phase).toBe("GAME_RESULT");
    expect(s.results).toHaveLength(1);
    expect(s.results[0]?.standings[0]).toMatchObject({ label: "Bride's Family", winner: true });
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
    const pub = JSON.stringify(projectPublic(s, bank, { hostConnected: true }));
    expect(pub).not.toContain("secret samosa");
    expect(projectPublic(s, bank, { hostConnected: true }).herd?.answeredCount).toBe(1);
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
    const hidden = projectPublic(s, bank, { hostConnected: true });
    expect(hidden.ml?.votes).toBeNull();

    s = act(s, { type: "reveal" });
    const shown = projectPublic(s, bank, { hostConnected: true });
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
    const hidden = projectPublic(s, bank, { hostConnected: true });
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

describe("projection", () => {
  test("lobby payload carries no question or game state", () => {
    const pub = projectPublic(session(), bank, { hostConnected: false });
    expect(pub.question).toBeNull();
    expect(pub.feud).toBeNull();
    expect(pub.hostConnected).toBe(false);
    expect(JSON.stringify(pub)).not.toContain("biryani");
  });

  test("host payload keeps answers that the public payload hides", () => {
    const s = startGame("family_feud");
    const pub = JSON.stringify(projectPublic(s, bank, { hostConnected: true }));
    for (const answer of bank.family_feud[0]!.answers) {
      expect(pub).not.toContain(answer.text);
    }
  });
});
