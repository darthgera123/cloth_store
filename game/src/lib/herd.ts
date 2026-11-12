/* Herd Mentality answer grouping. Pure: shared by the engine and the host UI. */

import type { HerdGroup, HerdState, Participant } from "./types";

export function normalizeAnswer(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Group answers by normalized text, following host merges. */
export function herdGroups(herd: HerdState, participants: Participant[]): HerdGroup[] {
  const resolve = (key: string): string => {
    let cursor = key;
    const seen = new Set<string>();
    for (;;) {
      const next = herd.merges[cursor];
      if (!next || next === cursor || seen.has(cursor)) return cursor;
      seen.add(cursor);
      cursor = next;
    }
  };

  const buckets = new Map<string, { ids: string[]; first: string }>();
  for (const participant of participants) {
    const raw = (herd.answers[participant.id] ?? "").trim();
    if (!raw) continue;
    const key = resolve(normalizeAnswer(raw));
    const bucket = buckets.get(key) ?? { ids: [], first: raw };
    bucket.ids.push(participant.id);
    buckets.set(key, bucket);
  }

  return [...buckets.entries()]
    .map(([key, bucket]) => ({ key, label: bucket.first, participantIds: bucket.ids }))
    .sort(
      (a, b) =>
        b.participantIds.length - a.participantIds.length || a.label.localeCompare(b.label),
    );
}
