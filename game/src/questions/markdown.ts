/* Markdown question-bank parser.

   Markdown files under questions/ are the single source of truth. This module
   is used by the build script (and tests) to turn them into typed questions;
   the browser only imports the generated JSON, so the parser never ships to
   players. */

import type {
  FeudQuestion,
  GameId,
  HerdQuestion,
  MostLikelyQuestion,
  PriceQuestion,
  Question,
  QuestionBank,
} from "../lib/types";

export class QuestionBankError extends Error {
  constructor(
    readonly file: string,
    readonly questionId: string | null,
    message: string,
  ) {
    super(`${file}${questionId ? ` (${questionId})` : ""}: ${message}`);
    this.name = "QuestionBankError";
  }
}

export const GAME_FILES: { file: string; game: GameId }[] = [
  { file: "family-feud.md", game: "family_feud" },
  { file: "herd-mentality.md", game: "herd_mentality" },
  { file: "whos-most-likely.md", game: "whos_most_likely" },
  { file: "price-is-right.md", game: "price_is_right" },
];

interface Entry {
  id: string;
  fields: Map<string, string>;
  table: string[][] | null;
}

const KEY_VALUE = /^([A-Za-z][A-Za-z0-9 _-]*?):\s*(.*)$/;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const SEPARATOR = /^:?-{3,}:?$/;

const normalizeKey = (key: string) => key.trim().toLowerCase().replace(/\s+/g, " ");

function parseTable(lines: string[], file: string, id: string): string[][] {
  const rows = lines.map((line) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .replace(/\\\|/g, "\u0000")
      .split("|")
      .map((cell) => cell.replace(/\u0000/g, "|").trim()),
  );
  if (rows.length < 2) {
    throw new QuestionBankError(file, id, "the answer table needs a header and at least one row");
  }
  const header = rows[0] ?? [];
  const separator = rows[1] ?? [];
  if (separator.length !== header.length || !separator.every((cell) => SEPARATOR.test(cell))) {
    throw new QuestionBankError(
      file,
      id,
      "the answer table needs a markdown separator row such as |---|---|",
    );
  }
  const body = rows.slice(2);
  for (const row of body) {
    if (row.length !== header.length) {
      throw new QuestionBankError(
        file,
        id,
        `table row has ${row.length} cells but the header has ${header.length}`,
      );
    }
  }
  return [header, ...body];
}

function splitEntries(source: string, file: string): Entry[] {
  const lines = source.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").split("\n");
  const entries: Entry[] = [];
  let current: { id: string; lines: string[] } | null = null;

  for (const line of lines) {
    const heading = /^##\s+(.+?)\s*$/.exec(line);
    if (heading) {
      if (current) entries.push(readEntry(current.id, current.lines, file));
      current = { id: heading[1]?.trim() ?? "", lines: [] };
      continue;
    }
    if (current) current.lines.push(line);
  }
  if (current) entries.push(readEntry(current.id, current.lines, file));

  if (entries.length === 0) {
    throw new QuestionBankError(file, null, "no '## QUESTION-ID' blocks found");
  }
  return entries;
}

function readEntry(id: string, lines: string[], file: string): Entry {
  if (!ID_PATTERN.test(id)) {
    throw new QuestionBankError(
      file,
      id,
      "question IDs must use letters, numbers, dashes or underscores",
    );
  }
  const fields = new Map<string, string>();
  let tableLines: string[] = [];
  let table: string[][] | null = null;

  const flushTable = () => {
    if (tableLines.length > 0) {
      table = parseTable(tableLines, file, id);
      tableLines = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("|")) {
      tableLines.push(line);
      continue;
    }
    flushTable();
    const match = KEY_VALUE.exec(line);
    if (!match) continue;
    fields.set(normalizeKey(match[1] ?? ""), (match[2] ?? "").trim());
  }
  flushTable();

  return { id, fields, table };
}

function required(entry: Entry, keys: string[], file: string): string {
  for (const key of keys) {
    const value = entry.fields.get(key);
    if (value) return value;
  }
  throw new QuestionBankError(file, entry.id, `missing required field "${keys[0]}"`);
}

function optional(entry: Entry, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = entry.fields.get(key);
    if (value) return value;
  }
  return undefined;
}

function metadata(entry: Entry, file: string): Pick<Question, "category" | "difficulty"> {
  const category = optional(entry, ["category"]);
  const difficulty = optional(entry, ["difficulty"])?.toLowerCase();
  if (difficulty && difficulty !== "easy" && difficulty !== "medium" && difficulty !== "hard") {
    throw new QuestionBankError(file, entry.id, `difficulty must be easy, medium or hard`);
  }
  return {
    ...(category ? { category } : {}),
    ...(difficulty ? { difficulty: difficulty as "easy" | "medium" | "hard" } : {}),
  };
}

