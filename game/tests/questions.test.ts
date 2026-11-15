import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { applyAction, createSession, projectPublic } from "../src/engine/engine";
import { ROUNDS_PER_GAME, sampleWithoutReplacement } from "../src/lib/random";
import {
  GAME_FILES,
  QuestionBankError,
  assembleQuestionBank,
  parseQuestionMarkdown,
} from "../src/questions/markdown";
import { loadQuestionBank } from "../src/questions/bank";
import type { QuestionBank, SessionState } from "../src/lib/types";
import { defaultConfig } from "../src/lib/types";
import generated from "../questions/generated.json";

const root = path.join(import.meta.dir, "..");
const read = (file: string) => readFileSync(path.join(root, "questions", file), "utf8");
const files = GAME_FILES.map(({ file, game }) => ({ file, game, source: read(file) }));

const seeded = (start: number) => {
  let seed = start;
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
};

describe("markdown question banks", () => {
  test("the committed JSON matches the markdown sources", () => {
    expect(assembleQuestionBank(files)).toEqual(loadQuestionBank(generated));
  });

  test("FF-001 keeps five answers, 100 points and both languages", () => {
    const feud = parseQuestionMarkdown(read("family-feud.md"), "family_feud", "family-feud.md");
    const ff = feud.find((question) => question.id === "FF-001");
    expect(ff).toBeDefined();
    if (!ff || ff.game !== "family_feud") throw new Error("FF-001 missing");
    expect(ff.answers).toHaveLength(5);
    expect(ff.answers.reduce((sum, answer) => sum + answer.points, 0)).toBe(100);
    expect(ff.hindi).toContain("mummy");
    expect(ff.answers[0]).toMatchObject({
      text: "Where are you going?",
      hindi: "Kahan ja raha/rahi hai?",
      points: 34,
    });
    expect(ff.answers.map((answer) => answer.id)).toEqual(["a1", "a2", "a3", "a4", "a5"]);
  });

  test("every game file parses and IDs stay unique", () => {
    const bank = assembleQuestionBank(files);
    const ids = Object.values(bank).flat().map((question) => question.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    expect(bank.price_is_right.length).toBeGreaterThan(0);
    expect(bank.herd_mentality.length).toBeGreaterThan(0);
    expect(bank.whos_most_likely.length).toBeGreaterThan(0);
  });

  test("the Family Feud bank holds FF-001 through FF-013", () => {
    const feud = assembleQuestionBank(files).family_feud;
    expect(feud.map((question) => question.id)).toEqual(
      Array.from({ length: 13 }, (_, index) => `FF-${String(index + 1).padStart(3, "0")}`),
    );
    for (const question of feud) {
      expect(question.answers).toHaveLength(5);
      expect(question.answers.reduce((sum, answer) => sum + answer.points, 0)).toBe(100);
      expect(question.hindi?.length).toBeGreaterThan(0);
      expect(question.answers.every((answer) => answer.hindi && answer.text)).toBe(true);
    }
    // Original wording and order are preserved.
    const ff2 = feud.find((question) => question.id === "FF-002");
    expect(ff2?.question).toBe("Name something mom always has in her purse.");
    expect(ff2?.hindi).toBe("Mummy ke purse mein hamesha kya hota hai?");
    expect(ff2?.answers.map((answer) => [answer.points, answer.hindi, answer.text])).toEqual([
      [38, "Paise", "Money"],
      [24, "rumaal", "tissues"],
      [18, "Chaabi", "Keys"],
      [11, "Phone", "Phone"],
      [9, "Lip balm", "Lip balm"],
    ]);
  });

  test("malformed Feud entries are rejected", () => {
    const base = "## FF-X\n\nEnglish: Q\n\nHindi: H\n\n";
    const table = (rows: string[]) =>
      `${base}| Points | Hindi | English |\n|---|---|---|\n${rows.join("\n")}\n`;
    const run = (source: string) => parseQuestionMarkdown(source, "family_feud", "x.md");

    expect(() => run(base)).toThrow(QuestionBankError);
    expect(() => run(table(["| 40 | H | E |"]))).toThrow(/exactly five/);
    expect(() =>
      run(
        table([
          "| 30 | H1 | E1 |",
          "| 30 | H2 | E2 |",
          "| 20 | H3 | E3 |",
          "| 10 | H4 | E4 |",
          "| 5 | H5 | E5 |",
        ]),
      ),
    ).toThrow(/total 100/);
    expect(() =>
      run(
        table([
          "| 34 | H1 | E1 |",
          "| 27 | H2 | E2 |",
          "| 19 | H3 | E3 |",
          "| 12 | H4 | E4 |",
          "| 8 | H5 |  |",
        ]),
      ),
    ).toThrow(/no English text/);
    expect(() =>
      run(
        table([
          "| 34 | H1 |  |",
          "| 27 | H2 | E2 |",
          "| 19 | H3 | E3 |",
          "| 12 | H4 | E4 |",
          "| 8 | H5 | E5 |",
        ]),
      ),
    ).toThrow(/no English text/);
    expect(() => run("## FF-Y\n\nEnglish: Q\n\n| Points | English |\n|---|---|\n| 100 | E |\n")).toThrow(
      /Hindi/,
    );
  });

  function tableRows(points: number[]) {
    return points.map((value, index) => `| ${value} | Hin ${index + 1} | Eng ${index + 1} |`);
  }

  test("duplicate IDs are rejected across files", () => {
    const feud = read("family-feud.md");
    const pir = read("price-is-right.md");
    expect(() =>
      assembleQuestionBank([
        { file: "a.md", game: "family_feud", source: feud },
        {
          file: "b.md",
          game: "price_is_right",
          source: pir.replace("## PIR-001", "## FF-001"),
        },
      ]),
    ).toThrow(/duplicate question ID/);
  });

  test("price and most-likely validation is specific", () => {
    expect(() =>
      parseQuestionMarkdown("## PIR-X\n\nItem: A\n\nDescription: B\n\nImage: /x.svg\n", "price_is_right", "p.md"),
    ).toThrow(/price/);
    expect(() =>
      parseQuestionMarkdown(
        "## PIR-Y\n\nItem: A\n\nDescription: B\n\nImage: /x.svg\n\nPrice: not-a-number\n",
        "price_is_right",
        "p.md",
      ),
    ).toThrow(/invalid price/);
    expect(() =>
      parseQuestionMarkdown("## ML-X\n\nQuestion: Q?\n\nEligible: bride\n", "whos_most_likely", "m.md"),
    ).toThrow(/Eligible/);
    expect(() =>
      parseQuestionMarkdown("## ML-Y\n\nQuestion: Q?\n\nAllow self vote: maybe\n", "whos_most_likely", "m.md"),
    ).toThrow(/yes or no/);
  });

  test("markdown line endings and unicode survive", () => {
    const source = [
      "## FF-U",
      "English: Naam batao — “chai” ke saath kya?",
      "Hindi: चाय के साथ क्या?",
      "| Points | Hindi | English |",
      "|---|---|---|",
      "| 30 | बिस्किट | Biscuits |",
      "| 25 | समोसा | Samosa |",
      "| 20 | नमकीन | Namkeen |",
      "| 15 | केक | Cake |",
      "| 10 | कुछ नहीं | Nothing |",
      "",
    ].join("\r\n");
    const [question] = parseQuestionMarkdown(source, "family_feud", "u.md");
    expect(question).toMatchObject({
      id: "FF-U",
      question: "Naam batao — “chai” ke saath kya?",
      hindi: "चाय के साथ क्या?",
    });
    expect(question?.game === "family_feud" && question.answers[0]?.hindi).toBe("बिस्किट");
  });
});

describe("random selection", () => {
  const corpus = Array.from({ length: 13 }, (_, index) => `q${index + 1}`);

  test("takes ten unique questions from thirteen", () => {
    const picked = sampleWithoutReplacement(corpus, ROUNDS_PER_GAME, seeded(3));
    expect(picked).toHaveLength(10);
    expect(new Set(picked).size).toBe(10);
    expect(picked.every((id) => corpus.includes(id))).toBe(true);
  });

  test("different draws give different orders", () => {
    const first = sampleWithoutReplacement(corpus, 10, seeded(1));
    const second = sampleWithoutReplacement(corpus, 10, seeded(2));
    expect(first).not.toEqual(second);
  });

  test("the same random source is reproducible", () => {
    expect(sampleWithoutReplacement(corpus, 10, seeded(9))).toEqual(
      sampleWithoutReplacement(corpus, 10, seeded(9)),
    );
  });

  test("keeps all questions when fewer than ten exist", () => {
    const picked = sampleWithoutReplacement(corpus.slice(0, 3), 10, seeded(4));
    expect(picked).toHaveLength(3);
    expect(new Set(picked).size).toBe(3);
  });

  test("an empty corpus yields nothing", () => {
    expect(sampleWithoutReplacement([], 10, seeded(5))).toEqual([]);
    expect(sampleWithoutReplacement(corpus, 0, seeded(5))).toEqual([]);
  });
});

describe("session question order", () => {
  const corpus: QuestionBank = {
    family_feud: Array.from({ length: 13 }, (_, index) => ({
      id: `ff-${index + 1}`,
      game: "family_feud" as const,
      question: `Q ${index + 1}`,
      hindi: `S ${index + 1}`,
      answers: [34, 27, 19, 12, 8].map((points, answerIndex) => ({
        id: `a${answerIndex + 1}`,
        text: `A ${answerIndex + 1}`,
        hindi: `B ${answerIndex + 1}`,
        points,
      })),
    })),
    herd_mentality: [],
    whos_most_likely: [],
    price_is_right: [],
  };

  const start = (random: () => number) => {
    const session = createSession(
      { names: ["Asha", "Ravi", "Meera", "Vikram"], config: defaultConfig },
      "TEST",
      1000,
    );
    return applyAction(session, { type: "select_game", game: "family_feud" }, corpus, 1000, random);
  };

  test("a new game samples ten; a different draw has a different order", () => {
    const fixed = start(() => 0);
    const seededDraw = start(seeded(12));
    expect(fixed.questionOrder).toHaveLength(10);
    expect(seededDraw.questionOrder).toHaveLength(10);
    expect(fixed.questionOrder).not.toEqual(seededDraw.questionOrder);
  });

  test("the order survives serialization, undo-free refreshes and projection", () => {
    const session = start(() => 0);
    const restored = JSON.parse(JSON.stringify(session)) as SessionState;
    expect(restored.questionOrder).toEqual(session.questionOrder);
    expect(Object.keys(projectPublic(session, corpus))).not.toContain("questionOrder");
  });

  test("a real Family Feud game samples ten of the thirteen", () => {
    const real = assembleQuestionBank(files);
    const session = createSession(
      { names: ["Asha", "Ravi", "Meera", "Vikram"], config: defaultConfig },
      "TEST",
      1000,
    );
    const game = applyAction(session, { type: "select_game", game: "family_feud" }, real, 1000);
    expect(game.questionOrder).toHaveLength(10);
    expect(new Set(game.questionOrder).size).toBe(10);
    expect(game.questionOrder.every((id) => real.family_feud.some((q) => q.id === id))).toBe(true);
  });

  test("bilingual question text is public but answer Hindi waits for the reveal", () => {
    let session = start(() => 0);
    session = applyAction(session, { type: "rules_finish" }, corpus, 1000, () => 0);
    const assignment = Object.fromEntries(
      session.participants.map((person, index) => [person.id, index < 2 ? 0 : 1]),
    );
    session = applyAction(
      session,
      { type: "feud_teams", names: ["A", "B"], assignment },
      corpus,
      1000,
      () => 0,
    );
    session = applyAction(session, { type: "start_round" }, corpus, 1000, () => 0);

    const hidden = projectPublic(session, corpus);
    expect(hidden.question?.hindi).toBe("S 1");
    expect(hidden.question?.answers?.every((answer) => answer.hindi === null)).toBe(true);

    session = applyAction(session, { type: "feud_reveal", answerId: "a1" }, corpus, 1000, () => 0);
    const shown = projectPublic(session, corpus);
    expect(shown.question?.answers?.find((answer) => answer.id === "a1")?.hindi).toBe("B 1");
  });
});
