import { describe, expect, test } from "bun:test";
import type { SessionState } from "../src/lib/types";
import { migrateLegacySession } from "../src/lib/sessionMigration";

const asState = (value: Record<string, unknown>) => value as unknown as SessionState;

describe("legacy session migration", () => {
  test("an old Feud round is restarted and the evening is kept", () => {
    const legacy = asState({
      game: "family_feud",
      phase: "QUESTION_ACTIVE",
      paused: true,
      timer: { endsAt: 1, seconds: 1, label: "1s" },
      scores: { participants: {}, teams: { t1: 40, t2: 30 } },
      feud: {
        questionId: "FF-001",
        revealed: ["a1"],
        credited: { a1: "t1" },
        strikes: { t1: 1, t2: 0 },
        pot: 34,
        ended: false,
        outcome: null,
      },
    });

    const migrated = migrateLegacySession(legacy);
    expect(migrated.phase).toBe("ROUND_READY");
    expect(migrated.feud).toBeNull();
    expect(migrated.paused).toBe(false);
    expect(migrated.timer).toBeNull();
    expect(migrated.scores).toEqual(legacy.scores);
  });

  test("a current Feud round is left untouched", () => {
    const current = asState({
      game: "family_feud",
      phase: "QUESTION_ACTIVE",
      feud: { strikes: 1, ended: false },
    });
    expect(migrateLegacySession(current)).toBe(current);
  });

  test("other games are left untouched", () => {
    const pir = asState({ game: "price_is_right", phase: "REVEAL", feud: null });
    expect(migrateLegacySession(pir)).toBe(pir);
  });
});
