import json
import re
from typing import Any, Annotated

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from agents import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    ToolOutputGuardrailData,
    tool_input_guardrail,
    tool_output_guardrail,
)
from agents.tracing import guardrail_span

load_dotenv()
client = OpenAI()
DOCUMENT_COMPLIANCE_CONFIDENCE_THRESHOLD = 0.7

ON_TOPIC_KEYWORDS = (
    "meeting",
    "schedule",
    "availability",
    "available",
    "works for me",
    "confirm",
    "accepted",
    "attached",
    "attachment",
    "document",
    "form 1500",
    "financial plan",
    "retirement",
    "account summary",
    "budget",
    "goals",
    "information requested",
    "requested documents",
    "driver's license",
    "drivers license",
    "household budget",
)

OFF_TOPIC_KEYWORDS = (
    "dungeons and dragons",
    "bard",
    "cleric",
    "rogue",
    "spelljammer",
    "campaign",
    "encounter balance",
    "game night",
    "snack assignments",
)

PROMPT_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore prior instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier)\b.{0,40}\b(instructions|prompt|message|rules)\b",
        re.IGNORECASE,
    ),
    "reveal system prompt": re.compile(
        r"\b(show|reveal|print|display|dump)\b.{0,40}\b(system|developer)\b.{0,20}\b(prompt|instructions|message)\b",
        re.IGNORECASE,
    ),
    "role override": re.compile(
        r"\byou are now\b.{0,40}\b(system|developer|assistant|agent|hacker|admin)\b",
        re.IGNORECASE,
    ),
    "tool execution request": re.compile(
        r"\b(run|execute|invoke)\b.{0,40}\b(shell|sql|command|code|script|tool)\b",
        re.IGNORECASE,
    ),
    "bypass safety": re.compile(
        r"\b(bypass|disable|ignore)\b.{0,40}\b(safety|guardrail|policy|moderation|restrictions)\b",
        re.IGNORECASE,
    ),
    "prompt extraction": re.compile(
        r"\bwhat (?:is|'s) your\b.{0,20}\b(system prompt|developer prompt|hidden prompt)\b",
        re.IGNORECASE,
    ),
}

SENSITIVE_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "date of birth": re.compile(
        r"\b(date of birth|dob)\b.{0,30}\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b",
        re.IGNORECASE,
    ),
    "social security number": re.compile(
        r"\b(?:ssn|social security)\b.{0,20}\b\d{3}-?\d{2}-?\d{4}\b",
        re.IGNORECASE,
    ),
    "driver's license": re.compile(
        r"\blicense number\b.{0,20}\b[A-Z0-9-]{5,}\b",
        re.IGNORECASE,
    ),
    "account number": re.compile(
        r"\b(account number|acct number|routing number)\b.{0,20}\b[A-Z0-9-]{5,}\b",
        re.IGNORECASE,
    ),
    "email address": re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
    ),
    "phone number": re.compile(
        r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\d{3}[-.\s]?\d{4})\b"
    ),
}

