/* "How to Play" slides. Deliberately separate from the question corpus so the
   wording can be edited without touching gameplay data or code. Keep each
   slide to a couple of short sentences: the audience reads it from a sofa. */

import type { GameId } from "../lib/types";

export interface RuleSlide {
  title: string;
  body: string;
}

export const RULES: Record<GameId, RuleSlide[]> = {
  family_feud: [
    {
      title: "Two Families, One Pot",
      body: "Two families of four compete to guess the most popular answers.",
    },
    {
      title: "Take Turns",
      body: "Families alternate guesses. A correct answer adds its points to the shared pot. Two wrong guesses put a family out of the round.",
    },
    {
      title: "Win the Pot",
      body: "The winning family takes the entire pot. One family left standing wins it. Otherwise the family with the more valuable correct answers wins. The starting family alternates each round. Two strikes knock a family out.",
    },
  ],
  herd_mentality: [
    {
      title: "Think Alike",
      body: "Everyone answers the same question privately. No discussing, no hints.",
    },
    {
      title: "Match the Herd",
      body: "Matching the most popular answer scores points. The bigger the group with the same answer, the better.",
    },
    {
      title: "Pink Cow",
      body: "When the Pink Cow is in play, the chosen player carries it — and if it blocks winning, the Pink Cow cannot take the game.",
    },
  ],
  whos_most_likely: [
    {
      title: "Point the Finger",
      body: "Everyone votes for the person who best fits the prompt.",
    },
    {
      title: "Reveal Together",
      body: "All votes are revealed at once. The most-voted person wins the round.",
    },
    {
      title: "Scoring",
      body: "Casual by default: no points, just the reveal. The host can switch on competitive points.",
    },
  ],
  price_is_right: [
    {
      title: "Guess the Price",
      body: "Each player guesses what the item on screen really costs.",
    },
    {
      title: "The Reveal",
      body: "Once guesses are locked, the host reveals every guess and then the actual price.",
    },
    {
      title: "Closest Wins",
      body: "Closest without going over wins. If every guess is too high, the host's configured fallback decides.",
    },
  ],
};
