# Game Night

Host-run family game-show for eight players: **Family Feud**, **Herd
Mentality**, **Who's Most Likely?** and **The Price Is Right**, in the
lavender-and-gold invitation styling from `plan/UI-DESIGN.md`.

Built for one evening. The static app runs on GitHub Pages, the host browser
owns the session, and an optional stateless relay connects a TV on another
device. No database, no accounts, no server-side persistence.

## Run

```bash
bun install
bun run dev        # http://127.0.0.1:5173
```

| Route | Use |
|---|---|
| `/#/host` | Host dashboard (laptop) |
| `/#/display` | Audience display (TV or projector) |

Open `/#/host`, enter the eight names, create the session, then open
`/#/display` on the TV and enter the four-letter code shown in the host bar.

Production build and local preview:

```bash
bun run build
bun run preview    # http://127.0.0.1:8091
```

### Cross-device relay (Mode B)

```bash
bun run relay      # ws://127.0.0.1:8092
```

Point the app at it at build/dev time:

```bash
VITE_RELAY_URL=ws://127.0.0.1:8092 bun run build
```

Without `VITE_RELAY_URL` the app runs same-device only. The relay keeps rooms
in memory and forwards messages; it stores nothing and is **not** hosted on
GitHub Pages.

## How state flows

```
host browser (source of truth)
  engine → sessionStorage → public snapshot
                              ├── BroadcastChannel  (same device, Mode A)
                              └── WebSocket relay   (another device, Mode B)
                                                     ↓
                                            audience display (read-only)
```

- The host applies every action locally through the pure engine, persists the
  session in `sessionStorage`, then publishes a `PublicState` snapshot.
- The audience only ever receives `PublicState`: concealed answers, prices,
  votes, tallies and per-player data are stripped by `projectPublic`.
- Both transports use the identical `{ type: "snapshot", code, revision,
  payload }` message; the display ignores revisions it has already applied.
- The display sends `hello` on open and every three seconds until it has a
  snapshot, so a refresh or a reopened TV re-syncs from the host.
- If the host goes away for 20 seconds, or ends the session explicitly, the
  display shows a **Session ended** panel instead of inventing state.

### Storage

`sessionStorage` is the only browser persistence: `gn:host-session:v1` holds the
host's state, undo history and revision; `gn:last-code` remembers the display's
session code. No `localStorage`, no IndexedDB, no database. Closing the host tab
ends the session by design.

## Architecture

```
src/engine/engine.ts       pure state machine (createSession / applyAction / projectPublic)
src/questions/bank.ts      bundled JSON questions, zod-validated, host-only chunk
src/lib/types.ts           domain types, zod schemas, action union
src/lib/herd.ts            answer normalisation and grouping
src/transport/link.ts      BroadcastChannel + relay client, one message shape
src/client/useHostGame.ts  host: engine + sessionStorage + publish
src/client/useDisplaySession.ts  audience: snapshots, presence, session-ended
src/display/               audience screens and boards
src/host/                  host dashboard, per-game controls
relay/index.ts             stateless WebSocket relay (Bun)
```

`HostApp` and the question bank are loaded as separate chunks, so the audience
never downloads question data.

## Games

| Game | Mechanics |
|---|---|
| Family Feud | Shared round pot; correct answers credit the guessing team's revealed value and alternate the turn; three strikes per team; round ends when the board is clear or both teams are out. One team left → it takes the whole pot. Otherwise the higher revealed total wins, with a host tiebreak. Explicit "Award pot" before the cumulative scores move; starters alternate each round. |
| Herd Mentality | Record eight answers, auto-normalise, merge/split groups, majority scoring with configurable ties, optional Pink Cow including "blocks winning" |
| Who's Most Likely? | Manual vote counts, reveal, ties, casual (no points) or competitive scoring |
| The Price Is Right | Individual or team guesses, lock, reveal guesses, price reveal, closest-without-going-over with fallback, ties |

Shared host controls: start/next/skip/restart round, end game, pause, countdown
timer, undo (snapshots include scores), manual score edits, reset confirmation,
session end. Display controls: fullscreen and sound on/off.

## Questions

`questions/*.json`, one array per game, validated with zod at load. Optional
`category`, `difficulty` and `image` fields are supported. Order follows the
file; enable "Shuffle question order" in setup to shuffle per session. Phase 1
ships dummy questions only — the real corpus is a data-only change.

## Deploy to GitHub Pages

`.github/workflows/pages.yml` builds the app with
`BASE_PATH=/cloth_store/game/` and publishes:

- the existing storefront bundle at the site root (when `dist/cloth-store`
  exists in the checkout), and
- this game at `/cloth_store/game/`.

Set the repository variable `RELAY_URL` (for example
`wss://relay.example.com`) to enable Mode B; leave it unset for same-device
only. Routes are hash-based, so refreshing `…/game/#/host` and
`…/game/#/display?code=XXXX` works on Pages without rewrites.

## Tests

```bash
bun test
```

- `tests/engine.test.ts` — phase guards, Feud alternating rules and pot award,
  herd grouping and ties, most-likely and price winners, restart rollback,
  public-state privacy.
- `tests/relay.test.ts` — spawns the relay and checks room isolation, no
  replay after disconnects, and malformed-message rejection.

## Limits

Optional later: phone voting, QR joining, speech recognition, music, a
tournament leaderboard, a question editor. None of them block the event.
