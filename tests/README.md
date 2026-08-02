# Tests

The suite is intentionally capped at **exactly 10 collected pytest cases** in
`test_scenarios.py`, per repository policy.

| # | Test | Coverage purpose |
|---|------|------------------|
| 1 | `test_website_static_catalog_contract` | Static storefront bundle, catalogue/styling services, web server contract |
| 2 | `test_vlm_bbox_parsing_and_validation` | VLM bbox contracts, malformed rejection, fenced JSON parsing |
| 3 | `test_sam_masks_and_catalog_cutouts` | SAM crop/mask helpers and catalog cutout centering |
| 4 | `test_catalog_template_geometry` | Template canvas invariants and garment-specific geometry |
| 5 | `test_catalog_template_selector_and_confidence` | VLM-label mapping, confidence, overrides, manifest alignment |
| 6 | `test_gemini_credential_config_and_redaction` | Credential resolution, missing-key errors, secret redaction |
| 7 | `test_gemini_request_artifact_provenance_and_prompt_policy` | Provenance guards, prompt policy, deterministic artifacts |
| 8 | `test_gemini_generation_one_call_mocked` | Mocked one-call generation, normalization, metadata redaction |
| 9 | `test_production_pipeline_idempotency_and_output_contract` | Production reuse, 1K output contract, override/geometry paths, catalog index + lexical search |
| 10 | `test_texture_qc_and_derived_geometry_invariants` | Texture/color QC and derived geometry validation |

Shared fixtures and builders live in `helpers.py` (not collected by pytest).

Tests never use real Gemini credentials or network calls; generation paths use
mocks only.
