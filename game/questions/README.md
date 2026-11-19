# Question banks

The Markdown files in this folder are the **single source of truth** for every
question. `generated.json` is produced from them by `bun run questions` (the
normal `bun run build` does this for you) — never edit it by hand.

One `## QUESTION-ID` block per question. IDs are stable: they are what a host
session stores for its ten selected rounds, so do not rename an ID once it has
been used.

Every new game randomly samples **10, 15 or 20 unique questions** (chosen in
the host setup) from that game's file; when the file is shorter, all of them are
used and the host screen shows a notice.

## Family Feud — `family-feud.md`

```md
## FF-001

English: Name something an Indian mom asks when you leave the house.

Hindi: Ghar se nikalte waqt mummy kya poochti hai?

| Points | Hindi | English |
|---|---|---|
| 34 | Kahan ja raha/rahi hai? | Where are you going? |
| 27 | Kisse milne ja raha/rahi hai? | Who are you meeting? |
| 19 | Kab wapas aayega/aayegi? | When will you be back? |
| 12 | Pahunch ke call/message karna | Text/call me when you reach |
| 8 | Kuch khaya hai? | Have you eaten? |
```

Requirements: exactly five answer rows, integer points totalling **100**, both
English and Hindi text. Optional: `Category:`, `Difficulty:` (`easy`/`medium`/
`hard`).

## The Price Is Right — `price-is-right.md`

```md
## PIR-001

Item: Maggi Masala Noodles

Size: 280 g (4-pack)

Image: products/PIR-001.jpg

Price: 60

Currency: INR

Unit: pack

Source: https://blinkit.com/prn/x/prid/171258
```

`Item`, `Size`, `Image`, `Price` and `Source` are required. `Currency` must be
`INR`; `Description` and `Unit` are optional. Images live in
`public/products/` and are resolved against the deployed base path. The price
is only shown after the host reveals it.

## Herd Mentality — `herd-mentality.md`

```md
## HM-001

Question: Name a food people commonly eat at weddings.
```

## Who's Most Likely — `whos-most-likely.md`

```md
## ML-001

Question: Who's most likely to arrive early to every event?

Eligible: all

Allow self vote: yes
```

`Eligible` currently only accepts `all`; `Allow self vote` defaults to `yes`.

## Adding a question

1. Add a `## ID` block to the right file.
2. Run `bun run questions` (or `bun run build`) to regenerate and validate.
3. Commit the Markdown file (and `generated.json`).

Validation errors name the file and question ID, for example:

```
family-feud.md (FF-014): Family Feud point values must total 100 (found 97)
```
