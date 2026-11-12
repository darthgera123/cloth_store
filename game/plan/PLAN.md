# Game Night — Plan

Source documents:

- **[UI-DESIGN.md](UI-DESIGN.md)** — visual specification (palette, mandalas,
  typography, screens A–H, motion, constraints).
- **Framework specification** — four games, host/audience split, scoring, undo,
  recovery.
- **Hosting directive** — static deployment, no database, host browser owns the
  session, stateless relay for cross-device sync.

## Decisions taken

1. **Static frontend** — React 19 + TypeScript + Tailwind 4 (Vite), published to
   GitHub Pages at `/cloth_store/game/` with hash routes (`#/host`,
   `#/display?code=…`).
2. **Host is the source of truth** — the pure engine runs in the host browser;
   the audience is read-only.
3. **No persistence beyond `sessionStorage`** — the session, undo history and
   revision live in the host tab; closing it ends the session. No database, no
   accounts, no host tokens.
4. **Two transports, one message format** — BroadcastChannel for same-device
   windows, an optional WebSocket relay for the TV. The relay is stateless,
   memory-only, and deployed separately (never on Pages).
5. **Privacy** — the question bank is a host-only chunk; the audience receives
   `PublicState` with concealed answers, prices, votes and tallies removed.
6. **Recovery** — refresh restores from `sessionStorage`; the display requests a
   fresh snapshot on open; a lost host shows a session-ended panel.
7. **Game rules** — the simplified alternating-team Family Feud (per-team
   strikes, shared pot, last team standing, revealed-total tiebreak, explicit
   pot award, alternating starters) replaces the earlier steal variant.
8. **Event game menu** — only Family Feud and The Price Is Right appear in
   selection and on the audience programme; Herd Mentality and Who's Most
   Likely remain implemented but hidden (`src/lib/games.ts`). Family Feud now
   defaults to two strikes per family.
9. **How to Play slides** — a `RULES` phase before the title card, with
   host-driven slides stored in `src/rules/slides.ts` (separate from questions),
   reopenable mid-round without touching scores or round state.

## Milestones

| Milestone | State |
|---|---|
| F-1 types, question schemas, session model, state machine | done |
| F-2 session setup, display, real-time sync | done (BC + relay) |
| F-3 Family Feud (alternating rules, scoring, undo) | done |
| F-4 Herd Mentality | done |
| F-5 Who's Most Likely? | done |
| F-6 The Price Is Right | done |
| F-7 shared scoring, recovery, session controls | done |
| F-8 testing and edge cases | done (`bun test`, engine + relay) |
| F-9 static hosting, base path, Pages workflow | done |

## Open items

- Real question corpus (Phase 2, as agreed).
- Optional later: phone voting, QR join, speech recognition, music, tournament
  leaderboard, question editor/import.
- Review the ported UI on the actual television at 1920×1080.
