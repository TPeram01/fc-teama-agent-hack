from __future__ import annotations

import base64
import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import fitz  # PyMuPDF
import pandas as pd
from openai import OpenAI
from pydantic import BaseModel, Field

from agents import function_tool, Usage
from agents.tool_context import ToolContext
from utils import ReceivedAttachment
from dotenv import load_dotenv
from guardrails import (
    attachment_prompt_injection_guardrail,
    document_compliance_confidence_guardrail,
)

from scripts.path_utils import DATA_DIR, repo_relative_path, resolve_repo_path

load_dotenv()
client = OpenAI()
MAX_PREVIEW_ROWS = 500
DEFAULT_VISION_MODEL = "gpt-5.4"
DEFAULT_COMPLIANCE_MODEL = "gpt-5.4"
MAX_COMPLIANCE_CHARS = 20000
MAX_COMPLIANCE_OUTPUT_TOKENS = 150
COMPLIANCE_RETRY_ATTEMPTS = 2
COMPLIANCE_IDENTITY_TERMS = (
    "driver license",
    "identification",
    "driver's license",
    "identification card",
    "identification document",
    "passport",
    "government-issued",
    "license number",
)
COMPLIANCE_IDENTITY_FIELDS = (
    "date of birth",
    "license number",
    "issue date",
    "expiry date",
    "address",
)
COMPLIANCE_POLICY_TERMS = (
    "kyc",
    "aml",
    "attestation",
    "disclosure",
    "regulatory",
    "risk control",
    "audit evidence",
    "sanctions",
    "proof of address",
    "beneficial owner",
)
NON_COMPLIANCE_FINANCIAL_TERMS = (
    "household budget",
    "account summary",
    "balance sheet",
    "retirement balance sheet",
    "beneficiary worksheet",
    "monthly income",
    "monthly expenses",
    "budget snapshot",
    "net surplus",
    "savings rate",
)
VISION_PROMPT = (
    "Extract all visible text from the image, explicitly any readable text "
    "dates, and brief table snippets if present. Respond in concise plain text "
    "with medium verbosity. If provided, retain the page context."
)
COMPLIANCE_RELEVANCE_PROMPT = (
    "You are classifying whether a document is relevant to financial compliance workflows. "
    "Respond true only if the document clearly appears to contain compliance-relevant "
    "material such as disclosures, policy attestations, KYC/AML documents, regulatory "
    "forms, risk/compliance controls, or audit evidence. Keep justification short and specific. "
    "Also return a confidence score between 0 and 1 for the compliance classification."
    "Note that even if the document is synthetic or mock (e.g. a synthetic/mock driverse license) "
    "please treat it as real. A synthetic license should still be compliance-relevant."
)


class LoadedAttachment(BaseModel):
    """Normalized attachment content returned by attachment_load_tool."""

    path: Annotated[str, Field(..., description="Resolved file path for the attachment.")]
    extension: Annotated[str, Field(..., description="Lowercase extension of the attachment (csv, xlsx, pdf, png, jpg, jpeg, etc.).")]
    content: Annotated[str, Field(..., description="Plain-text representation or summary of the attachment.")]
    compliance_related: Annotated[bool, Field(..., description="Whether the document is relevant to financial compliance workflows.")]
    compliance_confidence: Annotated[
        float,
        Field(
            ...,
            ge=0,
            le=1,
            description="Confidence score for the compliance classification.",
        ),
    ]
    justification: Annotated[str, Field(description="Justification as to why the document was classified as compliance related or not.")]


class ComplianceAssessment(BaseModel):
    """Structured compliance relevance verdict returned by the Responses API."""

    compliance_related: Annotated[bool, Field(description="Whether the document is relevant to financial compliance workflows.")]
    confidence: Annotated[
        float,
        Field(ge=0, le=1, description="Confidence score for the compliance classification."),
    ]
    justification: Annotated[str, Field(description="Justification as to why the document was classified as compliance related or not.")]