SENSITIVE_FINANCIAL_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "annual household income": re.compile(
        r"\bannual household income\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
    "monthly expenses": re.compile(
        r"\bmonthly expenses\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
    "liquid cash": re.compile(
        r"\bliquid cash\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
    "total debt": re.compile(
        r"\b(total debt|total debt balance)\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
    "retirement account balance": re.compile(
        r"\bretirement account balance\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
    "life insurance coverage": re.compile(
        r"\blife insurance coverage\b.{0,40}\b\d[\d,]*(?:\.\d{1,2})?\b",
        re.IGNORECASE,
    ),
}

ON_TOPIC_CLASSIFIER_PROMPT = (
    "You review parsed inbound client emails for a financial onboarding workflow. "
    "Allow emails that are on-topic for data or document submission, meeting scheduling or confirmation, "
    "financial planning follow-up, plan review, plan revision, or other normal intake workflow actions. "
    "Reject emails only when they are clearly unrelated to the workflow, such as hobby chat, personal banter, "
    "or unrelated requests. Incomplete but relevant onboarding emails are still on-topic."
)

class OnTopicVerdict(BaseModel):
    is_on_topic: Annotated[
        bool,
        Field(
            ...,
            description="True when the parsed inbound email is relevant to the financial onboarding workflow.",
        ),
    ]
    reason: Annotated[
        str,
        Field(..., description="Short explanation for the topic classification."),
    ]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _get_output_value(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _compose_inbound_email_text(email_output: Any) -> str:
    subject = _normalize_text(_get_output_value(email_output, "subject", None))
    body_text = _normalize_text(_get_output_value(email_output, "body_text", None))
    attachments = _get_output_value(email_output, "attachments", []) or []
    attachment_summaries: list[str] = []

    for attachment in attachments:
        summary = _normalize_text(_get_output_value(attachment, "summary"))
        filename = _normalize_text(_get_output_value(attachment, "filename"))
        if summary:
            attachment_summaries.append(summary)
            continue
        if filename:
            attachment_summaries.append(filename)

    return " ".join(
        part for part in [subject, body_text, " ".join(attachment_summaries)] if part
    )


def _has_on_topic_signal(email_output: Any) -> bool:
    classification_hint = _normalize_text(
        _get_output_value(email_output, "response_classification_hint", None)
    )
    if classification_hint and classification_hint != "unable_to_classify":
        return True

    if bool(_get_output_value(email_output, "meeting_confirmation_detected", False)):
        return True

    attachments = _get_output_value(email_output, "attachments", []) or []
    if attachments:
        return True

    text = _compose_inbound_email_text(email_output).lower()
    return any(keyword in text for keyword in ON_TOPIC_KEYWORDS)


def _has_off_topic_signal(email_output: Any) -> bool:
    text = _compose_inbound_email_text(email_output).lower()
    if not any(keyword in text for keyword in OFF_TOPIC_KEYWORDS):
        return False

    classification_hint = _normalize_text(
        _get_output_value(email_output, "response_classification_hint", None)
    )
    if classification_hint and classification_hint != "unable_to_classify":
        return False

    if bool(_get_output_value(email_output, "meeting_confirmation_detected", False)):
        return False

    attachments = _get_output_value(email_output, "attachments", []) or []
    return not attachments


def _find_pii_reasons(subject: str | None, text: str | None) -> list[str]:
    combined = "\n".join(
        part for part in [_normalize_text(subject), _normalize_text(text)] if part
    )
    if not combined:
        return []

    reasons: list[str] = []

    for label, pattern in SENSITIVE_FIELD_PATTERNS.items():
        if pattern.search(combined):
            reasons.append(label)

    for label, pattern in SENSITIVE_FINANCIAL_FIELD_PATTERNS.items():
        if pattern.search(combined):
            reasons.append(label)

    return reasons


def _find_prompt_injection_reason(text: str) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    for label, pattern in PROMPT_INJECTION_PATTERNS.items():
        if pattern.search(normalized):
            return label
    return None


def _compose_attachment_text(attachments: list[Any]) -> str:
    parts: list[str] = []
    for attachment in attachments:
        content = _normalize_text(_get_output_value(attachment, "content", None))
        justification = _normalize_text(
            _get_output_value(attachment, "justification", None)
        )
        if content:
            parts.append(content)
        if justification:
            parts.append(justification)
    return "\n".join(parts)


def _is_unreadable_attachment(attachment: Any) -> bool:
    content = _normalize_text(_get_output_value(attachment, "content", None)).lower()
    justification = _normalize_text(
        _get_output_value(attachment, "justification", None)
    ).lower()
    unreadable_markers = (
        "file not found",
        "error reading attachment",
        "ocr error",
        "unsupported attachment type",
        "could not be processed",
        "could not be analyzed reliably",
        "classification could not be completed",
    )
    return any(marker in content or marker in justification for marker in unreadable_markers)


@tool_input_guardrail
async def email_moderation_guardrail(data: Any) -> ToolGuardrailFunctionOutput:
    """Moderation guardrail for outbound email drafts."""

    mod = client.moderations.create(
        model="omni-moderation-latest",
        input=str(data),
    )
    result = mod.results[0]
    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)
    
    with guardrail_span("email_moderation_guardrail", triggered=tripped):

        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        flagged_categories = [
            name for name, flagged in vars(result.categories).items() if flagged
        ]
        categories_note = ""
        if flagged_categories:
            categories_note = f" (flagged categories: {', '.join(flagged_categories)})"

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Email blocked by moderation: content contains unsafe or inappropriate "
                f"material for this workflow.{categories_note} "
                "Please remove the offending content and try again."
            ),
            output_info={
                "moderation_flagged": tripped,
                "categories": vars(result.categories),
            },
        )


@tool_output_guardrail
async def client_on_topic_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Reject parsed inbound emails that are clearly unrelated to the workflow."""

    email_output = data.output
    response = client.responses.parse(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": ON_TOPIC_CLASSIFIER_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": _compose_inbound_email_text(email_output),
                    }
                ],
            },
        ],
        text_format=OnTopicVerdict,
    )
    verdict = response.output_parsed
    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)

    with guardrail_span("client_on_topic_guardrail", triggered=tripped):
        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Inbound email blocked: content is off-topic for the client onboarding "
                "and financial planning workflow."
            ),
            output_info={"reason": verdict.reason},
        )


@tool_output_guardrail
async def email_prompt_injection_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Reject inbound emails that attempt to manipulate agent instructions."""

    email_output = data.output
    text = _compose_inbound_email_text(email_output)
    reason = _find_prompt_injection_reason(text)
    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)

    with guardrail_span("email_prompt_injection_guardrail", triggered=tripped):
        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Inbound email blocked: content appears to contain a prompt-injection "
                "attempt or instruction-manipulation text."
            ),
            output_info={"reason": reason},
        )


