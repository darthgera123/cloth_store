/* Shared domain types. The question bank and the authoritative session state
   live on the server; these types are the contract between engine, server and
   the two clients. */

import { z } from "zod";

export const GAME_IDS = [
  "family_feud",
  "herd_mentality",
  "whos_most_likely",
  "price_is_right",
] as const;

export const gameIdSchema = z.enum(GAME_IDS);
export type GameId = (typeof GAME_IDS)[number];

export const GAME_LABEL: Record<GameId, string> = {
  family_feud: "Family Feud",
  herd_mentality: "Herd Mentality",
  whos_most_likely: "Who's Most Likely?",
  price_is_right: "The Price Is Right",
};

export const GAME_BLURB: Record<GameId, string> = {
  family_feud: "Name the answers the room would give.",
  herd_mentality: "Match the crowd. Originality loses.",
  whos_most_likely: "Point at the person who fits the prompt.",
  price_is_right: "Guess the price. Don't go over.",
};

/* ---------- phases ---------- */

export const PHASES = [
  "LOBBY",
  "RULES",
  "GAME_INTRO",
  "ROUND_READY",
  "QUESTION_ACTIVE",
  "ANSWERING",
  "REVEAL",
  "ROUND_RESULT",
  "GAME_RESULT",
] as const;

export const phaseSchema = z.enum(PHASES);
export type Phase = (typeof PHASES)[number];

/* ---------- questions ---------- */

const baseQuestion = {
  id: z.string().min(1),
  category: z.string().optional(),
  difficulty: z.enum(["easy", "medium", "hard"]).optional(),
};

export const feudQuestionSchema = z.object({
  ...baseQuestion,
  game: z.literal("family_feud"),
  question: z.string().min(1),
  answers: z
    .array(
      z.object({
        id: z.string().min(1),
        text: z.string().min(1),
        points: z.number().int().min(0),
      }),
    )
    .min(2)
    .max(10),
});

export const herdQuestionSchema = z.object({
  ...baseQuestion,
  game: z.literal("herd_mentality"),
  question: z.string().min(1),
  answerType: z.literal("free_text").default("free_text"),
});

export const mostLikelyQuestionSchema = z.object({
  ...baseQuestion,
  game: z.literal("whos_most_likely"),
  question: z.string().min(1),
  eligibleParticipants: z.literal("all").default("all"),
  allowSelfVote: z.boolean().default(true),
});

export const priceQuestionSchema = z.object({
  ...baseQuestion,
  game: z.literal("price_is_right"),
  item: z.string().min(1),
  description: z.string().min(1),
  image: z.string().min(1),
  actualPrice: z.number().min(0),
  currency: z.string().min(1).default("INR"),
  priceUnit: z.string().min(1).default("item"),
});

export const questionSchema = z.discriminatedUnion("game", [
  feudQuestionSchema,
  herdQuestionSchema,
  mostLikelyQuestionSchema,
  priceQuestionSchema,
]);

export type FeudQuestion = z.infer<typeof feudQuestionSchema>;
export type HerdQuestion = z.infer<typeof herdQuestionSchema>;
export type MostLikelyQuestion = z.infer<typeof mostLikelyQuestionSchema>;
export type PriceQuestion = z.infer<typeof priceQuestionSchema>;
export type Question = z.infer<typeof questionSchema>;

export interface QuestionBank {
  family_feud: FeudQuestion[];
  herd_mentality: HerdQuestion[];
  whos_most_likely: MostLikelyQuestion[];
  price_is_right: PriceQuestion[];
}

/* ---------- session model ---------- */

export interface Participant {
  id: string;
  name: string;
  teamId: string | null;
}

export interface Team {
  id: string;
  name: string;
}

export interface Scores {
  participants: Record<string, number>;
  teams: Record<string, number>;
}

export interface Timer {
  endsAt: number;
  seconds: number;
  label: string;
}

export type FeudEndReason = "answers_exhausted" | "both_eliminated" | "last_team_standing";

export interface FeudOutcome {
  reason: FeudEndReason;
  winnerTeamId: string | null;
  tied: boolean;
  credited: Record<string, number>;
}

export interface FeudState {
  questionId: string;
  revealed: string[];
  /** answer id -> team id that guessed it correctly */
  credited: Record<string, string>;
  /** per-team incorrect guesses this round */
  strikes: Record<string, number>;
  activeTeamId: string;
  startingTeamId: string;
  pot: number;
  awarded: boolean;
  awardedTo: string | null;
  ended: boolean;
  outcome: FeudOutcome | null;
}

