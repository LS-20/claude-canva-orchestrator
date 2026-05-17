"""Phase 1: vision analysis → DesignSpec."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import anthropic
from anthropic import APIError, APIStatusError

from canva_agent.config import get_api_key, resolve_model
from canva_agent.schemas import DesignSpec

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _load_system_prompt() -> str:
    return (PROMPTS_DIR / "phase1_system.md").read_text(encoding="utf-8")


def _encode_image(path: Path) -> tuple[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported image format '{suffix}'. Use: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return data, MEDIA_TYPES[suffix]


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_spec(raw: str) -> DesignSpec:
    cleaned = _strip_json_fences(raw)
    data = json.loads(cleaned)
    return DesignSpec.model_validate(data)


def _call_vision(
    client: anthropic.Anthropic,
    model_id: str,
    system: str,
    image_b64: str,
    media_type: str,
    user_text: str,
) -> str:
    response = client.messages.create(
        model=model_id,
        max_tokens=8192,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    parts = [block.text for block in response.content if block.type == "text"]
    return "".join(parts)


def analyze_image(
    image_path: str | Path,
    notes: str = "",
    model: str = "sonnet",
    memory_context: str = "",
) -> DesignSpec:
    """Analyze a reference image and return a validated DesignSpec."""
    path = Path(image_path).expanduser().resolve()
    model_id = resolve_model(model)
    system = _load_system_prompt()

    user_parts = ["Analyze this reference image and output the design spec JSON."]
    if notes.strip():
        user_parts.append(f"User intent notes: {notes.strip()}")
    if memory_context.strip():
        user_parts.append(f"Prior saved specs for context:\n{memory_context.strip()}")
    user_text = "\n\n".join(user_parts)

    image_b64, media_type = _encode_image(path)
    client = anthropic.Anthropic(api_key=get_api_key())

    try:
        raw = _call_vision(client, model_id, system, image_b64, media_type, user_text)
        try:
            return _parse_spec(raw)
        except (json.JSONDecodeError, ValueError) as first_err:
            fix_prompt = (
                "Your previous response was not valid JSON for the required schema. "
                f"Parse error: {first_err}. "
                "Reply with ONLY corrected valid JSON, no markdown fences."
            )
            raw_retry = _call_vision(
                client,
                model_id,
                system,
                image_b64,
                media_type,
                fix_prompt + f"\n\nPrevious response:\n{raw[:4000]}",
            )
            try:
                return _parse_spec(raw_retry)
            except (json.JSONDecodeError, ValueError) as retry_err:
                raise ValueError(
                    f"Could not parse design spec after retry.\n"
                    f"Last error: {retry_err}\n\nRaw response:\n{raw_retry}"
                ) from retry_err
    except APIStatusError as e:
        if e.status_code == 401:
            raise RuntimeError("Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env") from e
        if e.status_code == 429:
            raise RuntimeError("Anthropic rate limit hit. Wait a moment and try again.") from e
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}") from e
    except APIError as e:
        raise RuntimeError(f"Anthropic API error: {e}") from e


def spec_to_json(spec: DesignSpec) -> str:
    return spec.model_dump_json(indent=2)


def spec_from_json(text: str) -> DesignSpec:
    return _parse_spec(text)


def revise_spec(spec: DesignSpec, feedback: str, model: str = "sonnet") -> DesignSpec:
    """Revise an existing spec based on natural-language feedback."""
    model_id = resolve_model(model)
    system = _load_system_prompt()
    client = anthropic.Anthropic(api_key=get_api_key())
    prompt = (
        f"Revise this design spec based on user feedback.\n"
        f"Feedback: {feedback}\n\n"
        f"Current spec:\n{spec_to_json(spec)}\n\n"
        "Output ONLY the revised valid JSON spec."
    )
    response = client.messages.create(
        model=model_id,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in response.content if b.type == "text")
    return _parse_spec(raw)
