# Phone teams — The Price Is Right (Firebase)

Real-time phone guesses for The Price Is Right only. The host and TV keep
working exactly as before; when phone teams are enabled, three teams of two
join from `/join/`, submit a price, and the TV shows the reveal and the team
leaderboard.

The implementation is modular: without Firebase configuration the button is
disabled and the game falls back to the existing host-entered guesses.

## How it fits together

```
host browser (authority)                 Firebase Realtime Database
  engine ──────────────── board, teams, guesses (write) ──────────► phones
     ▲                                                              │
     └──────────── join + guess (read) ◄────────────────────────────┘
  display  ◄── host snapshots (BroadcastChannel / relay) ── host
```

- The host is the only writer of the item, lock state, price, scores and winners.
- A phone writes only its own team record and its own guess.
- Guesses live under `guesses/{teamId}/{roundId}` and are readable by that team
  and the host only; the audience never receives them before the reveal.
- The display is still driven by the host's snapshot, so it works exactly like
  the rest of the app.

## Firebase project setup

This repository is already wired to the **game-night-price** project:

- `.env.production` holds the public web config (Vite loads it for
  `bun run build`).
- `.firebaserc` points the CLI at the project.
- Anonymous Authentication is enabled.
- The Realtime Database exists in `asia-southeast1`.

The public web config is safe to ship; authorization lives in
`firebase/database.rules.json`. **Publish the rules before using phone teams** —
the database starts locked and denies every request until you do.

Either paste `firebase/database.rules.json` into
**Realtime Database → Rules** in the
[console](https://console.firebase.google.com/project/game-night-price/database/game-night-price-default-rtdb/rules),
or deploy with the CLI:

```bash
npx firebase login          # once per machine
npm run deploy:rules        # firebase deploy --only database
```

For local development the same values live in `.env.local` (gitignored) so
`bun run dev` and `bun run build` both use the real project.

## Local testing

```bash
# 1. Emulators (needs Node + JDK 21+)
npx firebase emulators:start --only auth,database --project demo-game-night

# 2. Point the app at them (.env.local)
VITE_FIREBASE_API_KEY=demo-key
VITE_FIREBASE_AUTH_DOMAIN=demo-game-night.firebaseapp.com
VITE_FIREBASE_DATABASE_URL=http://127.0.0.1:9000?ns=demo-game-night-default-rtdb
VITE_FIREBASE_PROJECT_ID=demo-game-night
VITE_FIREBASE_APP_ID=demo-app
VITE_FIREBASE_AUTH_EMULATOR=http://127.0.0.1:9099

# 3. Build and serve
bun run build
bun run serve
```

The emulator loads `firebase/database.rules.json`, so the security rules are
exercised locally. `bun test` includes `tests/multiplayer-rules.test.ts`, which
skips itself when the emulators are not running.

Manual run-through:

1. Open `/host/`, enable **Phone teams for The Price Is Right** under *Game
   rules*, create the session.
2. Choose **The Price Is Right** → Skip rules → Start round 1.
3. Open `/display/?code=CODE` — the QR and join URL appear with the item.
4. Open `/join/?code=CODE` on three phones (or three separate browser
   profiles), name each team, submit a price.
5. Lock submissions → reveal guesses → reveal price. The TV shows guesses,
   price and leaderboard; each phone shows its own result.

Each phone keeps its team identity in `sessionStorage`, so a refresh rejoins the
same team. Renaming or removing a team from the host updates the phone.

## Rules and privacy

| Actor | Can write | Can read |
|---|---|---|
| Host (first authenticated user to create the session) | board, teams, scores, any guess, meta | everything in the session |
| Team phone | its own `teams/{id}` and `guesses/{id}/{currentRound}` while unlocked | board, teams, its own guess |
| Anyone else | nothing | board, teams, meta |

- Guesses cannot be written for a stale round (`board.roundId` must match) or
  after the host locks submissions.
- Phones never receive other teams' guesses: the rules deny reads outside their
  own team, and the host never publishes guesses before the reveal.
- Prices are only written to the board after the host reveals them.

## Deploying to GitHub Pages

The workflow builds with `BASE_PATH=/cloth_store/game/`; the join URL and QR use
`import.meta.env.BASE_URL`, so they point at `/cloth_store/game/join/?code=…`.
The public Firebase config is committed in `.env.production`, so the Pages build
needs no extra variables.

Anonymous auth must allow the Pages domain: **Authentication → Settings →
Authorized domains → add `darthgera123.github.io`**.

## Cleanup

- **End Session** on the host removes the whole `sessions/{code}` node; phones
  then show “This session has ended”.
- Finishing The Price Is Right (game result) also removes the temporary data.
- Sessions older than 12 hours are rejected by the join page.
- Abandoned sessions can be removed in the Firebase console or with
  `npx firebase database:remove /sessions/CODE --project your-project`.

No analytics, profiles or historical storage are used.