@tool_input_guardrail
async def pii_filter(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Reject outbound email drafts that contain prohibited PII."""

    arguments = json.loads(data.context.tool_arguments)
    subject = arguments.get("subject")
    text = arguments.get("text")
    reasons = _find_pii_reasons(subject, text)
    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)

    with guardrail_span("email_prompt_injection_guardrail", triggered=tripped):
        
        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Email blocked: outbound drafts must not include PII or sensitive client "
                "financial details. Remove the flagged details and try again."
            ),
            output_info={"blocked_reasons": reasons},
        )


@tool_output_guardrail
async def attachment_prompt_injection_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Reject extracted attachment text that attempts to manipulate the agent."""

    attachments = data.output if isinstance(data.output, list) else []
    text = _compose_attachment_text(attachments)
    reason = _find_prompt_injection_reason(text)
    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)

    with guardrail_span("email_prompt_injection_guardrail", triggered=tripped):

        if tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Attachment processing blocked: extracted attachment content appears to "
                "contain a prompt-injection attempt or instruction-manipulation text."
            ),
            output_info={"reason": reason},
        )


@tool_output_guardrail
async def document_compliance_confidence_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Reject uncertain compliance classifications from the document processor."""

    attachments = data.output if isinstance(data.output, list) else []
    low_confidence_paths: list[dict[str, Any]] = []

    for attachment in attachments:
        if _is_unreadable_attachment(attachment):
            continue

        confidence = _get_output_value(attachment, "compliance_confidence", None)
        path = _normalize_text(_get_output_value(attachment, "path", None))
        compliance_related = _get_output_value(
            attachment, "compliance_related", None
        )

        if confidence is None:
            low_confidence_paths.append(
                {
                    "path": path,
                    "confidence": None,
                    "compliance_related": compliance_related,
                }
            )
            continue

        if confidence < DOCUMENT_COMPLIANCE_CONFIDENCE_THRESHOLD:
            low_confidence_paths.append(
                {
                    "path": path,
                    "confidence": confidence,
                    "compliance_related": compliance_related,
                }
            )

    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)
    info = {} #TODO: raise any relevent info as guardrail output
    
    with guardrail_span("document_compliance_confidence_guardrail", triggered=tripped):

        if not low_confidence_paths:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Attachment processing blocked: compliance classification confidence was "
                "too low for at least one attachment. Escalate for manual review."
            ),
            output_info=info,
       )


@tool_output_guardrail
async def pii_filter_output_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Recheck normalized outbound email payloads for prohibited PII."""

    output = data.output
    reasons = _find_pii_reasons(
        _get_output_value(output, "subject", None),
        _get_output_value(output, "text", None),
    )

    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)
    

    with guardrail_span("pii_filter_output_guardrail", triggered=tripped):

        if tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Email blocked: outbound drafts must not include PII or sensitive client "
                "financial details. Remove the flagged details and try again."
            ),
            output_info={"blocked_reasons": reasons},
        )


_FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|EXEC|EXECUTE|ATTACH|DETACH|PRAGMA|REINDEX|VACUUM)\b",
    re.IGNORECASE,
)


@tool_input_guardrail
async def sql_read_only_guardrail(
    data: ToolInputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Guardrail that rejects non-SELECT SQL statements."""

    query = json.loads(data.context.tool_arguments).get("query", "")
    match = _FORBIDDEN_SQL_PATTERN.search(query)

    tripped = False; # TODO: implement tripped boolean (guardrail will raise when True)

    with guardrail_span("document_compliance_confidence_guardrail", triggered=tripped):

        if match:
            return ToolGuardrailFunctionOutput.reject_content(
                message=(
                    f"SQL query blocked: '{match.group()}' statements are not permitted. "
                    "Only SELECT queries are allowed."
                ),
                output_info={"blocked_keyword": match.group()},
            )
        return ToolGuardrailFunctionOutput.allow()
