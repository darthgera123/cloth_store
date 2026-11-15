/* Generated question bank. Imported only by the host (dynamically), so the
   audience bundle never carries hidden answers or unused questions.

   The source of truth is questions/*.md; `bun run questions` regenerates
   questions/generated.json before builds and tests. */

import generated from "../../questions/generated.json";
import { type Question, type QuestionBank, questionSchema } from "../lib/types";

const GAMES = ["family_feud", "herd_mentality", "whos_most_likely", "price_is_right"] as const;

export function loadQuestionBank(source: unknown = generated): QuestionBank {
  const bank: QuestionBank = {
    family_feud: [],
    herd_mentality: [],
    whos_most_likely: [],
    price_is_right: [],
  };
  const seen = new Set<string>();
  const data = source as Record<string, unknown>;

  for (const game of GAMES) {
    const rows = data[game];
    if (!Array.isArray(rows)) throw new Error(`${game}: expected an array of questions`);
    for (const [index, row] of rows.entries()) {
      const parsed = questionSchema.safeParse(row);
      if (!parsed.success) {
        const issue = parsed.error.issues[0];
        throw new Error(`${game}[${index}]: ${issue?.message ?? "invalid question"}`);
      }
      const question = parsed.data as Question;
      if (seen.has(question.id)) throw new Error(`${game}[${index}]: duplicate id ${question.id}`);
      seen.add(question.id);
      bank[question.game].push(question as never);
    }
  }

  return bank;
}
