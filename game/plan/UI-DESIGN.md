# Game Night — UI Design Specification

## 1. Design objective

Create a refined, elegant website inspired by traditional Indian engagement invitations, using a lavender, ivory, and gold visual identity.

The website is called **Game Night**.

The aesthetic should feel personal, celebratory, sophisticated, and distinctly Indian, without becoming overly decorative.

**Design philosophy:** An elegant Indian wedding invitation transformed into an interactive game-show experience.

Avoid generic AI-generated SaaS interfaces and flashy arcade aesthetics.

## 2. Colour palette

| Role | Colour | Hex |
|---|---|---|
| Background | Soft lavender | `#D8C6E9` |
| Main surface | Lavender-tinted ivory | `#FCFAFF` |
| Decorative accents | Warm gold | `#D4A52E` |
| Primary text | Deep plum | `#392747` |
| Secondary surfaces | Pale lavender | `#EEE5F5` |

Use solid colours, not gradients. Gold should resemble delicate printed foil rather than neon or metallic 3D effects.

## 3. Signature visual elements

### Ornamental mandalas

The defining feature is intricate gold mandala linework inspired by Indian wedding stationery.

- Position a large circular mandala partly outside the upper-left screen corner.
- Position another partly outside the lower-right corner.
- Use concentric floral geometry, lotus petals, paisley-inspired shapes, scalloped circles, and fine decorative detailing.
- Draw ornaments using thin gold SVG strokes rather than filled shapes.
- Allow portions of the mandalas to sit behind the central content panel.
- Use extremely faint mandala watermarks within the ivory panel where appropriate.

The mandalas should look like fine gold pen drawings on lavender paper.

Do not substitute generic flower icons, emojis, or CSS circles.

### Central invitation panel

The primary composition consists of a large ivory panel centred on a lavender background.

- Thin inset gold border.
- Small ornamental corner flourishes.
- Generous internal spacing.
- Rectangular geometry with minimal rounding.
- Optional subtle layered-paper edges.
- No heavy shadows.

The result should resemble premium printed wedding stationery.

## 4. Typography

**Ceremonial headings:** Great Vibes or Allura, in gold. Use for the title "Game Night" and special celebration headings.

**Secondary headings:** Cormorant Garamond, in deep plum.

**Game content and controls:** DM Sans, in deep plum, for questions, answers, scores, buttons, and host controls.

Use large, readable typography on the audience display. Never use decorative script for gameplay information.

## 5. Screen designs

### A. Welcome screen

The most invitation-like screen.

- Lavender background with prominent gold mandalas.
- Large central ivory panel.
- Gold calligraphic heading: **Game Night**
- Subtitle: *Two Families. One Celebration. A Little Friendly Competition.*
- Primary action: **Let the Games Begin**
- Tasteful gold framing and generous spacing.

### B. Game selection

Maintain the same background and invitation framing.

Display four games in a balanced two-column grid:

1. Family Feud
2. Herd Mentality
3. Who's Most Likely?
4. The Price Is Right

Use clean rectangular tiles, thin gold outlines, lavender hover states, and typography-led layouts.

Avoid decorative icons and unnecessary descriptions.

### C. Family Feud — audience display

- Large question heading.
- Symmetrical concealed answer rows.
- Gold answer numbers and point values.
- Lavender answer surfaces with thin gold borders.
- Clearly visible team scores and strikes.
- Smooth individual answer reveals.

### D. Herd Mentality — audience display

- Large centred question.
- Clear answering phase.
- Elegant majority-answer reveal.
- Simple player scores.
- Optional Pink Cow indicator.

### E. Who's Most Likely — audience display

- Large question.
- Balanced participant-name grid.
- Optional countdown.
- Tasteful vote-results animation.
- Clear winner or most-voted-person display.

### F. The Price Is Right — audience display

- Large product or scenario image.
- Item name and description.
- Prominent guesses.
- Dramatic but restrained actual-price reveal.
- Clear winning guess and score update.

### G. Host dashboard

The host dashboard should be a practical interpretation of the same design system.

- Ivory surfaces.
- Deep plum text.
- Lavender selection states.
- Thin gold dividers.
- Clearly labelled controls.
- Minimal ornamentation.
- No decorative artwork behind operational controls.

Prioritise speed, readability, and reliability.

### H. Winner screen

Return to the more decorative invitation aesthetic.

- Gold calligraphic celebration heading.
- Winner's name or team.
- Final score.
- Subtle gold confetti.
- Options to replay or return to game selection.

## 6. Animations

Use purposeful, restrained animation:

- Soft fades between screens.
- Smooth answer reveals.
- Gentle score transitions.
- Simple countdowns.
- Brief gold confetti for winners.

Avoid bouncing elements, neon effects, constant movement, excessive particles, or 3D transitions.

Respect reduced-motion accessibility preferences.

## 7. Responsive design

**Audience:** Optimise for a 16:9 television at 1920×1080, with readable typography from several metres away.

**Host:** Optimise for laptop and tablet operation, with large, accessible controls.

**Mobile:** Maintain usable layouts without compromising host functionality.

Keep essential gameplay information visible without scrolling on the audience screen wherever possible.

## 8. Design constraints

Strictly avoid:

- Glassmorphism and blurred panels.
- Neon colours or purple-blue gradients.
- Generic SaaS dashboards.
- Excessively rounded cards.
- Heavy shadows.
- Decorative icon overload.
- Low-contrast gold text on pale backgrounds.
- Mandalas overlapping questions or answers.
- Overly ornate gameplay screens.

The welcome and winner screens may be decorative. Active gameplay should remain clean and functional.

## 9. Reusable design system

Implement reusable components for:

- Mandala SVG decorations.
- Invitation-style panels and borders.
- Typography and colour tokens.
- Buttons and selection tiles.
- Question headings.
- Answer tiles.
- Scoreboards.
- Timers.
- Result overlays.
- Celebration effects.

Use consistent spacing, borders, typography, and motion throughout all four games.

## 10. UI implementation milestones

**UI-1:** Establish colours, fonts, design tokens, mandala SVGs, and ornamental borders.

**UI-2:** Build the welcome screen and game selection screen.

**UI-3:** Build the Family Feud audience screen and host dashboard.

**UI-4:** Review the visual direction before applying it to the remaining games.

**UI-5:** Complete all audience and host screens.

**UI-6:** Polish responsive layouts, transitions, and accessibility.

## Acceptance criteria

The UI is complete when:

- The site consistently resembles elegant lavender-and-gold Indian wedding stationery.
- All four games share a coherent visual identity.
- Gameplay remains readable on a television.
- Host controls are clear and easy to operate.
- Decorative elements never obstruct content.
- Animations are tasteful and non-distracting.
- The website does not resemble a generic AI-generated dashboard.
