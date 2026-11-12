# Game Night — Plan

Source of truth: **[UI-DESIGN.md](UI-DESIGN.md)** — full UI specification
(palette, mandalas, typography, screens A–H, motion, responsive rules,
constraints, component list, milestones UI-1…UI-6, acceptance criteria).

Build order follows the spec's milestones. Code lives in `../`
(`index.html`, `host.html`, `static/`, `data/`).

## Decisions taken

1. **Tech** — plain HTML/CSS/JS modules, no build step, served by
   `python3 -m http.server` (same approach as `dist/cloth-store`).
2. **Host vs audience** — two routes: `index.html` (audience) and
   `host.html` (host), same browser profile, synced with `BroadcastChannel`.
3. **Question content** — authored in `data/games.json`; currently six sample
   Family Feud questions to replace with yours.
4. **Persistence** — `localStorage`, so a reload keeps scores.
5. **The Price Is Right art** — will use real `final_catalog/**/output.png`
   renders when that game is built (UI-5).

## Progress

| Milestone | State |
|---|---|
| UI-1 tokens, mandala SVGs, ornamental borders | done |
| UI-2 welcome + game selection | done |
| UI-3 Family Feud audience + host dashboard | done |
| UI-4 visual review | **awaiting your review** |
| UI-5 remaining games + winner screen | pending |
| UI-6 responsive/motion/a11y polish | in progress (TV, host, mobile checked) |

## Open notes

- Gold text is `--gold-ink` / `--gold-display` (darker than `#D4A52E`) so it
  clears the spec's own "no low-contrast gold on pale" rule; `--gold` stays the
  linework colour.
- Mandala watermarks inside the ivory panel were tried and removed — at any
  visible opacity they competed with the heading. Revisit on the winner screen.
