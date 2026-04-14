import json
from pathlib import Path
from typing import Annotated, Any

from agents import function_tool
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent
SALESFORCE_LEADS_DB_PATH = ROOT_DIR.parent / "data" / "salesforce_leads.json"


class ZocksReviewResult(BaseModel):
    """Result returned by the Zocks reviewer tool."""

    uid: Annotated[str, Field(description="Lead UID used for the lookup.")]
    found: Annotated[
        bool,
        Field(description="Whether a meeting with Zocks notes was found for the UID."),
    ]
    meeting_id: Annotated[
        str | None,
        Field(
            default=None,
            description="Meeting id for the most recent meeting with Zocks notes.",
        ),
    ]
    zocks_summary: Annotated[
        str | None,
        Field(
            default=None,
            description="Zocks summary from the most recent meeting with notes.",
        ),
    ]
    zocks_action_items: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Zocks action items from the most recent meeting with notes.",
        ),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


def update_meeting_notes(
    uid: str,
    meeting_notes: dict[str, Any],
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> dict[str, Any]:
    """Update the stored Zocks notes for a lead meeting.

    Args:
        uid: Lead UID to update.
        meeting_notes: Meeting payload with `meeting_id`, `zocks_summary`, and
            `zocks_action_items`.
        db_path: Path to the Salesforce leads JSON file.

    Returns:
        The updated meeting record.
    """
    if not uid:
        raise ValueError("`uid` is required.")

    meeting_id = meeting_notes.get("meeting_id")
    if not meeting_id:
        raise ValueError("`meeting_notes['meeting_id']` is required.")

    payload = json.loads(db_path.read_text(encoding="utf-8"))
    lead_record = payload.get(uid)
    if lead_record is None:
        raise ValueError(f"Lead record not found for uid `{uid}`.")

    meetings = lead_record.get("meetings")
    if not isinstance(meetings, list):
        raise ValueError(f"No meetings found for uid `{uid}`.")

    for meeting in meetings:
        if meeting.get("meeting_id") != meeting_id:
            continue

        meeting["zocks_summary"] = meeting_notes.get("zocks_summary")
        meeting["zocks_action_items"] = meeting_notes.get("zocks_action_items")
        db_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return meeting

    raise ValueError(f"Meeting `{meeting_id}` not found for uid `{uid}`.")


# TODO: add function tool decorator
@function_tool()
def zocks_reviewer_tool(
    uid: Annotated[str, Field(description="Lead UID used to retrieve Zocks meeting notes.")],
) -> ZocksReviewResult:
    """Retrieve the latest stored Zocks meeting notes for a lead.

    Args:
        uid: Lead UID used to look up stored meeting notes.

    Returns:
        ZocksReviewResult containing the most recent meeting with a non-null
        `zocks_summary`, or a not-found result when none exists.
    """
    if not uid:
        raise ValueError("`uid` is required.")

    payload = json.loads(SALESFORCE_LEADS_DB_PATH.read_text(encoding="utf-8"))
    lead_record = payload.get(uid)
    if lead_record is None:
        return ZocksReviewResult(
            uid=uid,
            found=False,
            meeting_id=None,
            zocks_summary=None,
            zocks_action_items=[],
            message=f"Lead record not found for uid `{uid}`.",
        )

    meetings = lead_record.get("meetings")
    if not isinstance(meetings, list) or not meetings:
        return ZocksReviewResult(
            uid=uid,
            found=False,
            meeting_id=None,
            zocks_summary=None,
            zocks_action_items=[],
            message=f"No meetings found for uid `{uid}`.",
        )

    for meeting in reversed(meetings):
        zocks_summary = meeting.get("zocks_summary")
        if zocks_summary is None:
            continue

        raw_action_items = meeting.get("zocks_action_items")
        if isinstance(raw_action_items, list):
            action_items = [str(item) for item in raw_action_items]
        elif isinstance(raw_action_items, str):
            action_items = [raw_action_items]
        else:
            action_items = []

        return ZocksReviewResult(
            uid=uid,
            found=True,
            meeting_id=meeting.get("meeting_id"),
            zocks_summary=zocks_summary,
            zocks_action_items=action_items,
            message=f"Retrieved Zocks notes for uid `{uid}`.",
        )

    return ZocksReviewResult(
        uid=uid,
        found=False,
        meeting_id=None,
        zocks_summary=None,
        zocks_action_items=[],
        message=f"No Zocks notes found for uid `{uid}`.",
    )