export interface HerdGroup {
  key: string;
  label: string;
  participantIds: string[];
}

export interface HerdResult {
  groups: HerdGroup[];
  winners: string[];
  tied: boolean;
  points: number;
}

export interface HerdState {
  questionId: string;
  answers: Record<string, string>;
  merges: Record<string, string>;
  result: HerdResult | null;
  awarded: boolean;
  pinkCow: string | null;
}

export interface MostLikelyState {
  questionId: string;
  votes: Record<string, number>;
  revealed: boolean;
  winners: string[];
  awarded: boolean;
}

export interface PriceState {
  questionId: string;
  guesses: Record<string, number | null>;
  locked: boolean;
  guessesRevealed: boolean;
  priceRevealed: boolean;
  winners: string[];
  awarded: boolean;
}

export interface GameStanding {
  label: string;
  points: number;
  winner?: boolean;
  blocked?: boolean;
}

export interface GameResult {
  game: GameId;
  round: number;
  standings: GameStanding[];
  at: number;
}

export interface ScoreAward {
  kind: "participant" | "team";
  id: string;
  points: number;
}

export interface SessionState {
  id: string;
  code: string;
  createdAt: number;
  updatedAt: number;
  status: "lobby" | "active" | "ended";
  phase: Phase;
  paused: boolean;
  game: GameId | null;
  round: number;
  questionIndex: number;
  rulesSlide: number;
  rulesReturn: Phase | null;
  usedQuestionIds: string[];
  questionOrder: string[];
  participants: Participant[];
  teams: Team[];
  config: SessionConfig;
  scores: Scores;
  feud: FeudState | null;
  herd: HerdState | null;
  ml: MostLikelyState | null;
  pir: PriceState | null;
  timer: Timer | null;
  results: GameResult[];
  roundAwards: ScoreAward[];
}

export interface SessionConfig {
  strikeLimit: number;
  roundMultiplier: number;
  herdPoints: number;
  herdTieAwards: boolean;
  pinkCowEnabled: boolean;
  pinkCowBlocksWin: boolean;
  mlMode: "casual" | "competitive";
  mlPoints: number;
  mlAllowSelfVote: boolean;
  pirMode: "individual" | "team";
  pirPoints: number;
  pirAllOverFallback: "closest" | "lowest";
  currency: string;
  soundDefault: boolean;
  shuffleQuestions: boolean;
}

export const configSchema = z.object({
  strikeLimit: z.number().int().min(1).max(5),
  roundMultiplier: z.number().int().min(1).max(3),
  herdPoints: z.number().int().min(1).max(10),
  herdTieAwards: z.boolean(),
  pinkCowEnabled: z.boolean(),
  pinkCowBlocksWin: z.boolean(),
  mlMode: z.enum(["casual", "competitive"]),
  mlPoints: z.number().int().min(1).max(10),
  mlAllowSelfVote: z.boolean(),
  pirMode: z.enum(["individual", "team"]),
  pirPoints: z.number().int().min(1).max(100),
  pirAllOverFallback: z.enum(["closest", "lowest"]),
  currency: z.string().min(1).max(8),
  soundDefault: z.boolean(),
  shuffleQuestions: z.boolean(),
});

export const defaultConfig: SessionConfig = {
  strikeLimit: 2,
  roundMultiplier: 1,
  herdPoints: 1,
  herdTieAwards: false,
  pinkCowEnabled: false,
  pinkCowBlocksWin: false,
  mlMode: "casual",
  mlPoints: 1,
  mlAllowSelfVote: true,
  pirMode: "individual",
  pirPoints: 1,
  pirAllOverFallback: "closest",
  currency: "INR",
  soundDefault: true,
  shuffleQuestions: false,
};

/* ---------- actions ---------- */

