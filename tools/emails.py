from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from agents import function_tool
from pydantic import BaseModel, Field

from guardrails import (
    client_on_topic_guardrail,
    email_moderation_guardrail,
    email_prompt_injection_guardrail,
    pii_filter,
    pii_filter_output_guardrail,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
EMAILS_PATH = ROOT_DIR / "data" / "emails.json"
SENDER_EMAIL = "someone@firstcommand.com"

RESPONSE_CLASSIFICATION = Literal[
    "scenario_1",
    "scenario_2",
    "information_only",
    "needs_follow_up",
    "unable_to_classify",
]


class SentEmail(BaseModel):
    """Normalized payload returned by send_email_tool."""

    sender: Annotated[
        str,
        Field(..., description="Address used to send the outbound message."),
    ]
    to: Annotated[
        list[str],
        Field(..., description="Primary recipients the draft was sent to."),
    ]
    subject: Annotated[
        str | None,
        Field(default=None, description="Subject line delivered to the recipient(s)."),
    ]
    text: Annotated[
        str | None,
        Field(default=None, description="Body content that was sent."),
    ]
    cc: Annotated[
        list[str],
        Field(default_factory=list, description="Copied recipients, if any."),
    ]
    attachments: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Attachment paths included with the email.",
        ),
    ]


class EmailReadResult(BaseModel):
    """Normalized email payload returned by the email read tool."""

    email_id: Annotated[str, Field(description="Email identifier loaded from mock data.")]
    uid: Annotated[str | None, Field(default=None, description="UID extracted from email.")]
    email_type: Annotated[
        str | None,
        Field(default=None, description="Email type label from source payload."),
    ]
    subject: Annotated[str | None, Field(default=None, description="Email subject line.")]
    sender_email: Annotated[
        str | None,
        Field(default=None, description="Sender email address."),
    ]
    recipients: Annotated[
        list[str],
        Field(default_factory=list, description="To-recipient email addresses."),
    ]
    cc_recipients: Annotated[
        list[str],
        Field(default_factory=list, description="CC-recipient email addresses."),
    ]
    body_text: Annotated[str | None, Field(default=None, description="Email body text.")]
    attachments: Annotated[
        list[dict[str, str]],
        Field(default_factory=list, description="Attachment metadata list."),
    ]
    meeting_confirmation_detected: Annotated[
        bool,
        Field(description="Whether body indicates explicit meeting availability/acceptance."),
    ]
    response_classification_hint: Annotated[
        RESPONSE_CLASSIFICATION | None,
        Field(default=None, description="Optional expected classification hint from mock payload."),
    ]


def _load_emails() -> dict[str, dict]:
    if not EMAILS_PATH.exists():
        return {}
    payload = json.loads(EMAILS_PATH.read_text(encoding="utf-8"))
    emails = payload.get("emails_by_id")
    if not isinstance(emails, dict):
        return {}
    return emails


def _extract_address_list(values: list[dict] | None) -> list[str]:
    if not values:
        return []

    addresses: list[str] = []
    for value in values:
        email = value.get("email")
        if isinstance(email, str) and email:
            addresses.append(email)
    return addresses


def _meeting_confirmation_from_body(body_text: str | None) -> bool:
    text = (body_text or "").lower()
    tokens = ("i can meet", "available", "works for me", "confirm", "accepted")
    return any(token in text for token in tokens)


def _format_attachment_names(attachments: list[dict[str, str]]) -> str:
    if not attachments:
        return "[none]"

    names: list[str] = []
    for attachment in attachments:
        filename = str(attachment.get("filename") or "").strip()
        names.append(Path(filename).name if filename else "[unnamed attachment]")

    return "\n".join(f"               - {name}" for name in names)


