"""Gemini Nano Banana 2 catalog-generation provider (Step 1: config + auth check)."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google import genai

# Official stable model ID for Nano Banana 2 (Gemini 3.1 Flash Image).
# https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image
NANO_BANANA_2_MODEL_ID = "gemini-3.1-flash-image"
RUNNER_MODEL_ID = "nano_banana_2"

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_CREDENTIALS_FILE_ENV = "GEMINI_CREDENTIALS_FILE"

DEFAULT_CREDENTIALS_FALLBACKS: tuple[Path, ...] = (
    Path("/users/pg00807/llamafactory/credentials"),
    Path("/users/pg00807/LlamaFactory/eval/MoveVQA/v6/credentials.env"),
)


class GeminiCredentialsError(RuntimeError):
    """Raised when GEMINI_API_KEY cannot be resolved."""


@dataclass(frozen=True)
class GeminiCatalogConfig:
    """Non-secret configuration for the catalog-generation provider."""

    model_id: str = NANO_BANANA_2_MODEL_ID
    credentials_file: Path | None = None

    def __repr__(self) -> str:
        creds = self.credentials_file
        creds_label = str(creds) if creds is not None else "<default-fallbacks>"
        return f"GeminiCatalogConfig(model_id={self.model_id!r}, credentials_file={creds_label!r})"


@dataclass(frozen=True)
class AvailabilityCheckResult:
    ok: bool
    model_id: str
    display_name: str | None = None
    error: str | None = None


def redact_secret(value: str | None) -> str:
    """Return a safe label for logs, reprs, and test assertions."""
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _parse_dotenv_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip().strip("\"'")
        if name == key and value:
            return value
    return None


def credential_fallback_paths(credentials_file: Path | None = None) -> tuple[Path, ...]:
    paths: list[Path] = []
    env_path = os.environ.get(GEMINI_CREDENTIALS_FILE_ENV)
    if env_path:
        paths.append(Path(env_path))
    if credentials_file is not None:
        paths.append(credentials_file)
    for fallback in DEFAULT_CREDENTIALS_FALLBACKS:
        if fallback not in paths:
            paths.append(fallback)
    return tuple(paths)


def resolve_gemini_api_key(*, credentials_file: Path | None = None) -> str:
    """Resolve GEMINI_API_KEY from environment first, then dotenv fallbacks."""
    env_key = os.environ.get(GEMINI_API_KEY_ENV)
    if env_key:
        return env_key

    for path in credential_fallback_paths(credentials_file):
        loaded = _parse_dotenv_value(path, GEMINI_API_KEY_ENV)
        if loaded:
            return loaded

    searched = ", ".join(str(path) for path in credential_fallback_paths(credentials_file))
    raise GeminiCredentialsError(
        f"{GEMINI_API_KEY_ENV} is not set in the environment and was not found in: {searched}"
    )


def build_gemini_client(*, config: GeminiCatalogConfig | None = None) -> genai.Client:
    """Construct a google-genai client using resolved credentials."""
    resolved = config or GeminiCatalogConfig()
    api_key = resolve_gemini_api_key(credentials_file=resolved.credentials_file)
    from google import genai

    return genai.Client(api_key=api_key)


def check_model_availability(
    *,
    config: GeminiCatalogConfig | None = None,
    client: Any | None = None,
) -> AvailabilityCheckResult:
    """Non-generating metadata check that the configured model is reachable."""
    resolved = config or GeminiCatalogConfig()
    try:
        gemini_client = client or build_gemini_client(config=resolved)
        model_info = gemini_client.models.get(model=resolved.model_id)
        display_name = getattr(model_info, "display_name", None)
        return AvailabilityCheckResult(
            ok=True,
            model_id=resolved.model_id,
            display_name=display_name,
        )
    except GeminiCredentialsError as exc:
        return AvailabilityCheckResult(
            ok=False,
            model_id=resolved.model_id,
            error=str(exc),
        )
    except Exception as exc:
        return AvailabilityCheckResult(
            ok=False,
            model_id=resolved.model_id,
            error=f"{type(exc).__name__}: {exc}",
        )


def main_check() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Gemini credentials and Nano Banana 2 model availability "
            "without generating images."
        )
    )
    parser.add_argument(
        "--model",
        default=NANO_BANANA_2_MODEL_ID,
        help=f"Gemini model id (default: {NANO_BANANA_2_MODEL_ID}).",
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="Optional dotenv credentials file when GEMINI_API_KEY is unset.",
    )
    args = parser.parse_args()

    config = GeminiCatalogConfig(model_id=args.model, credentials_file=args.credentials_file)
    result = check_model_availability(config=config)
    if result.ok:
        print(f"ok: model {result.model_id} is available")
        if result.display_name:
            print(f"display_name: {result.display_name}")
        raise SystemExit(0)

    print(f"error: model {result.model_id} is unavailable ({result.error})", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main_check()
