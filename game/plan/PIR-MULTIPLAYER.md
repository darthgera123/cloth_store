# The Price Is Right — phone multiplayer (plan)

Extends the existing Firebase phone mode from "3 teams" to **3 teams or 6
individuals**, moves scoring to a **top-3 podium**, and splits the reveal into
two host steps: price first, leaderboard second.

## 1. Modes

| Mode | Slots | Join label | Leaderboard rows |
|---|---|---|---|
| `teams` | 3 | Team name | 3 |
| `individual` | 6 | Your name | 6 |
| `off` | — | — | host-entered guesses (existing local mode) |

- Mode is chosen once per game in setup (not per round), so identities and
  totals stay stable.
- The phone UI is the same; only copy and capacity change, driven by
  `board.mode` / `board.capacity`.
- Join is refused when the slot count is full (client-side check against the
  entries node; the host can still remove an entry).

## 2. Firebase shape

`sessions/{code}/` keeps its current shape; entries stay under `teams/` so the
published rules need no new paths (`teams` = teams or individuals).

```
meta:   { hostUid, createdAt }
teams/{entryId}:    { name, uid, joinedAt }          # 3 or 6 entries
guesses/{entryId}/{roundId}: number                  # own guess only
board: {
  roundId, index, item, description, image, currency, priceUnit,
  mode: "teams" | "individual",
  capacity: 3 | 6,
  locked, revealed,                 # submissions locked / guesses public
  priceRevealed,                    # price visible, no scores yet
  leaderboardRevealed,              # podium + totals visible
  price: number | null,             # written only when priceRevealed
  podium: [{ entryId, rank, points, distance }],
  scores: { entryId: number }
}
```

Writes:

| Actor | Writes |
|---|---|
| Host | `board`, `scores`/podium (inside board), any guess, entry rename/remove |
| Phone | own `teams/{id}`, own `guesses/{id}/{currentRound}` while unlocked |
| Audience display | nothing (still host snapshots) |

Rules stay as published: guesses readable only by their owner and the host,
board writes host-only, stale rounds rejected, locked rounds rejected.

## 3. Round flow (host-driven)

```
RULES (how to play)
  → QUESTION_ACTIVE   item shown, QR + join URL, submissions open
  → (phones submit/update; TV shows “n of N submitted”)
  → [Lock submissions]        board.locked = true
  → [Reveal guesses]          board.revealed = true      TV lists guesses
  → [Reveal price]            board.priceRevealed = true  TV shows price only
  → [Reveal leaderboard]      board.leaderboardRevealed = true
                              compute podium, add points, update scores
  → ROUND_RESULT              TV totals; phones show own rank + points
  → [Next item]               totals kept, guesses cleared
```

- Price and leaderboard are separate actions so the price lands as a beat.
- Points are awarded only by the "Reveal leaderboard" action; `Undo award`
  puts the points back and reopens the podium for an override.
- Reopening submissions is allowed until the guesses are revealed.

## 4. Scoring — approved

Rank submitted guesses by **absolute distance** from the actual price
(overbids count the same). Exact ties share the rank and the points using
standard competition ranking (1, 2, 2, 4…). Points: **3 / 2 / 1** for ranks
1–3; ranks 4–6 score nothing. With 3 teams every team scores 3/2/1.

The podium stores `{ entryId, rank, points, distance }` so the TV can show
guesses, distances and points together, and undo can subtract exactly.

## 5. Engine changes (`src/engine`)

- `PriceParty` gains `mode`, `capacity`, `leaderboardRevealed`, `podium`.
- New actions: `pir_party_mode` (setup), `pir_leaderboard` (podium + award),
  keep `pir_undo_award`, `pir_override` (replace podium before awarding).
- `pir_reveal_price` no longer computes a single winner; it only exposes the
  price. The generic PIR (host-entered) path is untouched.
- Ranking helper is pure and unit-tested (ties, overbids, missing guesses).
- `pir_award` stays for the override path.

## 6. UI changes

**Host panel** — mode label, capacity progress, entries table (name, guess,
score, remove), buttons: Lock / Reopen, Reveal guesses, Reveal price, Reveal
leaderboard, Undo award, Next item; manual guess fields.

**TV** — join card (QR + URL) until locked; progress; guesses after reveal;
price alone after price reveal; podium with distances/points and totals after
the leaderboard reveal; finished-game screen uses the same totals.

**Phone** — label per mode; input + submit/update until lock; “guess received”;
after price reveal show the price; after the leaderboard reveal show own rank,
points earned and total.

## 7. Compatibility

- `mode` defaults to `teams` (3) so existing sessions and the published rules
  keep working; no rule change is required.
- Sessions created before this change load with mode `teams` / capacity 3.
- Firebase stays optional: without configuration the local host-entered PIR
  flow is unchanged.

## 8. Testing

- Unit: ranking (under/over, ties, fewer than three guesses), point awarding,
  undo, mode capacity (6 individuals), next round keeps totals, stale round.
- Rules: existing probe still passes; add a check that board fields are
  host-only.
- Browser: 6 phone tabs → submit → lock → reveal guesses → reveal price
  (no scores) → reveal leaderboard (podium + totals) → next item → end session
  → Firebase cleanup.
- Deploy: Pages build under `/cloth_store/game/`, join URL from `BASE_URL`.

## 9. Decisions (approved)

1. **Points**: 3 / 2 / 1 for ranks 1–3.
2. **Ranking**: pure absolute distance, overbids included.
3. **Ties**: shared rank and points (standard competition ranking).
4. **Mode**: fixed per game, selected in setup (3 teams or 6 individuals).

## 10. Capacity safety

Slots are claimed with Realtime Database transactions over a fixed id list
(`t1..t3`, `p1..p6`). A transaction aborts if the slot is already occupied, so
two phones racing for the last slot cannot both win; the loser tries the next
slot and sees “all slots taken” when none remain. The engine additionally
validates the slot id against the mode and the capacity, and the host can
remove an entry to free its slot.