# TODO: add function tool decorator with guardrails for outbound email moderation
@function_tool()
async def send_email_tool(
    to: list[str],
    subject: str | None = None,
    text: str | None = None,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> SentEmail:
    """Send an outbound email using the mock email transport.

    Args:
        to: Primary recipient email addresses.
        subject: Optional subject line.
        text: Optional plain-text body.
        cc: Optional CC recipient addresses.
        attachments: Optional attachment file paths.

    Returns:
        Normalized email payload echoing the provided values.
    """
    cc_list = list() if cc is None else cc
    attachments_list = list() if attachments is None else attachments

    to_display = ", ".join(to) if to else "[no recipients]"
    cc_display = ", ".join(cc_list) if cc_list else "[none]"
    attachments_display = ", ".join(attachments_list) if attachments_list else "[none]"
    subject_display = subject or "[no subject]"

    print("\n📧 [Email Dispatch] --------------------------------------------------")
    print(f"   From       : {SENDER_EMAIL}")
    print(f"   To         : {to_display}")
    print(f"   CC         : {cc_display}")
    print(f"   Subject    : {subject_display}")
    print(f"   Attachments: {attachments_display}")
    if text:
        print("\n📝 [Email Dispatch] Body:")
        print(text)
    else:
        print("\n📝 [Email Dispatch] Body: [empty]")
    print("📧 [Email Dispatch] --------------------------------------------------\n")

    return SentEmail(
        sender=SENDER_EMAIL,
        to=to,
        subject=subject,
        text=text,
        cc=cc_list,
        attachments=attachments_list,
    )


# TODO: add function tool decorator with guardrails for email moderation
@function_tool
async def email_read_tool(
    email_id: Annotated[
        str,
        Field(description="Email id to load from data/emails.json."),
    ],
) -> EmailReadResult:
    """Read inbound email details from mock email storage.

    Args:
        email_id: Identifier of the email record in mock storage.

    Returns:
        EmailReadResult with extracted sender, body, recipients, and attachments.
    """
    email = _load_emails().get(email_id)
    if email is None:
        raise ValueError(f"Email id `{email_id}` not found in data/emails.json.")

    sender = email.get("from") or {}
    body_text = email.get("body_text")
    attachments_raw = list(email.get("attachments") or [])
    attachments: list[dict[str, str]] = []

    for item in attachments_raw:
        if isinstance(item, dict):
            attachments.append(
                {
                    "filename": str(item.get("filename") or ""),
                    "content_type": str(item.get("content_type") or ""),
                    "summary": str(item.get("summary") or ""),
                }
            )
            continue

        if isinstance(item, str):
            attachments.append(
                {"filename": item, "content_type": "application/octet-stream", "summary": ""}
            )

    to = email.get("to")
    cc = email.get("cc")
    subject = email.get("subject")

    to_addresses = _extract_address_list(to)
    cc_addresses = _extract_address_list(cc)

    to_display = ", ".join(to_addresses) if to_addresses else "[no recipients]"
    cc_display = ", ".join(cc_addresses) if cc_addresses else "[none]"
    subject_display = subject or "[no subject]"

    print("\n📧 [Inbound Email] --------------------------------------------------")
    print(f"   From       : {SENDER_EMAIL}")
    print(f"   To         : {to_display}")
    print(f"   CC         : {cc_display}")
    print(f"   Subject    : {subject_display}")
    print(f"   Attachments: \n{_format_attachment_names(attachments)}")
    if body_text:
        print("\n📝 [Inbound Email] Body:")
        print(body_text)
    else:
        print("\n📝 [Inbound Email] Body: [empty]")
    print("📧 [Inbound Email] --------------------------------------------------\n")

    return EmailReadResult(
        email_id=email_id,
        uid=email.get("uid") or email.get("UID"),
        email_type=email.get("email_type"),
        subject=subject,
        sender_email=sender.get("email"),
        recipients=_extract_address_list(to),
        cc_recipients=_extract_address_list(cc),
        body_text=body_text,
        attachments=attachments,
        meeting_confirmation_detected=_meeting_confirmation_from_body(body_text),
        response_classification_hint=email.get("response_classification_expected"),
    )
