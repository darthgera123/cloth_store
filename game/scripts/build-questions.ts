/* Generate questions/generated.json from the Markdown question banks.

   Run directly (`bun run questions`) or as part of `bun run build`. `--check`
   verifies the committed output is current without writing (used by tests). */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { QuestionBank } from "../src/lib/types";
import { GAME_FILES, QuestionBankError, assembleQuestionBank } from "../src/questions/markdown";

const root = path.join(import.meta.dir, "..");
const output = path.join(root, "questions", "generated.json");

export function buildQuestionBank(base = root): QuestionBank {
  return assembleQuestionBank(
    GAME_FILES.map(({ file, game }) => ({
      file,
      game,
      source: readFileSync(path.join(base, "questions", file), "utf8"),
    })),
  );
}

function main(): void {
  const check = process.argv.includes("--check");
  try {
    const json = `${JSON.stringify(buildQuestionBank(), null, 2)}\n`;
    if (check) {
      let current = "";
      try {
        current = readFileSync(output, "utf8");
      } catch {
        current = "";
      }
      if (current !== json) {
        console.error("questions/generated.json is out of date; run `bun run questions`");
        process.exit(1);
      }
      console.log("question banks are up to date");
      return;
    }
    writeFileSync(output, json);
    console.log(`wrote ${path.relative(root, output)}`);
  } catch (error) {
    if (error instanceof QuestionBankError) {
      console.error(error.message);
      process.exit(1);
    }
    throw error;
  }
}

if (import.meta.main) main();
