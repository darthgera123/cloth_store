# Game Night — Plan

Source of truth: **[UI-DESIGN.md](UI-DESIGN.md)** — full UI specification
(palette, mandalas, typography, screens A–H, motion, responsive rules,
constraints, component list, milestones UI-1…UI-6, acceptance criteria).

Build order follows the spec's milestones. Code lands in `../static/`,
art in `../assets/`.

## Open decisions

These are not covered by the spec; answer before or during UI-1.

1. **Tech**: plain HTML/CSS/JS served statically (recommended — matches repo's
   existing `dist/cloth-store` approach), or a bundler/build step.
2. **Host vs audience**: one page with a host console panel, or two separate
   routes (`/` audience, `/host`) on one machine/projector.
3. **Question content**: authored by you in a data file (`data/games.json`)
   per game, or generated.
4. **Persistence**: in-memory only, or `localStorage` for scores between rounds.
5. **Product art**: use real `final_catalog/**/output.png` renders for
   *The Price Is Right*, or neutral placeholder illustrations.
