"""Qwen3.5 garment bounding-box localization and response validation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

LAYOUT_SEPARATES = "separates"
LAYOUT_DRESS = "dress"
LAYOUTS = {LAYOUT_SEPARATES, LAYOUT_DRESS}

ROLE_SETS: dict[str, frozenset[str]] = {
    LAYOUT_SEPARATES: frozenset({"top", "bottom"}),
    LAYOUT_DRESS: frozenset({"dress"}),
}

DEFAULT_MODEL = "Qwen/Qwen3.5-9B"

LOCALIZATION_PROMPT = """You are a garment localizer for mirror selfies.

Localize garments worn by the person reflected in the mirror only. Ignore hanging \
clothes, background garments, and anything not on the reflected person.

Taxonomy:
- layout "separates": required roles top and bottom
- layout "dress": required role dress

Policies:
- For layered separates, "top" is the dominant outermost upper garment visible on \
the person (e.g. blazer over shirt counts as top=blazer).
- "bottom" is trousers, skirt, or similar lower garment.

Return ONLY valid JSON with no markdown fences. Format:
{"layout":"separates","top":[x_min,y_min,x_max,y_max],"bottom":[...]}
or {"layout":"dress","dress":[x_min,y_min,x_max,y_max]}
Coordinates are normalized floats in [0,1] with x_min < x_max and y_min < y_max."""


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped


def _looks_like_thousand_scale(box: list[float]) -> bool:
    return any(value > 1.0 for value in box)


def normalize_box(raw_box: Any) -> list[float]:
    if not isinstance(raw_box, list) or len(raw_box) != 4:
        raise ValueError(f"bbox must be a list of four numbers, got {raw_box!r}")

    try:
        box = [float(value) for value in raw_box]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bbox values must be numeric, got {raw_box!r}") from exc

    if _looks_like_thousand_scale(box):
        box = [value / 1000.0 for value in box]

    for index, value in enumerate(box):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"bbox[{index}]={value} is outside [0, 1]")

    x_min, y_min, x_max, y_max = box
    if x_min >= x_max:
        raise ValueError(f"bbox x_min ({x_min}) must be less than x_max ({x_max})")
    if y_min >= y_max:
        raise ValueError(f"bbox y_min ({y_min}) must be less than y_max ({y_max})")

    return box


def validate_localization(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(
            f"localization payload must be a JSON object, got {type(payload).__name__}"
        )

    if "confidence" in payload:
        raise ValueError("confidence is not part of the localization contract")

    layout = payload.get("layout")
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {sorted(LAYOUTS)}, got {layout!r}")

    allowed_roles = ROLE_SETS[layout]
    extra_keys = set(payload) - {"layout"} - allowed_roles
    if extra_keys:
        raise ValueError(f"unexpected keys for layout {layout!r}: {sorted(extra_keys)}")

    present_roles = {role for role in allowed_roles if role in payload}
    missing_required = allowed_roles - present_roles
    if missing_required:
        raise ValueError(
            f"missing required roles for layout {layout!r}: {sorted(missing_required)}"
        )

    result: dict[str, Any] = {"layout": layout}
    for role in sorted(present_roles):
        result[role] = normalize_box(payload[role])

    return result


def parse_localization_response(text: str) -> dict[str, Any]:
    cleaned = strip_markdown_fences(text)
    if not cleaned:
        raise ValueError("model response was empty")

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response is not valid JSON: {exc}") from exc

    return validate_localization(payload)


def extract_response_text(raw_text: str) -> str:
    think_end = "<" + "/think>"
    if think_end in raw_text:
        return raw_text.split(think_end, maxsplit=1)[-1].strip()
    return raw_text.strip()


def localize_garments(image_path: str | Path, *, model_id: str = DEFAULT_MODEL) -> dict[str, Any]:
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
                {"type": "text", "text": LOCALIZATION_PROMPT},
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
        generated = model.generate(**inputs, max_new_tokens=512, do_sample=False)

    prompt_length = inputs["input_ids"].shape[-1]
    decoded = processor.decode(generated[0][prompt_length:], skip_special_tokens=True)
    return parse_localization_response(extract_response_text(decoded))


def main() -> None:
    parser = argparse.ArgumentParser(description="Localize garments with Qwen3.5 bounding boxes.")
    parser.add_argument("image", help="Path to a mirror-selfie image.")
    parser.add_argument("--output", "-o", help="Optional path to write JSON output.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model id.")
    args = parser.parse_args()

    try:
        result = localize_garments(args.image, model_id=args.model)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
