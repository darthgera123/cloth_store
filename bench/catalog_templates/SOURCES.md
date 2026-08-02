# Online template source research

Research date: 2026-07-31. Goal: find a **coherent** CC0/public-domain SVG
silhouette set covering all five catalog categories:

1. long-sleeve top
2. short-sleeve top
3. blazer / suit jacket
4. skirt
5. pants / trousers

## Candidates reviewed

| Source | URL | License (stated) | Fit |
|--------|-----|------------------|-----|
| SVG Repo — clothing vectors | https://www.svgrepo.com/vectors/clothing/ | Mixed per icon; CC0 subset exists | **Incomplete / incoherent.** Icons come from many unrelated packs (429xxx t-shirt/pants/skirt, 416xxx fashion shirts, separate suit icons). No single pack with all five front-facing catalog silhouettes. Blazer options are full suits, biker jackets, or worn-on-body figures — not isolated structured blazers. |
| SVG Repo — licensing page | https://www.svgrepo.com/page/licensing/ | CC0 + CC-BY + others | Site-wide policy does not guarantee CC0 for every icon; license must be verified per file. Mixing icons risks inconsistent style and ambiguous compliance. |
| SVG Repo — individual CC0 icons (examples) | https://www.svgrepo.com/svg/169038/t-shirt-silhouette , https://www.svgrepo.com/svg/429145/clothing-pants-trousers , https://www.svgrepo.com/svg/416026/clothing-mini-skirt , https://www.svgrepo.com/svg/133826/suit | CC0 (per page) | Useful individually but **different art styles** and the “suit” asset is not a standalone blazer cutout. Would require manual normalization and legal review per asset. |
| Openclipart — clothing | https://openclipart.org/detail/221267/clothing | Public domain (site default) | Composite/miscellaneous clothing sheet sourced from Pixabay; not a matched five-category catalog set. |
| Openclipart — clothing outline pack (mirror) | https://www.woovector.com/clothing-outline-socks-pants-jackets-clip-art-249169.html | Public domain (attributed to openclipart) | Outline sheet with socks/pants/jackets; missing short vs long sleeve distinction and no matched skirt/blazer catalog set. |
| FreePNGimg — fashion silhouettes | https://freepngimg.com/svg/color/C0C0C0/146017-fashion-silhouettes | CC0 1.0 Universal (stated) | Single composite illustration (2016×1600), not five separate normalized garment templates; would require manual extraction and re-centering. |
| Tuts King / snap2objects clothing silhouettes | https://tutsking.com/vectors/clothing-silhouettes | CC-BY 3.0 | **Not adopted** — attribution-required license is weaker than CC0 for repo-owned benchmark assets. |

## Conclusion

**No suitable complete online set was integrated.**

Reasons:

1. **Coverage gap** — no one CC0/PD source provides all five required categories in a unified front-facing catalog silhouette style.
2. **Style coherence** — SVG Repo/Openclipart collections mix outline icons, worn garments, and full outfits; blending them would produce inconsistent geometry targets.
3. **Blazer specificity** — available “suit/jacket” CC0 icons are either full suits, casual jackets, or figures wearing clothes, not generic structured blazer cutouts.
4. **License clarity** — SVG Repo hosts multiple license types; per-icon verification would be required before import, and mixed packs increase legal ambiguity.

## Repo decision

Keep **internal deterministic polygon sources** in
`src/cloth_store/catalog_templates.py`, regenerated to SVG/PNG by
`cloth-store-templates`. This preserves:

- explicit repo-owned geometry
- consistent scale, centering, and margins across all five templates
- no third-party asset dependency or attribution burden

If a future CC0 pack appears that covers all five categories in one style,
record it here with exact URLs, author, license text, and import path before
adoption.
