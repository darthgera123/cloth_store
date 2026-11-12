/* Bundled question bank. Imported only by the host (dynamically), so the
   audience bundle never carries hidden answers or unused questions. */

import familyFeud from "../../questions/family-feud.json";
import herdMentality from "../../questions/herd-mentality.json";
import priceIsRight from "../../questions/price-is-right.json";
import mostLikely from "../../questions/whos-most-likely.json";
import { type Question, type QuestionBank, questionSchema } from "../lib/types";

const SOURCES: { name: string; rows: unknown }[] = [
  { name: "family-feud.json", rows: familyFeud },
  { name: "herd-mentality.json", rows: herdMentality },
  { name: "whos-most-likely.json", rows: mostLikely },
  { name: "price-is-right.json", rows: priceIsRight },
];

export function loadQuestionBank(): QuestionBank {
  const bank: QuestionBank = {
    family_feud: [],
    herd_mentality: [],
    whos_most_likely: [],
    price_is_right: [],
  };
  const seen = new Set<string>();

  for (const source of SOURCES) {
    if (!Array.isArray(source.rows)) throw new Error(`${source.name}: expected an array`);
    for (const [index, row] of source.rows.entries()) {
      const parsed = questionSchema.safeParse(row);
      if (!parsed.success) {
        const issue = parsed.error.issues[0];
        throw new Error(`${source.name}[${index}]: ${issue?.message ?? "invalid question"}`);
      }
      const question = parsed.data as Question;
      if (seen.has(question.id)) throw new Error(`${source.name}: duplicate id ${question.id}`);
      seen.add(question.id);
      bank[question.game].push(question as never);
    }
  }

  return bank;
}
