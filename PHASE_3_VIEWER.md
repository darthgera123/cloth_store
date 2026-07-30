# Phase 3: Aesthetic Viewer

## Objective

Present the private wardrobe, search results, collections, and generated outfits
through a refined editorial interface.

## Experience principles

- Garment photography is the primary visual element.
- The interface feels calm, spacious, and intentional.
- Styling actions are direct: save, reject, lock, and replace.
- AI decisions remain editable and explainable.
- Mobile and desktop experiences are equally complete.

## Main views

### Wardrobe

- Editorial grid and compact list modes
- Filters for category, colour, formality, season, and status
- Semantic search
- Saved views and collections

### Import and review

- Selfie import progress
- Extracted garment comparison
- Mask and metadata review
- Duplicate resolution
- Approval and rejection actions

### Garment details

- Catalogue image and source-outfit context
- Normalized attributes
- Compatible garments and saved outfits
- Wear and feedback history

### Stylist

- Natural-language prompt
- Clarification of interpreted constraints
- Garment, collection, outfit, and weekly-plan results
- Explanations and quick refinements

### Outfit builder

- Visual garment slots
- Lock and replace individual pieces
- Compatibility feedback
- Save as an outfit or collection

### Weekly planner

- Outfits arranged by day
- Repetition and availability indicators
- Drag-and-drop reassignment
- Optional weather and calendar context

## Frontend architecture

- Next.js and TypeScript
- A reusable design-token system
- Typed API client generated from the backend contract
- Responsive image delivery
- Accessible keyboard, focus, and screen-reader behavior
- Optimistic updates for lightweight wardrobe actions

## Visual direction

- Neutral base palette with restrained accent colours
- Strong editorial typography
- Large, consistent garment imagery
- Subtle motion for transitions and outfit replacements
- Clear hierarchy without dense dashboard styling

The final visual language should be established with a small set of representative
screens before implementing the complete component library.

## Definition of done

- Phase 1 review and Phase 2 retrieval flows are fully accessible.
- Search, collection, and outfit interactions are responsive.
- Users can replace individual garments without rebuilding an outfit.
- Loading, empty, partial, and failure states are intentionally designed.
- Core workflows meet accessibility and responsive-layout requirements.
