"""Structured garment-attribute extraction with the local Qwen vision model."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cloth_store.catalog_hash import sha256_file
from cloth_store.vlm_bbox import DEFAULT_MODEL, extract_response_text, strip_markdown_fences

ATTRIBUTE_SCHEMA_VERSION = 1

ObservationType = Literal["observed", "inferred"]
ConfidenceLevel = Literal["high", "medium", "low"]

ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "garment_class",
    "dominant_color",
    "likely_material",
    "surface_sheen",
    "texture_pattern",
    "weave_finish",
    "closures_details",
    "sleeve_cuff_neckline",
)

ATTRIBUTE_EXTRACTION_PROMPT = """\
You are a conservative garment attribute extractor for catalog imagery.

Analyze ONLY the garment visible in the provided image. Do not guess fiber composition unless \
explicitly labeled; describe appearance only.

Return ONLY valid JSON with no markdown fences. Wrap all fields under an "attributes" object:
{"attributes": {"garment_class": {...}, "dominant_color": {...}, ...}}

Each attribute value object must include value, confidence, observation_type, and evidence.

Policies:
- garment_class: normalized short label (e.g. office_blouse, blazer, trousers).
- dominant_color: plain-language color name; observed from pixels.
- likely_material: appearance-based only (e.g. "satin-like woven fabric"); never claim \
cotton/silk/poly unless visible label.
- surface_sheen: describe reflectivity (matte, soft satin-like, glossy, etc.).
- texture_pattern: solid, print, embroidery, etc.
- weave_finish: visible weave or finish if discernible; else "not discernible at this resolution".
- closures_details: buttons, zippers, plackets, trim visible in frame.
- sleeve_cuff_neckline: sleeve length, cuff style, neckline as visible.
- Use observation_type "observed" for direct pixel evidence; "inferred" for appearance guesses.
- Keep evidence concise and cite what is visible."""


class GarmentAttributeError(ValueError):
    """Raised when garment attribute extraction or validation fails."""


def _normalize_confidence(value: Any) -> ConfidenceLevel:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("high", "medium", "low"):
            return lowered  # type: ignore[return-value]
        with contextlib.suppress(ValueError):
            value = float(lowered.rstrip("%"))

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1.0:
            numeric /= 100.0
        if numeric >= 0.8:
            return "high"
        if numeric >= 0.5:
            return "medium"
        return "low"

    raise GarmentAttributeError(f"confidence must be high, medium, low, or numeric, got {value!r}")


def validate_attribute_field(name: str, payload: Any) -> dict[str, str]:
    if isinstance(payload, str):
        payload = {
            "value": payload,
            "confidence": "medium",
            "observation_type": "observed",
            "evidence": f"model returned bare string for {name}",
        }

    if not isinstance(payload, dict):
        raise GarmentAttributeError(
            f"attributes.{name} must be an object, got {type(payload).__name__}"
        )

    value = payload.get("value")
    confidence = _normalize_confidence(payload.get("confidence"))
    observation_type = payload.get("observation_type")
    evidence = payload.get("evidence")

    if not isinstance(value, str) or not value.strip():
        raise GarmentAttributeError(f"attributes.{name}.value must be a non-empty string")
    if observation_type not in ("observed", "inferred"):
        raise GarmentAttributeError(
            f"attributes.{name}.observation_type must be observed or inferred, "
            f"got {observation_type!r}"
        )
    if not isinstance(evidence, str) or not evidence.strip():
        raise GarmentAttributeError(f"attributes.{name}.evidence must be a non-empty string")

    return {
        "value": value.strip(),
        "confidence": confidence,
        "observation_type": observation_type,
        "evidence": evidence.strip(),
    }


def _normalize_attributes_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "attributes" in payload and isinstance(payload["attributes"], dict):
        return payload

    if any(key in payload for key in ATTRIBUTE_FIELDS):
        return {"attributes": {key: payload[key] for key in ATTRIBUTE_FIELDS if key in payload}}

    raise GarmentAttributeError("payload must contain an attributes object or attribute fields")


def validate_garment_attributes(payload: Any) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise GarmentAttributeError(
            f"garment attributes payload must be a JSON object, got {type(payload).__name__}"
        )

    normalized = _normalize_attributes_payload(payload)
    attributes = normalized["attributes"]
    if not isinstance(attributes, dict):
        raise GarmentAttributeError("attributes must be an object")

    extra = set(attributes) - set(ATTRIBUTE_FIELDS)
    if extra:
        raise GarmentAttributeError(f"unexpected attribute keys: {sorted(extra)}")

    missing = set(ATTRIBUTE_FIELDS) - set(attributes)
    if missing:
        raise GarmentAttributeError(f"missing attribute keys: {sorted(missing)}")

    return {name: validate_attribute_field(name, attributes[name]) for name in ATTRIBUTE_FIELDS}


def parse_garment_attributes_response(text: str) -> dict[str, dict[str, str]]:
    cleaned = strip_markdown_fences(text)
    if not cleaned:
        raise GarmentAttributeError("model response was empty")

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GarmentAttributeError(f"model response is not valid JSON: {exc}") from exc

    return validate_garment_attributes(payload)


def high_confidence_attributes(
    attributes: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    return {name: field for name, field in attributes.items() if field["confidence"] == "high"}


def build_extraction_record(
    *,
    fixture_id: str,
    role: str,
    image_path: Path,
    attributes: dict[str, dict[str, str]],
    model_id: str,
    source_photo_path: Path | None = None,
) -> dict[str, Any]:
    inputs: list[dict[str, Any]] = [
        {
            "role": "segmented_cutout",
            "path": str(image_path),
            "sha256": sha256_file(image_path),
        }
    ]
    if source_photo_path is not None and source_photo_path.is_file():
        inputs.append(
            {
                "role": "source_photo",
                "path": str(source_photo_path),
                "sha256": sha256_file(source_photo_path),
            }
        )

    return {
        "schema_version": ATTRIBUTE_SCHEMA_VERSION,
        "extracted_at_utc": datetime.now(tz=UTC).isoformat(),
        "model_id": model_id,
        "case": {"fixture": fixture_id, "role": role},
        "inputs": inputs,
        "attributes": attributes,
    }


def extract_garment_attributes(
    image_path: str | Path,
    *,
    model_id: str = DEFAULT_MODEL,
    fixture_id: str = "unknown",
    role: str = "top",
    source_photo_path: str | Path | None = None,
) -> dict[str, Any]:
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    resolved = Path(image_path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"image not found: {resolved}")

    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id,
        dtype=torch.bfloat16,
        device_map="auto",
    )
    model.eval()

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(resolved)},
                {"type": "text", "text": ATTRIBUTE_EXTRACTION_PROMPT},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        enable_thinking=False,
    )
    inputs = {
        key: value.to(model.device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        generated = model.generate(**inputs, max_new_tokens=1024, do_sample=False)

    prompt_length = inputs["input_ids"].shape[-1]
    decoded = processor.decode(generated[0][prompt_length:], skip_special_tokens=True)
    attributes = parse_garment_attributes_response(extract_response_text(decoded))

    source = Path(source_photo_path).expanduser().resolve() if source_photo_path else None
    return build_extraction_record(
        fixture_id=fixture_id,
        role=role,
        image_path=resolved,
        attributes=attributes,
        model_id=model_id,
        source_photo_path=source,
    )


def serialize_extraction_record(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_extraction_record(payload: dict[str, Any], *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_extraction_record(payload), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured garment attributes from a segmented cutout with Qwen3.5."
    )
    parser.add_argument("image", help="Path to segmented catalog cutout PNG.")
    parser.add_argument("--output", "-o", required=True, help="Path to write JSON output.")
    parser.add_argument("--fixture", default="unknown", help="Fixture id for provenance.")
    parser.add_argument("--role", default="top", help="Garment role for provenance.")
    parser.add_argument(
        "--source-photo",
        help="Optional original mirror-selfie for provenance (not sent to model).",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model id.")
    args = parser.parse_args()

    try:
        result = extract_garment_attributes(
            args.image,
            model_id=args.model,
            fixture_id=args.fixture,
            role=args.role,
            source_photo_path=args.source_photo,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    output_path = Path(args.output)
    write_extraction_record(result, output_path=output_path)
    print(f"ok: wrote {output_path}")
    high = high_confidence_attributes(result["attributes"])
    print(f"  high-confidence fields: {', '.join(sorted(high))}")


if __name__ == "__main__":
    main()
