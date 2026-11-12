# Game Night

Host-operated family game-show for eight players: **Family Feud**, **Herd
Mentality**, **Who's Most Likely?** and **The Price Is Right**.

Phase 1 is the framework: complete mechanics, host controls, audience display,
scoring, undo, persistence and recovery. The question files hold **dummy
content** only — real questions come in Phase 2.

## Run

```bash
bun install
bun run build      # typecheck + bundle the client into dist/
bun run start      # http://127.0.0.1:8091
```

| Route | Use |
|---|---|
| `/host` | Private dashboard, laptop/tablet |
| `/display` | Audience screen, television or projector |

Open `/host`, enter eight names, create the session, then open `/display` on
the TV and enter the four-letter session code shown in the host bar.

### Development

```bash
bun run start      # server on :8091
bun run dev        # Vite on :5173, proxies /api and /ws
```

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8091` | Server port |
| `DB_PATH` | `.data/sessions.db` | SQLite session store |
| `QUESTIONS_DIR` | `questions/` | Question bank directory |

## Architecture

```
questions/*.json        question bank (server-only, zod-validated)
src/lib/types.ts        domain types, zod schemas, action union
src/lib/herd.ts         answer normalisation and grouping
src/server/engine.ts    pure state machine: createSession / applyAction / projectPublic
src/server/db.ts        SQLite sessions, snapshots, applied-action ids
src/server/index.ts     Bun HTTP + WebSocket server, static bundle
src/client/useSession.ts  host/display transport: REST + WS, reconnect
src/display/            audience screens and boards
src/host/               host dashboard, per-game controls
```

- The **server owns all state**. The host sends actions; the server validates the
  phase, mutates, persists, and broadcasts.
- **Two payloads**: the display receives `PublicState` (hidden answers, prices,
  votes and tallies stripped); the host receives `HostState` with the full
  session and the question bank for the current game.
- **Undo** restores a full pre-action snapshot (scores included), not a visual
  rollback. Snapshots are capped at 50.
- **Idempotency**: every action carries an `actionId`; duplicates are recorded in
  `applied_actions` and ignored, so a double click cannot award twice.
- **Reconnect**: the display and host re-fetch state, then reopen the socket; the
  first message is always a full snapshot. `localStorage` keeps the host token
  and the last display code.

### Phases

`LOBBY → GAME_INTRO → ROUND_READY → QUESTION_ACTIVE → ANSWERING → REVEAL →
ROUND_RESULT → GAME_RESULT`

Invalid transitions throw `EngineError` and never reach the display.

## Games

| Game | Mechanics implemented |
|---|---|
| Family Feud | Reveal answers into a pot, strikes with configurable limit, automatic steal opportunity, steal won/missed, manual award, round multiplier, two teams |
| Herd Mentality | Record eight answers, auto-normalise, merge/split groups, majority scoring with configurable ties, optional Pink Cow including "blocks winning" |
| Who's Most Likely? | Manual vote counts, reveal, ties, casual (no points) or competitive scoring |
| The Price Is Right | Individual or team guesses, lock, reveal guesses, price reveal, closest-without-going-over with fallback, ties |

Shared controls: start/next/skip/restart round, end game, pause, countdown
timer, undo, manual score edits, back to game selection, reset with confirmation.

## Questions

One JSON array per game. `server/questions.ts` validates every entry with zod,
rejects duplicate ids and groups by `game`.

```json
{
  "id": "ff-demo-001",
  "game": "family_feud",
  "question": "Name something people bring on a family trip.",
  "answers": [
    { "id": "a1", "text": "Food", "points": 40 },
    { "id": "a2", "text": "Clothes", "points": 30 }
  ]
}
```

Other schemas live in `src/lib/types.ts`; optional `category` and `difficulty`
metadata are accepted, as are optional `image` paths for price items (served
from `public/`). Questions are ordered by file order, or shuffled per session
when "Shuffle question order" is enabled. Used ids are tracked in the session.

## Tests

```bash
bun test
```

- `tests/engine.test.ts` — phase guards, scoring, steals, ties, merge, restarts,
  privacy of the public projection, undo-relevant rollbacks.
- `tests/server.test.ts` — spawns the real server on a temp database and drives
  HTTP + WebSocket: host-token enforcement, private/public separation,
  duplicate-action idempotency, undo, display rejection, reconnect persistence.

## Phase 1 boundaries

Implemented: everything in the specification's "Essential" list. Not
implemented (optional/later): phone voting, QR joining, speech recognition,
background music, tournament leaderboard, question editor/import.
