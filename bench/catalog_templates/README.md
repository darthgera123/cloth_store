# Catalog templates

Canonical **geometry/layout targets** for garment cataloguing and reconstruction
experiments. These are neutral front-facing silhouettes — not photorealistic
garments, branding, or fashion details.

## Templates

| ID | Role | Notes |
|----|------|-------|
| `top_full_sleeve` | top | Long sleeves to wrist; distinct from half-sleeve |
| `top_half_sleeve` | top | Short sleeves ending mid-upper arm |
| `blazer` | top | Structured long-sleeve blazer; open front with lapels |
| `waistcoat_closed` | top | Sleeveless closed/buttoned waistcoat or vest; V-neck lapels, no open front gap |
| `skirt` | bottom | A-line lower garment; no leg separation |
| `skirt_pencil` | bottom | Straight/fitted pencil skirt; waist ~34%, hip ~47%, hem ~43% canvas width |
| `pants` | bottom | Straight trousers with split-leg inner separation from y=0.10 |

## Conventions

- **512×512 RGB** on opaque white `(255, 255, 255)`
- **~4% safe margin** on each side; silhouettes scaled to fill the inner box
- **Visible bounding box centered** horizontally and vertically on canvas
- Front-facing, symmetric silhouettes
- Neutral flat fill `(90, 90, 90)` — geometry only

Plan 1 photo cutouts still use 9% margin; these templates intentionally use a
tighter margin so silhouettes read larger as layout targets.

## Source provenance

Online CC0/PD template packs were researched; none provided all five categories
in one coherent front-facing catalog style. See
[`SOURCES.md`](SOURCES.md) for URLs, licenses, and the adoption decision.

Assets are generated from repo-owned polygon definitions in
`src/cloth_store/catalog_templates.py`.

## Layout

```text
bench/catalog_templates/
  manifest.json              # metadata, categories, provenance
  SOURCES.md                 # online source research notes
  sources/*.svg              # generated vector renders
  generated/*.png            # 512×512 raster targets
  generated/contact_sheet.jpg
  generate.sh                # deterministic regeneration wrapper
```

Regenerate after editing silhouettes:

```bash
./bench/catalog_templates/generate.sh
# or:
uv run cloth-store-templates
```

## Plan 2 integration

`bench/plan2_reconstruction/manifest.json` references these categories under
`template_categories` for optional geometry/layout comparison. Plan 2 cases and
the running Flux smoke job continue to use frozen Plan 1 photo cutouts only.