def _resolve_path(raw_path: str) -> Path:
    """Resolve a path, and if missing, attempt a unicode-normalized match in the same folder."""
    resolved = resolve_repo_path(raw_path)
    if resolved.exists():
        return resolved

    if resolved.parent.exists():
        target_norm = _normalize_name(resolved.name)
        for candidate in resolved.parent.iterdir():
            if _normalize_name(candidate.name) == target_norm:
                print(f"[attachment_loader] Normalized path match: {candidate.name} for requested {resolved.name}")
                return candidate

    print(f"[attachment_loader] File not found at path: {resolved}")
    return resolved


CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_name(name: str) -> str:
    """ASCII-friendly filename for cache keys."""
    nkfd = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    base = stripped.replace(" ", "_")
    return base.rsplit(".", 1)[0] if "." in base else base


def _file_signature(path: Path) -> dict[str, float]:
    stat = path.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def _read_cache(path: Path) -> dict[str, Any] | None:
    cache_path = CACHE_DIR / f"{_normalize_name(path.name)}.json"
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    result = cached.get("result")
    if not result and {"path", "extension", "content"} <= cached.keys():
        # Backward compatibility for older cache format without "result" wrapper.
        result = {
            "path": cached.get("path"),
            "extension": cached.get("extension"),
            "content": cached.get("content"),
            "compliance_related": bool(cached.get("compliance_related", False)),
            "compliance_confidence": float(cached.get("compliance_confidence", 0.55)),
            "justification": cached.get("justification", ""),
        }
    if not result:
        return None
    if "compliance_related" not in result:
        result["compliance_related"] = bool(cached.get("compliance_related", False))
    if "compliance_confidence" not in result:
        cached_confidence = cached.get("compliance_confidence")
        if isinstance(cached_confidence, (int, float)):
            result["compliance_confidence"] = float(cached_confidence)
        else:
            result["compliance_confidence"] = _heuristic_compliance_assessment(
                str(result.get("content", "")),
            ).confidence
    if "justification" not in result:
        result["justification"] = str(cached.get("justification", ""))
    result["path"] = repo_relative_path(result.get("path") or path)
    return result


