/** Unbiased sample without replacement: partial Fisher–Yates. */
export function sampleWithoutReplacement<T>(
  items: readonly T[],
  count: number,
  random: () => number = Math.random,
): T[] {
  const pool = [...items];
  const take = Math.max(0, Math.min(count, pool.length));
  for (let index = 0; index < take; index += 1) {
    const pick = index + Math.floor(random() * (pool.length - index));
    const swap = pool[index];
    pool[index] = pool[pick] as T;
    pool[pick] = swap as T;
  }
  return pool.slice(0, take);
}


function shuffle<T>(items: T[], random: () => number): T[] {
  for (let index = items.length - 1; index > 0; index -= 1) {
    const pick = Math.floor(random() * (index + 1));
    const swap = items[index];
    items[index] = items[pick] as T;
    items[pick] = swap as T;
  }
  return items;
}

/**
 * Price Is Right draw: split the catalogue into cheap/mid/expensive thirds and
 * take a balanced number from each, then shuffle the round order. Keeps every
 * game from being all luxury items or all groceries.
 */
export function samplePriceQuestions<T>(
  items: readonly T[],
  count: number,
  priceOf: (item: T) => number,
  random: () => number = Math.random,
): T[] {
  const take = Math.max(0, Math.min(count, items.length));
  if (take === 0) return [];
  // The whole catalogue fits: keep the file order as the round order.
  if (take === items.length) return [...items];
  const sorted = [...items].sort((a, b) => priceOf(a) - priceOf(b));

  const tierCount = Math.min(3, sorted.length);
  const tiers: T[][] = Array.from({ length: tierCount }, () => []);
  sorted.forEach((item, index) => {
    const tier = Math.min(tierCount - 1, Math.floor((index / sorted.length) * tierCount));
    tiers[tier]?.push(item);
  });

  const base = Math.floor(take / tierCount);
  const remainder = take % tierCount;
  const bonusOrder = shuffle(
    Array.from({ length: tierCount }, (_, index) => index),
    random,
  );
  const takes = tiers.map((_, index) => base + (bonusOrder.indexOf(index) < remainder ? 1 : 0));

  const selected: T[] = [];
  let shortfall = 0;
  tiers.forEach((tier, index) => {
    const wanted = takes[index] ?? 0;
    const actual = Math.min(wanted, tier.length);
    selected.push(...sampleWithoutReplacement(tier, actual, random));
    shortfall += wanted - actual;
  });

  if (shortfall > 0) {
    const chosen = new Set(selected);
    const leftovers = sorted.filter((item) => !chosen.has(item));
    selected.push(...sampleWithoutReplacement(leftovers, shortfall, random));
  }

  return shuffle(selected, random);
}

/** Default rounds for games that do not expose a round-count setting. */
export const ROUNDS_PER_GAME = 10;
