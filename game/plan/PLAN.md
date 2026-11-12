# Game Night — Plan

Source documents:

- **[UI-DESIGN.md](UI-DESIGN.md)** — visual specification (palette, mandalas,
  typography, screens A–H, motion, constraints). Delivered as the static
  prototype in commit `aa0c504`.
- **Framework specification** (from the client) — Phase 1 technical scope:
  server-authoritative engine, four games, host/audience split, scoring, undo,
  persistence, testing.

## Decisions taken

1. **Stack** — React 19 + TypeScript + Tailwind 4 + Vite, Bun HTTP/WebSocket
   server, SQLite (`bun:sqlite`). Single process, no external services.
2. **Two routes** — `/host` (private, host token) and `/display` (audience,
   session code). Previously a same-browser BroadcastChannel prototype; now
   server-authoritative so host and TV can be different devices.
3. **Authentication** — session creation returns a 32-byte host token, stored in
   the host browser's `localStorage`; actions and the private payload require it.
   The display joins with the four-letter code only.
4. **Undo** — full pre-action snapshots, capped at 50. Restoring scores is part
   of the snapshot, not a visual reverse.
5. **Question content** — dummy bank of 4/4/4/3 in `../questions/`; Phase 2 adds
   the real corpus without touching code.
6. **Pink Cow** — optional, configurable, can block winning.
7. **Who's Most Likely?** — casual by default; competitive scoring is opt-in.
8. **Price Is Right** — closest without going over; when every guess is over,
   configurable fallback (closest overall by default, or lowest guess).

## Framework milestones

| Milestone | State |
|---|---|
| F-1 types, question schemas, session model, state machine | done |
| F-2 session setup, host auth, display, real-time sync | done |
| F-3 Family Feud end-to-end (scoring, strikes, reveals, undo) | done |
| F-4 Herd Mentality | done |
| F-5 Who's Most Likely? | done |
| F-6 The Price Is Right | done |
| F-7 shared scoring, recovery, persistence, session controls | done |
| F-8 end-to-end testing and edge cases | done (`bun test`, 29 assertions paths) |

## Open items for Phase 2

- Real question corpus (not generated here, per the specification).
- Optional later: phone voting, QR join, speech recognition, music, tournament
  leaderboard, question editor/import.
- Design review of the ported UI at 1920×1080 on the actual television.