function parseFeud(entry: Entry, file: string): FeudQuestion {
  const question = required(entry, ["english", "question"], file);
  const hindi = entry.fields.get("hindi");
  if (!hindi) {
    throw new QuestionBankError(file, entry.id, "missing required field \"Hindi\"");
  }
  if (!entry.table) {
    throw new QuestionBankError(file, entry.id, "missing the Points | Hindi | English table");
  }
  const [header = [], ...rows] = entry.table;
  const pointsIndex = header.findIndex((cell) => normalizeKey(cell) === "points");
  const englishIndex = header.findIndex((cell) => normalizeKey(cell) === "english");
  const hindiIndex = header.findIndex((cell) => normalizeKey(cell) === "hindi");
  if (pointsIndex < 0 || englishIndex < 0 || hindiIndex < 0) {
    throw new QuestionBankError(
      file,
      entry.id,
      "the answer table must have Points, Hindi and English columns",
    );
  }
  if (rows.length !== 5) {
    throw new QuestionBankError(
      file,
      entry.id,
      `Family Feud needs exactly five answers (found ${rows.length})`,
    );
  }
  const answers = rows.map((row, index) => {
    const text = row[englishIndex]?.trim() ?? "";
    const answerHindi = row[hindiIndex]?.trim() ?? "";
    const rawPoints = row[pointsIndex]?.trim() ?? "";
    if (!text) throw new QuestionBankError(file, entry.id, `answer ${index + 1} has no English text`);
    if (!answerHindi) throw new QuestionBankError(file, entry.id, `answer ${index + 1} has no Hindi text`);
    const points = Number(rawPoints);
    if (!Number.isInteger(points) || points < 0) {
      throw new QuestionBankError(file, entry.id, `answer ${index + 1} has an invalid point value "${rawPoints}"`);
    }
    return { id: `a${index + 1}`, text, hindi: answerHindi, points };
  });
  const total = answers.reduce((sum, answer) => sum + answer.points, 0);
  if (total !== 100) {
    throw new QuestionBankError(
      file,
      entry.id,
      `Family Feud point values must total 100 (found ${total})`,
    );
  }
  return {
    id: entry.id,
    game: "family_feud",
    question,
    hindi,
    answers,
    ...metadata(entry, file),
  };
}

function parsePrice(entry: Entry, file: string): PriceQuestion {
  const item = required(entry, ["item"], file);
  const size = required(entry, ["size"], file);
  const image = required(entry, ["image"], file);
  const sourceUrl = required(entry, ["source", "source url"], file);
  const rawPrice = required(entry, ["price", "actual price"], file);
  const actualPrice = Number(rawPrice);
  if (!Number.isFinite(actualPrice) || actualPrice <= 0) {
    throw new QuestionBankError(file, entry.id, `invalid price "${rawPrice}"`);
  }
  const currency = optional(entry, ["currency"]) ?? "INR";
  if (currency !== "INR") {
    throw new QuestionBankError(file, entry.id, `currency must be INR (found "${currency}")`);
  }
  return {
    id: entry.id,
    game: "price_is_right",
    item,
    size,
    description: optional(entry, ["description"]),
    image,
    actualPrice,
    currency,
    priceUnit: optional(entry, ["unit", "price unit"]) ?? "item",
    sourceUrl,
    ...metadata(entry, file),
  };
}

function parseHerd(entry: Entry, file: string): HerdQuestion {
  return {
    id: entry.id,
    game: "herd_mentality",
    question: required(entry, ["question", "english"], file),
    answerType: "free_text",
    ...metadata(entry, file),
  };
}

function parseMostLikely(entry: Entry, file: string): MostLikelyQuestion {
  const eligible = optional(entry, ["eligible", "eligible participants"])?.toLowerCase();
  if (eligible && eligible !== "all") {
    throw new QuestionBankError(file, entry.id, "only \"Eligible: all\" is supported today");
  }
  const allowRaw = optional(entry, ["allow self vote", "allow self-vote"])?.toLowerCase();
  if (allowRaw && allowRaw !== "yes" && allowRaw !== "no") {
    throw new QuestionBankError(file, entry.id, "Allow self vote must be yes or no");
  }
  return {
    id: entry.id,
    game: "whos_most_likely",
    question: required(entry, ["question", "english"], file),
    eligibleParticipants: "all",
    allowSelfVote: allowRaw !== "no",
    ...metadata(entry, file),
  };
}

export function parseQuestionMarkdown(source: string, game: GameId, file = `${game}.md`): Question[] {
  return splitEntries(source, file).map((entry) => {
    switch (game) {
      case "family_feud":
        return parseFeud(entry, file);
      case "price_is_right":
        return parsePrice(entry, file);
      case "herd_mentality":
        return parseHerd(entry, file);
      case "whos_most_likely":
        return parseMostLikely(entry, file);
      default: {
        const exhaustive: never = game;
        throw new QuestionBankError(file, entry.id, `unsupported game ${String(exhaustive)}`);
      }
    }
  });
}

/** Parse a set of Markdown files, checking IDs stay unique across the bank. */
export function assembleQuestionBank(
  sources: { file: string; game: GameId; source: string }[],
): QuestionBank {
  const bank: QuestionBank = {
    family_feud: [],
    herd_mentality: [],
    whos_most_likely: [],
    price_is_right: [],
  };
  const seen = new Map<string, string>();

  for (const { file, game, source } of sources) {
    for (const question of parseQuestionMarkdown(source, game, file)) {
      const previous = seen.get(question.id);
      if (previous) {
        throw new QuestionBankError(file, question.id, `duplicate question ID (also in ${previous})`);
      }
      seen.set(question.id, file);
      bank[game].push(question as never);
    }
  }

  return bank;
}
