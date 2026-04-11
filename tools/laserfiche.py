from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from agents import function_tool
from pydantic import BaseModel, Field
from scripts.path_utils import DATA_DIR, repo_relative_path

LASERFICHE_DB_PATH = DATA_DIR / "laserfiche.json"


class LaserficheUploadResult(BaseModel):
    """Normalized payload returned by the Laserfiche uploader tool."""

    uid: Annotated[str, Field(description="UID used for the Laserfiche upload.")]
    attachment_path: Annotated[str, Field(description="Attachment path that was stored.")]
    attachments: Annotated[
        list[str],
        Field(description="Current attachment paths stored for the UID after the update."),
    ]
    message: Annotated[str, Field(description="Write outcome summary.")]


def _load_laserfiche_db(db_path: Path = LASERFICHE_DB_PATH) -> dict[str, Any]:
    if not db_path.exists():
        return {}

    return json.loads(db_path.read_text(encoding="utf-8"))


def _write_laserfiche_db(
    payload: dict[str, Any],
    db_path: Path = LASERFICHE_DB_PATH,
) -> None:
    db_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_uid_attachments(payload: dict[str, Any], uid: str) -> list[str]:
    attachments = payload.get(uid)
    if attachments is None:
        return []

    if not isinstance(attachments, list):
        raise ValueError(f"Laserfiche record for uid `{uid}` must be a list of attachment paths.")

    normalized_attachments: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, str):
            raise ValueError(
                f"Laserfiche record for uid `{uid}` contains a non-string attachment path."
            )
        normalized_attachments.append(attachment)

    return normalized_attachments


def upload_laserfiche_attachment(
    uid: str,
    attachment_path: str,
    db_path: Path = LASERFICHE_DB_PATH,
) -> LaserficheUploadResult:
    """Append an attachment path to the mock Laserfiche database for a UID."""

    if not uid:
        raise ValueError("`uid` is required.")

    if not attachment_path:
        raise ValueError("`attachment_path` is required.")

    normalized_attachment_path = repo_relative_path(attachment_path)
    payload = _load_laserfiche_db(db_path)
    attachments = _get_uid_attachments(payload, uid)
    attachments.append(normalized_attachment_path)
    payload[uid] = attachments
    _write_laserfiche_db(payload, db_path)

    return LaserficheUploadResult(
        uid=uid,
        attachment_path=normalized_attachment_path,
        attachments=attachments,
        message=f"Stored attachment for uid `{uid}` in mock Laserfiche.",
    )


# TODO: add function tool decorator 
def laserfiche_uploader_tool(
    uid: Annotated[
        str,
        Field(description="UID used to append an attachment path in mock Laserfiche storage."),
    ],
    attachment_path: Annotated[
        str,
        Field(description="Attachment path to store for the UID in data/laserfiche.json."),
    ],
) -> LaserficheUploadResult:
    """Store an attachment path in the mock Laserfiche database.

    Args:
        uid: UID key whose attachment list should be updated.
        attachment_path: Attachment path to append for the UID.

    Returns:
        LaserficheUploadResult containing the stored path and the current UID attachment list.
    """
    return upload_laserfiche_attachment(uid, attachment_path)
