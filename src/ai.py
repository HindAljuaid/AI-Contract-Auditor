from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterable

from .data_utils import contract_file_descriptor
from .models import ContractSpec, MappingBatch


class AIServiceError(RuntimeError):
    """Base class for user-facing OpenAI/API errors."""


class AIQuotaError(AIServiceError):
    pass


class AIAuthenticationError(AIServiceError):
    pass


class AIRateLimitError(AIServiceError):
    pass


class AIConnectionError(AIServiceError):
    pass


def _get_openai_client(api_key: str):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The openai package is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return OpenAI(api_key=api_key)


def _translate_api_exception(exc: Exception) -> AIServiceError:
    text = str(exc).lower()
    name = exc.__class__.__name__.lower()

    if "credit_balance_exhausted" in text or "insufficient_quota" in text or "no credits remaining" in text:
        return AIQuotaError(
            "OpenAI API credits are unavailable for this API organization. "
            "Add API credit and retry, or upload a previously saved contract-rules JSON file."
        )
    if "authentication" in name or "invalid_api_key" in text or "incorrect api key" in text:
        return AIAuthenticationError(
            "The OpenAI API key was rejected. Check that the key is valid and belongs to the intended API organization."
        )
    if "ratelimit" in name or "rate limit" in text or "429" in text:
        return AIRateLimitError(
            "The OpenAI API rate limit was reached. Retry later or upload previously saved contract rules."
        )
    if "connection" in name or "timeout" in name:
        return AIConnectionError(
            "The OpenAI API could not be reached. Check your network connection or upload previously saved contract rules."
        )
    return AIServiceError(f"OpenAI request failed: {exc}")


def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def _file_content_item(name: str, data: bytes) -> dict:
    suffix = Path(name).suffix.lower()
    if suffix in {".txt", ".md", ".json", ".html", ".xml", ".csv"}:
        text = data.decode("utf-8", errors="replace")
        return {
            "type": "input_text",
            "text": f"\n\n===== FILE: {name} =====\n{text}",
        }

    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".rtf": "application/rtf",
    }.get(suffix, "application/octet-stream")

    encoded = base64.b64encode(data).decode("ascii")
    return {
        "type": "input_file",
        "filename": name,
        "file_data": f"data:{mime};base64,{encoded}",
        **({"detail": "high"} if suffix == ".pdf" else {}),
    }


def extract_contract_spec(
    contract_files: Iterable,
    api_key: str,
    model: str = "gpt-5.6-terra",
) -> ContractSpec:
    """Extract a typed contract rule set using OpenAI Structured Outputs."""
    client = _get_openai_client(api_key)
    content = [
        {
            "type": "input_text",
            "text": (
                "Extract one consolidated reimbursement contract specification from "
                "the attached document(s). Amendments override the base agreement "
                "only from their stated effective date."
            ),
        }
    ]

    count = 0
    for file_obj in contract_files:
        name, data = contract_file_descriptor(file_obj)
        content.append(_file_content_item(name, data))
        count += 1

    if count == 0:
        raise ValueError("No contract files were supplied.")

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": _load_prompt("contract_extraction_v1.md")},
                {"role": "user", "content": content},
            ],
            text_format=ContractSpec,
        )
    except Exception as exc:
        raise _translate_api_exception(exc) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise AIServiceError("The model did not return a structured contract specification.")
    return parsed


def resolve_ambiguous_mappings(
    items: list[dict],
    api_key: str,
    model: str = "gpt-5.6-terra",
) -> MappingBatch:
    """
    Resolve only ambiguous descriptions. Each item must contain item_id,
    description, and candidates (service_name/score pairs).
    """
    if not items:
        return MappingBatch(mappings=[])

    client = _get_openai_client(api_key)
    prompt = _load_prompt("mapping_resolution_v1.md")

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Resolve these billing descriptions. Choose only from each item's "
                        "candidate list; use null when the evidence is insufficient.\n\n"
                        + json.dumps(items, ensure_ascii=False)
                    ),
                },
            ],
            text_format=MappingBatch,
        )
    except Exception as exc:
        raise _translate_api_exception(exc) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise AIServiceError("The model did not return structured mapping decisions.")
    return parsed


def explain_audit_evidence(
    evidence: dict,
    api_key: str,
    model: str = "gpt-5.6-terra",
) -> str:
    """Turn deterministic audit evidence into a concise natural-language explanation.

    The model is explicitly prohibited from changing amounts, categories, or mappings.
    """
    client = _get_openai_client(api_key)
    system = (
        "You explain insurance invoice audit findings to a reviewer. "
        "Use ONLY the supplied deterministic evidence. Do not recalculate, change, infer, "
        "or add monetary amounts, service mappings, contract terms, or error categories. "
        "If evidence is uncertain, state that clearly. Keep the explanation concise and auditable."
    )
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": "Explain this audit evidence:\n\n" + json.dumps(evidence, ensure_ascii=False),
                },
            ],
        )
    except Exception as exc:
        raise _translate_api_exception(exc) from exc

    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise AIServiceError("The model returned no explanation text.")
    return output_text