export const actionSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("configure"),
    participants: z
      .array(
        z.object({
          name: z.string().trim().min(1).max(24),
          team: z.union([z.literal(0), z.literal(1)]).optional(),
        }),
      )
      .min(2)
      .max(8),
    teams: z.tuple([z.string().trim().min(1).max(24), z.string().trim().min(1).max(24)]).nullable(),
    config: configSchema.partial().optional(),
    assignTeams: z.boolean().optional(),
  }),
  z.object({ type: z.literal("select_game"), game: gameIdSchema }),
  z.object({ type: z.literal("rules_next") }),
  z.object({ type: z.literal("rules_prev") }),
  z.object({ type: z.literal("rules_finish") }),
  z.object({ type: z.literal("rules_skip") }),
  z.object({ type: z.literal("open_rules") }),
  z.object({ type: z.literal("start_round") }),
  z.object({ type: z.literal("begin_answering") }),
  z.object({ type: z.literal("reveal") }),
  z.object({ type: z.literal("round_result") }),
  z.object({ type: z.literal("next_round") }),
  z.object({ type: z.literal("end_game") }),
  z.object({ type: z.literal("back_to_lobby") }),
  z.object({ type: z.literal("set_paused"), paused: z.boolean() }),
  z.object({ type: z.literal("set_timer"), seconds: z.number().int().min(0).max(3600), label: z.string().max(32).default("") }),
  z.object({ type: z.literal("clear_timer") }),
  z.object({
    type: z.literal("edit_score"),
    kind: z.enum(["participant", "team"]),
    id: z.string().min(1),
    value: z.number().int().min(0).max(100000),
  }),
  z.object({ type: z.literal("skip_question") }),
  z.object({ type: z.literal("restart_round") }),
  z.object({ type: z.literal("reset_session") }),

  z.object({ type: z.literal("feud_reveal"), answerId: z.string().min(1) }),
  z.object({
    type: z.literal("feud_strike"),
    delta: z.union([z.literal(1), z.literal(-1)]),
    teamId: z.string().min(1).optional(),
  }),
  z.object({ type: z.literal("feud_award"), teamId: z.string().min(1).optional() }),

  z.object({ type: z.literal("herd_set_answer"), participantId: z.string().min(1), text: z.string().max(60) }),
  z.object({ type: z.literal("herd_merge"), from: z.string().min(1), to: z.string().min(1) }),
  z.object({ type: z.literal("herd_unmerge"), key: z.string().min(1) }),
  z.object({ type: z.literal("herd_set_pink_cow"), participantId: z.string().nullable() }),

  z.object({ type: z.literal("ml_set_votes"), participantId: z.string().min(1), votes: z.number().int().min(0).max(8) }),
  z.object({ type: z.literal("ml_clear_votes") }),

  z.object({ type: z.literal("pir_set_guess"), entityId: z.string().min(1), value: z.number().min(0).max(10000000) }),
  z.object({ type: z.literal("pir_lock") }),
  z.object({ type: z.literal("pir_reveal_price") }),
]);

export type Action = z.infer<typeof actionSchema>;

export interface ActionEnvelope {
  actionId: string;
  action: Action;
}

/* ---------- wire payloads ---------- */

export interface PublicAnswer {
  id: string;
  text: string | null;
  points: number | null;
  revealed: boolean;
}

export interface PublicQuestion {
  game: GameId;
  text: string;
  /** Family Feud */
  answers?: PublicAnswer[];
  /** The Price Is Right */
  item?: string;
  description?: string;
  image?: string;
  currency?: string;
  priceUnit?: string;
  actualPrice?: number | null;
}

export interface PublicFeud {
  activeTeamId: string | null;
  strikes: Record<string, number>;
  strikeLimit: number;
  pot: number;
  awarded: boolean;
  awardedTo: string | null;
  ended: boolean;
  outcome: FeudOutcome | null;
}

export interface PublicHerd {
  answeredCount: number;
  totalPlayers: number;
  pinkCow: string | null;
  result: HerdResult | null;
}

export interface PublicMostLikely {
  voteCount: number;
  revealed: boolean;
  winners: string[];
  votes: { participantId: string; votes: number }[] | null;
}

export interface PublicPrice {
  guesses: { entityId: string; value: number | null }[] | null;
  locked: boolean;
  priceRevealed: boolean;
  winners: string[];
  mode: "individual" | "team";
}

export interface PublicState {
  code: string;
  status: "lobby" | "active" | "ended";
  phase: Phase;
  paused: boolean;
  game: GameId | null;
  round: number;
  rulesSlide: number;
  participants: Participant[];
  teams: Team[];
  scores: Scores;
  timer: Timer | null;
  question: PublicQuestion | null;
  feud: PublicFeud | null;
  herd: PublicHerd | null;
  ml: PublicMostLikely | null;
  pir: PublicPrice | null;
  results: GameResult[];
  updatedAt: number;
}

export interface HostState {
  session: SessionState;
  questions: Question[];
  canUndo: boolean;
  undoLabel: string | null;
  history: { label: string; at: number }[];
}
