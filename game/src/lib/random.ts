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

/** Rounds selected for every new game. */
export const ROUNDS_PER_GAME = 10;
