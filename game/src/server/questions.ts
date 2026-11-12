/* Load and validate the question bank from JSON files. The bank never leaves
   the server: only the current, projected question is sent to clients. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import {
  type Question,
  type QuestionBank,
  questionSchema,
} from "../lib/types";

const EMPTY: QuestionBank = {
  family_feud: [],
  herd_mentality: [],
  whos_most_likely: [],
  price_is_right: [],
};

export async function loadQuestionBank(dir: string): Promise<QuestionBank> {
  const bank: QuestionBank = structuredClone(EMPTY);
  let files: string[] = [];

  try {
    files = (await readdir(dir)).filter((name) => name.endsWith(".json")).sort();
  } catch {
    throw new Error(`Question directory not found: ${dir}`);
  }

  const seen = new Set<string>();

  for (const file of files) {
    const raw = await readFile(path.join(dir, file), "utf8");
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw new Error(`${file}: invalid JSON — ${(error as Error).message}`);
    }

    const list = Array.isArray(parsed) ? parsed : [parsed];
    for (const [index, item] of list.entries()) {
      const result = questionSchema.safeParse(item);
      if (!result.success) {
        throw new Error(`${file}[${index}]: ${result.error.issues[0]?.message ?? "invalid question"}`);
      }
      const question = result.data as Question;
      if (seen.has(question.id)) throw new Error(`${file}: duplicate question id ${question.id}`);
      seen.add(question.id);
      bank[question.game].push(question as never);
    }
  }

  return bank;
}
