# Game Night

Lavender-and-gold game night for the engagement: an audience display and a
host dashboard built from `plan/UI-DESIGN.md`.

## Run

```bash
cd game
python3 -m http.server 8090
```

| | URL | Use |
|---|-----|-----|
| Audience | http://127.0.0.1:8090/ | TV / projector |
| Host | http://127.0.0.1:8090/host.html | laptop or tablet |

Open both in **the same browser profile** on one machine. The two tabs sync
through a `BroadcastChannel`; `localStorage` keeps the state across reloads.
No server or build step.

## Host keys

`R` reveal all · `H` hide all · `N` next question · `1`/`2` active team ·
`S` strike on the active team.

## Content

`data/games.json` holds the team names and the Family Feud questions
(6 questions × 6 answers). Edit and reload; nothing else depends on the copy.

## Built so far

- **UI-1** design tokens, mandala linework, invitation panel, buttons, tiles
- **UI-2** welcome screen, game selection
- **UI-3** Family Feud audience board and host dashboard

Herd Mentality, Who's Most Likely? and The Price Is Right are listed but
disabled until UI-5; the winner screen (UI-5/6) is also pending.

## Files

```
index.html        audience display
host.html         host dashboard
data/games.json   teams + questions
static/tokens.css  palette, type, motion tokens
static/components.css  ornaments, panels, buttons, tiles
static/screens.css     welcome, selection, Family Feud
static/host.css        host dashboard
static/mandala.js  generated mandala SVG
static/store.js    shared state + tab sync
static/audience.js audience rendering
static/host.js     host controls
```