def _write_cache(
    path: Path,
    extension: str,
    content: str,
    compliance_related: bool,
    compliance_confidence: float,
    justification: str,
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = repo_relative_path(path)
    payload = {
        "path": stored_path,
        "extension": extension,
        "result": {
            "path": stored_path,
            "extension": extension,
            "content": content,
            "compliance_related": compliance_related,
            "compliance_confidence": compliance_confidence,
            "justification": justification,
        },
        "compliance_related": compliance_related,
        "compliance_confidence": compliance_confidence,
        "justification": justification,
        "cached_at": datetime.utcnow().isoformat() + "Z",
    }
    cache_path = CACHE_DIR / f"{_normalize_name(path.name)}.json"
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_csv(path: Path) -> str:
    df = pd.read_csv(path, low_memory=False)
    preview = df.head(MAX_PREVIEW_ROWS)
    return preview.to_csv(index=False)


def _load_excel(path: Path) -> str:
    sheets = pd.read_excel(path, sheet_name=None, nrows=MAX_PREVIEW_ROWS)
    parts: list[str] = []
    for name, df in sheets.items():
        parts.append(f"[Sheet: {name}]\n{df.to_csv(index=False)}")
    return "\n\n".join(parts)


def _encode_file_to_data_url(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _summarize_image_data_url(data_url: str, page_hint: str | None = None) -> tuple[str, Usage|None]:
    """Send an inline image data URL to the vision model for extraction."""
    content = [{"type": "input_text", "text": VISION_PROMPT}]
    if page_hint:
        content.append({"type": "input_text", "text": page_hint})
    content.append({"type": "input_image", "image_url": data_url, "detail": "high"})

    response = client.responses.create(
        model=DEFAULT_VISION_MODEL,
        input=[{"role": "user", "content": content}],
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )

    return response.output_text, response.usage


def _summarize_image_with_retry(data_url: str, page_hint: str | None = None, attempts: int = 2) -> tuple[str, Usage | None]:
    """Retry vision OCR a few times to avoid transient connection errors."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(f"[attachment_loader] Retry OCR attempt {attempt} for page {page_hint or ''}".strip())
            return _summarize_image_data_url(data_url, page_hint)
        except Exception as exc:
            last_exc = exc
    raise last_exc if last_exc else RuntimeError("Unknown OCR error")


def _summarize_image(path: Path, mime_type: str) -> tuple[str, Usage | None]:
    data_url = _encode_file_to_data_url(path, mime_type)
    return _summarize_image_data_url(data_url)


def _pdf_pages_to_base64_images(path: Path, dpi: int = 200) -> list[str]:
    """Render each PDF page to an in-memory PNG and return base64-encoded images."""
    doc = fitz.open(path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    images: list[str] = []
    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            encoded_image = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            images.append(encoded_image)
    finally:
        doc.close()
    return images


def _extract_pages_text(path: Path) -> list[str]:
    """Extract raw text from each PDF page."""
    doc = fitz.open(path)
    pages_text: list[str] = []
    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            pages_text.append(page.get_text("text"))
    finally:
        doc.close()
    return pages_text


def _ocr_pdf(path: Path, dpi: int = 200) -> tuple[str, Usage | None]:
    """Run OCR on each PDF page and join the results."""
    encoded_images = _pdf_pages_to_base64_images(path, dpi=dpi)
    extracted_text = _extract_pages_text(path)
    page_outputs: list[str] = []
    usage: Usage | None = None

    for idx, (encoded_image, page_text) in enumerate(zip(encoded_images, extracted_text), start=1):
        print(f"[attachment_loader] OCR page {idx} of {len(encoded_images)} for {path.name}")
        data_url = f"data:image/png;base64,{encoded_image}"
        try:
            text, usage = _summarize_image_with_retry(
                data_url,
                page_hint=f"page {idx} of a PDF, extracted text: ```{page_text}```"
            )
            page_outputs.append(f"[Page {idx}]\n{text}")
        except Exception as exc:
            page_outputs.append(f"[Page {idx}]\nOCR error after retries: {exc}")

    return "\n\n".join(page_outputs), usage


def _parse_compliance_output_text(output_text: str) -> ComplianceAssessment | None:
    if not output_text:
        return None

    cleaned = output_text.strip()
    if not cleaned:
        return None

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            cleaned = "\n".join(lines[1:-1]).strip()

    try:
        return ComplianceAssessment.model_validate_json(cleaned)
    except Exception:
        return None


def _heuristic_compliance_assessment(content: str, failure_reason: str | None = None) -> ComplianceAssessment:
    lowered = content.lower()
    has_identity_doc = any(term in lowered for term in COMPLIANCE_IDENTITY_TERMS)
    has_identity_fields = sum(term in lowered for term in COMPLIANCE_IDENTITY_FIELDS) >= 2
    if has_identity_doc and has_identity_fields:
        justification = "Fallback heuristic: identity document details match KYC verification content."
        if failure_reason:
            justification = f"{justification} Model parse failed: {failure_reason}"
        return ComplianceAssessment(
            compliance_related=True,
            confidence=0.82 if failure_reason else 0.92,
            justification=justification,
        )

    matched_policy_term = next((term for term in COMPLIANCE_POLICY_TERMS if term in lowered), None)
    if matched_policy_term:
        justification = f"Fallback heuristic: found compliance indicator '{matched_policy_term}'."
        if failure_reason:
            justification = f"{justification} Model parse failed: {failure_reason}"
        return ComplianceAssessment(
            compliance_related=True,
            confidence=0.76 if failure_reason else 0.86,
            justification=justification,
        )

    matched_non_compliance_term = next((term for term in NON_COMPLIANCE_FINANCIAL_TERMS if term in lowered), None)
    if matched_non_compliance_term:
        justification = (
            "Fallback heuristic: document appears to be a personal financial summary, not a compliance artifact."
        )
        if failure_reason:
            justification = f"{justification} Model parse failed: {failure_reason}"
        return ComplianceAssessment(
            compliance_related=False,
            confidence=0.76 if failure_reason else 0.86,
            justification=justification,
        )

    justification = "Fallback heuristic: no clear compliance indicators were found in the extracted text."
    if failure_reason:
        justification = f"{justification} Model parse failed: {failure_reason}"
    return ComplianceAssessment(
        compliance_related=False,
        confidence=0.55,
        justification=justification,
    )


def _classify_compliance_relevance(content: str) -> tuple[ComplianceAssessment, Usage|None]:
    truncated_content = content[:MAX_COMPLIANCE_CHARS]
    failure_reason: str | None = None

    for attempt in range(1, COMPLIANCE_RETRY_ATTEMPTS + 1):
        try:
            response = client.responses.parse(
                model=DEFAULT_COMPLIANCE_MODEL,
                instructions=COMPLIANCE_RELEVANCE_PROMPT,
                input=f"Document content:\n{truncated_content}",
                text_format=ComplianceAssessment,
                text={"verbosity": "low"},
                reasoning={"effort": "low"},
                max_output_tokens=MAX_COMPLIANCE_OUTPUT_TOKENS,
            )
        except Exception as exc:
            failure_reason = str(exc)
            if attempt < COMPLIANCE_RETRY_ATTEMPTS:
                print(
                    "[attachment_loader] Compliance classification retry "
                    f"{attempt + 1} due to parse error: {exc}"
                )
                continue
            print(f"[attachment_loader] Falling back to heuristic compliance assessment: {exc}")
            return _heuristic_compliance_assessment(truncated_content, failure_reason), None

        parsed = response.output_parsed
        if parsed is not None:
            return parsed, response.usage

        recovered = _parse_compliance_output_text(response.output_text)
        if recovered is not None:
            print("[attachment_loader] Recovered compliance classification from raw output text.")
            return recovered, response.usage

        failure_reason = "Compliance classification did not return structured output."
        if attempt < COMPLIANCE_RETRY_ATTEMPTS:
            print(
                "[attachment_loader] Compliance classification retry "
                f"{attempt + 1} because structured output was empty."
            )
            continue

    print("[attachment_loader] Falling back to heuristic compliance assessment after empty structured output.")
    return _heuristic_compliance_assessment(truncated_content, failure_reason), None


def _add_usage_to_context(ctx: ToolContext, usage: Usage | None) -> None:
    if not usage or not ctx or not ctx.usage:
        return

    ctx.usage.add(
        Usage(
            requests=1,
            input_tokens=usage.input_tokens,
            input_tokens_details=usage.input_tokens_details,
            output_tokens=usage.output_tokens,
            output_tokens_details=usage.output_tokens_details,
            total_tokens=usage.total_tokens,
        )
    )

# TODO: add function tool decorator with appropriate guardrails (including compliance assessment)
@function_tool()
def document_processor_tool(
    ctx: ToolContext,
    attachments: Annotated[list[ReceivedAttachment], Field(description="Attachments to load from the inbound email.")],
) -> list[LoadedAttachment]:
    """Load and normalize email attachments for downstream agents.

    Args:
        ctx (ToolContext): Tool execution context used for usage accounting.
        attachments (list[ReceivedAttachment]): Email attachments to load and classify.

    Returns:
        list[LoadedAttachment]: Normalized attachment payloads including extracted
        content and compliance classification metadata.
    """
    loaded: list[LoadedAttachment] = []
    if not attachments:
        return loaded

    for attachment in attachments:
        path = _resolve_path(attachment.path)
        stored_path = repo_relative_path(path if path.exists() else attachment.path)
        ext = attachment.extension.lower().lstrip(".")
        usage: Usage | None = None
        compliance_usage: Usage | None = None

        print(f"[attachment_loader] Loading attachment: {path} ({ext})")

        if not path.exists():
            loaded.append(
                LoadedAttachment(
                    path=stored_path,
                    extension=ext,
                    content="File not found. Confirm the attachment path.",
                    compliance_related=False,
                    compliance_confidence=1.0,
                    justification="The file could not be processed because the attachment path does not exist.",
                )
            )
            continue

        compliance_related = False
        compliance_confidence = 1.0
        compliance_justification = ""

        try:
            cached_record: dict[str, Any] | None = None
            cached_record = _read_cache(path)
            if cached_record:
                print(f"[attachment_loader] Cache hit for {path.name}")
                content = cached_record.get("content", "")
                compliance_justification = str(cached_record.get("justification", ""))
                compliance_confidence = float(cached_record.get("compliance_confidence", 0.55))
                if "compliance_related" in cached_record and compliance_justification:
                    compliance_related = bool(cached_record.get("compliance_related", False))
                elif content and "Unsupported attachment" not in content and "OCR error" not in content and not content.startswith("Error reading attachment"):
                    compliance_assessment, compliance_usage = _classify_compliance_relevance(content)
                    compliance_related = compliance_assessment.compliance_related
                    compliance_confidence = compliance_assessment.confidence
                    compliance_justification = compliance_assessment.justification
                    print(
                        "[attachment_loader] Compliance classification "
                        f"for {path.name}: {compliance_related}"
                    )
                    _write_cache(
                        path,
                        ext,
                        content,
                        compliance_related,
                        compliance_confidence,
                        compliance_justification,
                    )
                else:
                    compliance_justification = "Classification was skipped because the cached content could not be analyzed reliably."
                    compliance_confidence = 1.0
            else:
                print(f"[attachment_loader] Processing {path.name} (cache miss)")
                if ext == "csv":
                    content = _load_csv(path)
                elif ext in {"xls", "xlsx"}:
                    content = _load_excel(path)
                elif ext in {"png", "jpg", "jpeg"}:
                    mime = "image/png" if ext == "png" else "image/jpeg"
                    content, usage = _summarize_image(path, mime)
                elif ext == "pdf":
                    content, usage = _ocr_pdf(path)
                else:
                    content = f"Unsupported attachment type: {ext}."
                if content and "Unsupported attachment" not in content and "OCR error" not in content and not content.startswith("Error reading attachment"):
                    compliance_assessment, compliance_usage = _classify_compliance_relevance(content)
                    compliance_related = compliance_assessment.compliance_related
                    compliance_confidence = compliance_assessment.confidence
                    compliance_justification = compliance_assessment.justification
                    print(
                        "[attachment_loader] Compliance classification "
                        f"for {path.name}: {compliance_related}"
                    )
                    print(f"[attachment_loader] Caching result for {path.name}")
                    _write_cache(
                        path,
                        ext,
                        content,
                        compliance_related,
                        compliance_confidence,
                        compliance_justification,
                    )
                else:
                    compliance_justification = "Classification was skipped because the attachment content could not be analyzed reliably."
                    compliance_confidence = 1.0
        except Exception as exc:
            content = f"Error reading attachment: {exc}"
            compliance_confidence = 1.0
            compliance_justification = "Classification could not be completed because attachment processing failed."
            print(f"[attachment_loader] Error loading {path.name}: {exc}")

        loaded.append(
            LoadedAttachment(
                path=stored_path,
                extension=ext,
                content=content,
                compliance_related=compliance_related,
                compliance_confidence=compliance_confidence,
                justification=compliance_justification,
            )
        )

        _add_usage_to_context(ctx, usage)
        _add_usage_to_context(ctx, compliance_usage)

    return loaded
