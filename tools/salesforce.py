from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from agents import function_tool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scripts.path_utils import DATA_DIR, repo_relative_path

SALESFORCE_CLIENTS_DB_PATH = DATA_DIR / "salesforce_clients.json"
SALESFORCE_LEADS_DB_PATH = DATA_DIR / "salesforce_leads.json"
SALESFORCE_ADVISORS_DB_PATH = DATA_DIR / "salesforce_advisors.json"
SALESFORCE_NOTIFICATIONS_DB_PATH = DATA_DIR / "salesforce_notifications.json"
SYNCED_FORM_1500_LEAD_FIELDS = ("first_name", "last_name", "email")

LEAD_STATUS = Literal["New", "Working", "Qualified"]
LEAD_STATUS_UPDATE = Literal["Working", "Qualified"]
PERSON_STATUS = Literal["Lead", "Prospect", "Prospective Buyer"]


class SalesforceClientForm1500(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    date_of_birth: Annotated[date | None, Field(default=None)]
    marital_status: Annotated[str | None, Field(default=None)]
    email: Annotated[str, Field(min_length=1)]
    mobile_phone: Annotated[str | None, Field(default=None)]
    city: Annotated[str | None, Field(default=None)]
    state: Annotated[str | None, Field(default=None)]
    service_affiliation: Annotated[str | None, Field(default=None)]
    branch_of_service: Annotated[str | None, Field(default=None)]
    military_status: Annotated[str | None, Field(default=None)]
    rank_or_pay_grade: Annotated[str | None, Field(default=None)]
    projected_retirement_date: Annotated[date | None, Field(default=None)]
    spouse_name: Annotated[str | None, Field(default=None)]
    dependents_count: Annotated[int | None, Field(default=None, ge=0)]
    primary_goal: Annotated[str | None, Field(default=None)]
    annual_household_income: Annotated[int | float | None, Field(default=None, ge=0)]
    monthly_expenses: Annotated[int | float | None, Field(default=None, ge=0)]
    liquid_cash: Annotated[int | float | None, Field(default=None, ge=0)]
    retirement_account_balance: Annotated[int | float | None, Field(default=None, ge=0)]
    total_debt_balance: Annotated[int | float | None, Field(default=None, ge=0)]
    risk_tolerance: Annotated[str | None, Field(default=None)]
    life_insurance_coverage: Annotated[int | float | None, Field(default=None, ge=0)]
    estate_documents_in_place: Annotated[bool | None, Field(default=None)]
    planning_notes: Annotated[str | None, Field(default=None)]


class SalesforceMeetingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: Annotated[datetime, Field(description="Scheduled meeting start time in UTC.")]
    end_time: Annotated[datetime, Field(description="Scheduled meeting end time in UTC.")]
    meeting_id: Annotated[str, Field(min_length=1, description="Sequential meeting id for the lead.")]
    zocks_summary: Annotated[
        str | None,
        Field(default=None, description="Optional Zocks meeting summary after the meeting completes."),
    ]
    zocks_action_items: Annotated[
        list[str] | None,
        Field(default=None, description="Optional Zocks-generated action items after the meeting completes."),
    ]

    @model_validator(mode="after")
    def validate_schedule(self) -> "SalesforceMeetingRecord":
        if self.start_time.tzinfo is None:
            raise ValueError("`start_time` must include a UTC timezone offset.")

        if self.end_time.tzinfo is None:
            raise ValueError("`end_time` must include a UTC timezone offset.")

        if self.start_time.utcoffset() != timezone.utc.utcoffset(self.start_time):
            raise ValueError("`start_time` must be in UTC.")

        if self.end_time.utcoffset() != timezone.utc.utcoffset(self.end_time):
            raise ValueError("`end_time` must be in UTC.")

        if self.end_time <= self.start_time:
            raise ValueError("`end_time` must be later than `start_time`.")

        return self


class SalesforceClientRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: Annotated[str, Field(min_length=1)]
    advisor_name: Annotated[str | None, Field(default=None)]
    advisor_id: Annotated[str | None, Field(default=None)]
    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    email: Annotated[str, Field(min_length=1)]
    form_1500: Annotated[SalesforceClientForm1500, Field()]
    meetings: Annotated[list[SalesforceMeetingRecord] | None, Field(default=None)]


class SalesforceLeadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: Annotated[str, Field(min_length=1)]
    lead_status: Annotated[LEAD_STATUS, Field(default="New")]
    person_status: Annotated[PERSON_STATUS, Field(default="Lead")]
    advisor_name: Annotated[str | None, Field(default=None)]
    advisor_id: Annotated[str | None, Field(default=None)]
    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    email: Annotated[str, Field(min_length=1)]
    form_1500: Annotated[SalesforceClientForm1500, Field()]
    meetings: Annotated[list[SalesforceMeetingRecord] | None, Field(default=None)]
    document: Annotated[
        list[str] | None,
        Field(default=None, description="Uploaded Salesforce document file paths for the lead."),
    ]


class SalesforceClientLookupResult(BaseModel):
    """Result returned by the Salesforce client retrieval tool."""

    uid: Annotated[str, Field(description="UID used for the lookup.")]
    found: Annotated[bool, Field(description="Whether a matching client record was found.")]
    client_record: Annotated[
        SalesforceClientRecord | None,
        Field(default=None, description="Validated client record when found."),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


class SalesforceClientUpsertResult(BaseModel):
    """Result returned by the Salesforce client upsert tool."""

    uid: Annotated[str, Field(description="UID used for the write operation.")]
    client_record: Annotated[
        SalesforceClientRecord,
        Field(description="Validated client record that was written to storage."),
    ]
    message: Annotated[str, Field(description="Write outcome summary.")]


class SalesforceClientQueryResult(BaseModel):
    """Result returned by the Salesforce client query tool."""

    uid: Annotated[str, Field(description="Lead UID used for the client check.")]
    found: Annotated[bool, Field(description="Whether the input lead record was found.")]
    is_existing_client: Annotated[
        bool,
        Field(
            description="Whether a client shares the same first name, last name, and email as the lead.",
        ),
    ]
    matching_client_uids: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Client UIDs with the same first name, last name, and email as the lead.",
        ),
    ]
    message: Annotated[str, Field(description="Client check outcome summary.")]


class SalesforceClientInformationResult(BaseModel):
    """Result returned by the Salesforce client information tool."""

    uid: Annotated[str, Field(description="Lead UID used for the lookup.")]
    found: Annotated[bool, Field(description="Whether a matching lead record was found.")]
    form_1500: Annotated[
        SalesforceClientForm1500 | None,
        Field(default=None, description="Form 1500 data for the lead when found."),
    ]
    is_form_1500_complete: Annotated[
        bool,
        Field(description="Whether all Form 1500 fields are populated with non-empty values."),
    ]
    missing_fields: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Form 1500 field names that are empty or null.",
        ),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


class SalesforceLeadLookupResult(BaseModel):
    uid: Annotated[str, Field(description="UID used for the lookup.")]
    found: Annotated[bool, Field(description="Whether a matching lead record was found.")]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Validated lead record when found."),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


class SalesforceLeadUpsertResult(BaseModel):
    uid: Annotated[str, Field(description="UID used for the write operation.")]
    lead_record: Annotated[
        SalesforceLeadRecord,
        Field(description="Validated lead record that was written to storage."),
    ]
    message: Annotated[str, Field(description="Write outcome summary.")]


class SalesforceLeadDuplicateQueryResult(BaseModel):
    """Result returned by the Salesforce duplicate lead query tool."""

    uid: Annotated[str, Field(description="UID used for the duplicate check.")]
    found: Annotated[bool, Field(description="Whether the input lead record was found.")]
    is_duplicate: Annotated[
        bool,
        Field(
            description="Whether another lead shares the same first name, last name, and email.",
        ),
    ]
    duplicate_uids: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Other lead UIDs with the same first name, last name, and email.",
        ),
    ]
    message: Annotated[str, Field(description="Duplicate check outcome summary.")]


class SalesforceLeadStatusUpdateResult(BaseModel):
    """Result returned by the Salesforce lead status update tool."""

    uid: Annotated[str, Field(description="UID used for the lead status update.")]
    found: Annotated[bool, Field(description="Whether the input lead record was found.")]
    previous_status: Annotated[
        LEAD_STATUS | None,
        Field(default=None, description="Lead status before the update, when found."),
    ]
    updated_status: Annotated[
        LEAD_STATUS | None,
        Field(default=None, description="Lead status after the update, when found."),
    ]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Updated lead record when found."),
    ]
    message: Annotated[str, Field(description="Lead status update outcome summary.")]


class SalesforceClientInputForm1500Update(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Annotated[str | None, Field(default=None)]
    last_name: Annotated[str | None, Field(default=None)]
    date_of_birth: Annotated[date | None, Field(default=None)]
    marital_status: Annotated[str | None, Field(default=None)]
    email: Annotated[str | None, Field(default=None)]
    mobile_phone: Annotated[str | None, Field(default=None)]
    city: Annotated[str | None, Field(default=None)]
    state: Annotated[str | None, Field(default=None)]
    service_affiliation: Annotated[str | None, Field(default=None)]
    branch_of_service: Annotated[str | None, Field(default=None)]
    military_status: Annotated[str | None, Field(default=None)]
    rank_or_pay_grade: Annotated[str | None, Field(default=None)]
    projected_retirement_date: Annotated[date | None, Field(default=None)]
    spouse_name: Annotated[str | None, Field(default=None)]
    dependents_count: Annotated[int | None, Field(default=None, ge=0)]
    primary_goal: Annotated[str | None, Field(default=None)]
    annual_household_income: Annotated[int | float | None, Field(default=None, ge=0)]
    monthly_expenses: Annotated[int | float | None, Field(default=None, ge=0)]
    liquid_cash: Annotated[int | float | None, Field(default=None, ge=0)]
    retirement_account_balance: Annotated[int | float | None, Field(default=None, ge=0)]
    total_debt_balance: Annotated[int | float | None, Field(default=None, ge=0)]
    risk_tolerance: Annotated[str | None, Field(default=None)]
    life_insurance_coverage: Annotated[int | float | None, Field(default=None, ge=0)]
    estate_documents_in_place: Annotated[bool | None, Field(default=None)]
    planning_notes: Annotated[str | None, Field(default=None)]


class SalesforceClientInputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_status: Annotated[
        LEAD_STATUS | None,
        Field(
            default=None,
            description="Optional lead status update to apply to the target lead record.",
        ),
    ]
    person_status: Annotated[
        PERSON_STATUS | None,
        Field(
            default=None,
            description="Optional person status update to apply to the target lead record.",
        ),
    ]
    form_1500: Annotated[
        SalesforceClientInputForm1500Update | None,
        Field(
            default=None,
            description="Optional partial Form 1500 field updates to merge into the stored lead record.",
        ),
    ]


class SalesforceClientInputResult(BaseModel):
    """Result returned by the Salesforce client input tool."""

    uid: Annotated[str, Field(description="UID used for the update operation.")]
    found: Annotated[bool, Field(description="Whether a matching lead record was found.")]
    updated_fields: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Field paths that changed on the stored lead record.",
        ),
    ]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Updated lead record when found."),
    ]
    message: Annotated[str, Field(description="Update outcome summary.")]


class SalesforceMeetingScheduleResult(BaseModel):
    """Result returned by the Salesforce meeting scheduler tool."""

    uid: Annotated[str, Field(description="UID used for the meeting scheduling operation.")]
    found: Annotated[bool, Field(description="Whether a matching lead record was found.")]
    meeting_record: Annotated[
        SalesforceMeetingRecord | None,
        Field(default=None, description="Meeting that was scheduled for the lead."),
    ]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Updated lead record when found."),
    ]
    message: Annotated[str, Field(description="Meeting scheduling outcome summary.")]


class SalesforceDocumentUploadResult(BaseModel):
    """Result returned by the Salesforce document uploader tool."""

    uid: Annotated[str, Field(description="UID used for the document upload operation.")]
    found: Annotated[bool, Field(description="Whether a matching lead record was found.")]
    uploaded_documents: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Document file paths appended to the lead record during this upload.",
        ),
    ]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Updated lead record when found."),
    ]
    message: Annotated[str, Field(description="Document upload outcome summary.")]


class SalesforceLeadDeleteResult(BaseModel):
    """Result returned by the Salesforce lead delete tool."""

    uid: Annotated[str, Field(description="Lead UID used for the delete operation.")]
    found: Annotated[bool, Field(description="Whether the input lead record was found.")]
    deleted: Annotated[bool, Field(description="Whether the lead record was deleted.")]
    message: Annotated[str, Field(description="Lead delete outcome summary.")]


class SalesforceAdvisorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisor_id: Annotated[str, Field(min_length=1)]
    advisor_name: Annotated[str, Field(min_length=1)]
    skills: Annotated[list[str], Field(min_length=1)]
    branch_type: Annotated[str, Field(min_length=1)]
    state: Annotated[str, Field(min_length=1)]
    available_blocks: Annotated[list[str], Field(default_factory=list)]


class SalesforceNotificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: Annotated[str, Field(min_length=1)]
    scenario_id: Annotated[str, Field(min_length=1)]
    notification_type: Annotated[str, Field(min_length=1)]
    first_name: Annotated[str | None, Field(default=None)]
    last_name: Annotated[str | None, Field(default=None)]
    email: Annotated[str | None, Field(default=None)]
    description: Annotated[str, Field(min_length=1)]


class SalesforceAdvisorLookupResult(BaseModel):
    advisor_id: Annotated[str, Field(description="Advisor id used for the lookup.")]
    found: Annotated[bool, Field(description="Whether a matching advisor record was found.")]
    advisor_record: Annotated[
        SalesforceAdvisorRecord | None,
        Field(default=None, description="Validated advisor record when found."),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


class SalesforceAdvisorUpsertResult(BaseModel):
    advisor_id: Annotated[str, Field(description="Advisor id used for the write operation.")]
    advisor_record: Annotated[
        SalesforceAdvisorRecord,
        Field(description="Validated advisor record that was written to storage."),
    ]
    message: Annotated[str, Field(description="Write outcome summary.")]


class SalesforceAdvisorSearchResult(BaseModel):
    """Result returned by the Salesforce advisor search tool."""

    state: Annotated[str, Field(description="State code used for the advisor search.")]
    found: Annotated[bool, Field(description="Whether any advisors matched the search or fallback.")]
    used_remote_fallback: Annotated[
        bool,
        Field(description="Whether the result fell back to remote advisors."),
    ]
    no_region_based_matches: Annotated[
        bool,
        Field(
            description="Whether no advisors matched the requested state and remote advisors were suggested instead.",
        ),
    ]
    advisor_records: Annotated[
        list[SalesforceAdvisorRecord],
        Field(
            default_factory=list,
            description="Advisor records matching the state or remote fallback.",
        ),
    ]
    message: Annotated[str, Field(description="Advisor search outcome summary.")]


class SalesforceAdvisorCalendarResult(BaseModel):
    """Result returned by the advisor calendar availability tool."""

    uid: Annotated[str, Field(description="Lead UID used for the availability lookup.")]
    advisor_id: Annotated[
        str | None,
        Field(default=None, description="Advisor id used for the availability lookup."),
    ]
    found: Annotated[
        bool,
        Field(description="Whether advisor availability was found for the lead."),
    ]
    advisor_name: Annotated[
        str | None,
        Field(default=None, description="Advisor name when the advisor record is found."),
    ]
    available_blocks: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Available meeting time blocks returned for the advisor.",
        ),
    ]
    message: Annotated[str, Field(description="Availability lookup outcome summary.")]


class SalesforceAdvisorAssignmentResult(BaseModel):
    """Result returned by the Salesforce advisor assignment tool."""

    uid: Annotated[str, Field(description="Lead UID used for the advisor assignment.")]
    advisor_id: Annotated[str, Field(description="Advisor id used for the assignment.")]
    lead_found: Annotated[bool, Field(description="Whether the input lead record was found.")]
    advisor_found: Annotated[bool, Field(description="Whether the advisor record was found.")]
    lead_record: Annotated[
        SalesforceLeadRecord | None,
        Field(default=None, description="Updated lead record when the assignment succeeds."),
    ]
    message: Annotated[str, Field(description="Advisor assignment outcome summary.")]


class SalesforceNotificationLookupResult(BaseModel):
    notification_id: Annotated[str, Field(description="Notification id used for the lookup.")]
    found: Annotated[bool, Field(description="Whether a matching notification record was found.")]
    notification_record: Annotated[
        SalesforceNotificationRecord | None,
        Field(default=None, description="Validated notification record when found."),
    ]
    message: Annotated[str, Field(description="Lookup outcome summary.")]


class SalesforceNotificationUpsertResult(BaseModel):
    notification_id: Annotated[
        str,
        Field(description="Notification id used for the write operation."),
    ]
    notification_record: Annotated[
        SalesforceNotificationRecord,
        Field(description="Validated notification record that was written to storage."),
    ]
    message: Annotated[str, Field(description="Write outcome summary.")]


def _load_keyed_db(db_path: Path) -> dict[str, dict]:
    if not db_path.exists():
        return {}

    payload = json.loads(db_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected `{db_path}` to contain a top-level JSON object.")

    return payload


def _write_keyed_db(db_path: Path, payload: dict[str, dict]) -> None:
    db_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def get_salesforce_client(
    uid: str,
    db_path: Path = SALESFORCE_CLIENTS_DB_PATH,
) -> SalesforceClientRecord | None:
    """Return the Salesforce client record for a uid, or `None` when it does not exist."""

    if not uid:
        raise ValueError("`uid` is required.")

    payload = _load_keyed_db(db_path)
    client_record = payload.get(uid)
    if client_record is None:
        return None

    return SalesforceClientRecord.model_validate(client_record)


def set_salesforce_client(
    uid: str,
    client_data: SalesforceClientRecord | dict[str, Any],
    db_path: Path = SALESFORCE_CLIENTS_DB_PATH,
) -> SalesforceClientRecord:
    """Validate and upsert a Salesforce client record for the provided uid."""

    if not uid:
        raise ValueError("`uid` is required.")

    record = SalesforceClientRecord.model_validate(client_data)
    if record.uid != uid:
        raise ValueError("`uid` must match `client_data.uid`.")

    payload = _load_keyed_db(db_path)
    payload[uid] = record.model_dump(mode="json")
    _write_keyed_db(db_path, payload)
    return record


def find_matching_salesforce_client_uids(
    uid: str,
    leads_db_path: Path = SALESFORCE_LEADS_DB_PATH,
    clients_db_path: Path = SALESFORCE_CLIENTS_DB_PATH,
) -> list[str]:
    """Return client UIDs that match a lead's first name, last name, and email."""

    lead_record = get_salesforce_lead(uid, db_path=leads_db_path)
    if lead_record is None:
        return []

    payload = _load_keyed_db(clients_db_path)
    matching_client_uids: list[str] = []
    for client_uid, client_data in payload.items():
        client_record = SalesforceClientRecord.model_validate(client_data)
        if (
            client_record.first_name == lead_record.first_name
            and client_record.last_name == lead_record.last_name
            and client_record.email == lead_record.email
        ):
            matching_client_uids.append(client_uid)

    return matching_client_uids


def get_missing_form_1500_fields(form_1500: SalesforceClientForm1500) -> list[str]:
    """Return Form 1500 field names that are empty or null."""

    missing_fields: list[str] = []
    for field_name, value in form_1500.model_dump(mode="json").items():
        if value is None:
            missing_fields.append(field_name)
            continue

        if isinstance(value, str) and not value.strip():
            missing_fields.append(field_name)

    return missing_fields


def get_salesforce_lead(
    uid: str,
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceLeadRecord | None:
    """Return the Salesforce lead record for a uid, or `None` when it does not exist."""

    if not uid:
        raise ValueError("`uid` is required.")

    payload = _load_keyed_db(db_path)
    lead_record = payload.get(uid)
    if lead_record is None:
        return None

    return SalesforceLeadRecord.model_validate(lead_record)


def set_salesforce_lead(
    uid: str,
    lead_data: SalesforceLeadRecord | dict[str, Any],
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceLeadRecord:
    """Validate and upsert a Salesforce lead record for the provided uid."""

    if not uid:
        raise ValueError("`uid` is required.")

    record = SalesforceLeadRecord.model_validate(lead_data)
    if record.uid != uid:
        raise ValueError("`uid` must match `lead_data.uid`.")

    payload = _load_keyed_db(db_path)
    payload[uid] = record.model_dump(mode="json")
    _write_keyed_db(db_path, payload)
    return record


def find_duplicate_salesforce_lead_uids(
    uid: str,
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> list[str]:
    """Return other lead UIDs with the same first name, last name, and email."""

    lead_record = get_salesforce_lead(uid, db_path=db_path)
    if lead_record is None:
        return []

    payload = _load_keyed_db(db_path)
    duplicate_uids: list[str] = []
    for other_uid, other_lead_data in payload.items():
        if other_uid == uid:
            continue

        other_lead = SalesforceLeadRecord.model_validate(other_lead_data)
        if (
            other_lead.first_name == lead_record.first_name
            and other_lead.last_name == lead_record.last_name
            and other_lead.email == lead_record.email
        ):
            duplicate_uids.append(other_uid)

    return duplicate_uids


def update_salesforce_lead_status(
    uid: str,
    lead_status: LEAD_STATUS_UPDATE,
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceLeadRecord | None:
    """Update the lead status for a uid and return the saved record."""

    lead_record = get_salesforce_lead(uid, db_path=db_path)
    if lead_record is None:
        return None

    updated_record = lead_record.model_copy(update={"lead_status": lead_status})
    return set_salesforce_lead(uid, updated_record, db_path=db_path)


def apply_salesforce_client_input(
    uid: str,
    client_input: SalesforceClientInputPayload | dict[str, Any],
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceClientInputResult:
    """Apply a partial lead update based on structured client-response input."""

    if not uid:
        raise ValueError("`uid` is required.")

    lead_record = get_salesforce_lead(uid, db_path=db_path)
    if lead_record is None:
        return SalesforceClientInputResult(
            uid=uid,
            found=False,
            updated_fields=[],
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    payload = SalesforceClientInputPayload.model_validate(client_input)
    if not payload.model_fields_set:
        raise ValueError(
            "At least one of `lead_status`, `person_status`, or `form_1500` must be provided."
        )

    lead_updates: dict[str, Any] = {}
    updated_fields: list[str] = []

    if "lead_status" in payload.model_fields_set and payload.lead_status is not None:
        if lead_record.lead_status != payload.lead_status:
            updated_fields.append("lead_status")
        lead_updates["lead_status"] = payload.lead_status

    if "person_status" in payload.model_fields_set and payload.person_status is not None:
        if lead_record.person_status != payload.person_status:
            updated_fields.append("person_status")
        lead_updates["person_status"] = payload.person_status

    if "form_1500" in payload.model_fields_set:
        if payload.form_1500 is None:
            raise ValueError("`form_1500` cannot be null when provided.")

        form_updates = payload.form_1500.model_dump(mode="python", exclude_unset=True)
        if form_updates:
            merged_form_1500 = lead_record.form_1500.model_copy(update=form_updates)
            lead_updates["form_1500"] = merged_form_1500

            for field_name, new_value in form_updates.items():
                if getattr(lead_record.form_1500, field_name) != new_value:
                    updated_fields.append(f"form_1500.{field_name}")

            for field_name in SYNCED_FORM_1500_LEAD_FIELDS:
                if field_name not in form_updates:
                    continue

                synced_value = getattr(merged_form_1500, field_name)
                if getattr(lead_record, field_name) != synced_value:
                    updated_fields.append(field_name)
                lead_updates[field_name] = synced_value

    if not lead_updates:
        raise ValueError(
            "At least one changed `lead_status`, `person_status`, or `form_1500` field is required."
        )

    updated_record = lead_record.model_copy(update=lead_updates)
    saved_record = set_salesforce_lead(uid, updated_record, db_path=db_path)
    return SalesforceClientInputResult(
        uid=uid,
        found=True,
        updated_fields=updated_fields,
        lead_record=saved_record,
        message=f"Lead record updated for uid `{uid}`.",
    )


def schedule_salesforce_meeting(
    uid: str,
    start_time: datetime,
    end_time: datetime,
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceMeetingScheduleResult:
    """Schedule a new meeting for a Salesforce lead and persist it to storage."""

    if not uid:
        raise ValueError("`uid` is required.")

    lead_record = get_salesforce_lead(uid, db_path=db_path)
    if lead_record is None:
        return SalesforceMeetingScheduleResult(
            uid=uid,
            found=False,
            meeting_record=None,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    existing_meetings = list(lead_record.meetings or [])
    meeting_record = SalesforceMeetingRecord(
        start_time=start_time,
        end_time=end_time,
        meeting_id=f"meeting_{len(existing_meetings) + 1}",
        zocks_summary=None,
        zocks_action_items=None,
    )
    updated_record = lead_record.model_copy(
        update={"meetings": [*existing_meetings, meeting_record]}
    )
    saved_record = set_salesforce_lead(uid, updated_record, db_path=db_path)
    return SalesforceMeetingScheduleResult(
        uid=uid,
        found=True,
        meeting_record=meeting_record,
        lead_record=saved_record,
        message=f"Meeting `{meeting_record.meeting_id}` scheduled for uid `{uid}`.",
    )


def upload_salesforce_documents(
    uid: str,
    document_paths: str | list[str],
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> SalesforceDocumentUploadResult:
    """Append one or more document paths to a Salesforce lead record."""

    if not uid:
        raise ValueError("`uid` is required.")

    lead_record = get_salesforce_lead(uid, db_path=db_path)
    if lead_record is None:
        return SalesforceDocumentUploadResult(
            uid=uid,
            found=False,
            uploaded_documents=[],
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    normalized_paths = [document_paths] if isinstance(document_paths, str) else document_paths
    cleaned_paths = [
        repo_relative_path(path.strip())
        for path in normalized_paths
        if isinstance(path, str) and path.strip()
    ]
    if not cleaned_paths:
        raise ValueError("At least one non-empty document path is required.")

    existing_documents = list(lead_record.document or [])
    updated_record = lead_record.model_copy(
        update={"document": [*existing_documents, *cleaned_paths]}
    )
    saved_record = set_salesforce_lead(uid, updated_record, db_path=db_path)
    return SalesforceDocumentUploadResult(
        uid=uid,
        found=True,
        uploaded_documents=cleaned_paths,
        lead_record=saved_record,
        message=f"Uploaded {len(cleaned_paths)} document(s) for uid `{uid}`.",
    )


def delete_salesforce_lead(
    uid: str,
    db_path: Path = SALESFORCE_LEADS_DB_PATH,
) -> bool:
    """Delete a lead record by uid and return whether it was removed."""

    if not uid:
        raise ValueError("`uid` is required.")

    payload = _load_keyed_db(db_path)
    if uid not in payload:
        return False

    del payload[uid]
    _write_keyed_db(db_path, payload)
    return True


def get_salesforce_advisor(
    advisor_id: str,
    db_path: Path = SALESFORCE_ADVISORS_DB_PATH,
) -> SalesforceAdvisorRecord | None:
    """Return the Salesforce advisor record for an advisor id, or `None` when it does not exist."""

    if not advisor_id:
        raise ValueError("`advisor_id` is required.")

    payload = _load_keyed_db(db_path)
    advisor_record = payload.get(advisor_id)
    if advisor_record is None:
        return None

    return SalesforceAdvisorRecord.model_validate(advisor_record)


def set_salesforce_advisor(
    advisor_id: str,
    advisor_data: SalesforceAdvisorRecord | dict[str, Any],
    db_path: Path = SALESFORCE_ADVISORS_DB_PATH,
) -> SalesforceAdvisorRecord:
    """Validate and upsert a Salesforce advisor record for the provided advisor id."""

    if not advisor_id:
        raise ValueError("`advisor_id` is required.")

    record = SalesforceAdvisorRecord.model_validate(advisor_data)
    if record.advisor_id != advisor_id:
        raise ValueError("`advisor_id` must match `advisor_data.advisor_id`.")

    payload = _load_keyed_db(db_path)
    payload[advisor_id] = record.model_dump(mode="json")
    _write_keyed_db(db_path, payload)
    return record


def search_salesforce_advisors_by_state(
    state: str,
    db_path: Path = SALESFORCE_ADVISORS_DB_PATH,
) -> tuple[list[SalesforceAdvisorRecord], bool, bool]:
    """Return advisors matching a state code, or remote advisors when none match."""

    if not state:
        raise ValueError("`state` is required.")

    payload = _load_keyed_db(db_path)
    advisor_records = [
        SalesforceAdvisorRecord.model_validate(advisor_data)
        for advisor_data in payload.values()
    ]
    normalized_state = state.strip().lower()
    remote_matches = [
        advisor_record
        for advisor_record in advisor_records
        if advisor_record.branch_type.strip().lower() == "remote"
    ]

    if normalized_state == "remote":
        return remote_matches, True, True

    state_matches = [
        advisor_record
        for advisor_record in advisor_records
        if advisor_record.state.strip().lower() == normalized_state
    ]
    if state_matches:
        return state_matches, False, False

    return remote_matches, True, True


def assign_salesforce_advisor_to_lead(
    uid: str,
    advisor_id: str,
    leads_db_path: Path = SALESFORCE_LEADS_DB_PATH,
    advisors_db_path: Path = SALESFORCE_ADVISORS_DB_PATH,
) -> SalesforceLeadRecord | None:
    """Assign an advisor id and name to a lead and return the saved record."""

    lead_record = get_salesforce_lead(uid, db_path=leads_db_path)
    if lead_record is None:
        return None

    advisor_record = get_salesforce_advisor(advisor_id, db_path=advisors_db_path)
    if advisor_record is None:
        return None

    updated_record = lead_record.model_copy(
        update={
            "advisor_id": advisor_record.advisor_id,
            "advisor_name": advisor_record.advisor_name,
        }
    )
    return set_salesforce_lead(uid, updated_record, db_path=leads_db_path)


def get_salesforce_advisor_calendar(
    uid: str,
    leads_db_path: Path = SALESFORCE_LEADS_DB_PATH,
    advisors_db_path: Path = SALESFORCE_ADVISORS_DB_PATH,
) -> SalesforceAdvisorCalendarResult:
    """Return advisor availability for the advisor assigned to a lead.

    Args:
        uid: Lead UID used to find the assigned advisor.
        leads_db_path: Path to the mock Salesforce leads database.
        advisors_db_path: Path to the mock Salesforce advisors database.

    Returns:
        SalesforceAdvisorCalendarResult indicating whether the lead exists, has an assigned
        advisor, and whether the advisor availability could be retrieved.
    """
    if not uid:
        raise ValueError("`uid` is required.")

    lead_record = get_salesforce_lead(uid, db_path=leads_db_path)
    if lead_record is None:
        return SalesforceAdvisorCalendarResult(
            uid=uid,
            advisor_id=None,
            found=False,
            advisor_name=None,
            available_blocks=[],
            message=f"Lead record not found for uid `{uid}`.",
        )

    if not lead_record.advisor_id:
        return SalesforceAdvisorCalendarResult(
            uid=uid,
            advisor_id=None,
            found=False,
            advisor_name=lead_record.advisor_name,
            available_blocks=[],
            message=f"No advisor is assigned to uid `{uid}`.",
        )

    advisor_record = get_salesforce_advisor(lead_record.advisor_id, db_path=advisors_db_path)
    if advisor_record is None:
        return SalesforceAdvisorCalendarResult(
            uid=uid,
            advisor_id=lead_record.advisor_id,
            found=False,
            advisor_name=lead_record.advisor_name,
            available_blocks=[],
            message=f"Advisor record not found for advisor_id `{lead_record.advisor_id}` assigned to uid `{uid}`.",
        )

    return SalesforceAdvisorCalendarResult(
        uid=uid,
        advisor_id=advisor_record.advisor_id,
        found=True,
        advisor_name=advisor_record.advisor_name,
        available_blocks=advisor_record.available_blocks,
        message=(
            f"Returned {len(advisor_record.available_blocks)} available block(s) "
            f"for uid `{uid}` and advisor_id `{advisor_record.advisor_id}`."
        ),
    )


def get_salesforce_notification(
    notification_id: str,
    db_path: Path = SALESFORCE_NOTIFICATIONS_DB_PATH,
) -> SalesforceNotificationRecord | None:
    """Return the Salesforce notification record for an id, or `None` when it does not exist."""

    if not notification_id:
        raise ValueError("`notification_id` is required.")

    payload = _load_keyed_db(db_path)
    notification_record = payload.get(notification_id)
    if notification_record is None:
        return None

    return SalesforceNotificationRecord.model_validate(notification_record)


def set_salesforce_notification(
    notification_id: str,
    notification_data: SalesforceNotificationRecord | dict[str, Any],
    db_path: Path = SALESFORCE_NOTIFICATIONS_DB_PATH,
) -> SalesforceNotificationRecord:
    """Validate and upsert a Salesforce notification record for the provided notification id."""

    if not notification_id:
        raise ValueError("`notification_id` is required.")

    record = SalesforceNotificationRecord.model_validate(notification_data)
    if record.notification_id != notification_id:
        raise ValueError("`notification_id` must match `notification_data.notification_id`.")

    payload = _load_keyed_db(db_path)
    payload[notification_id] = record.model_dump(mode="json")
    _write_keyed_db(db_path, payload)
    return record


# TODO: add function tool decorator
@function_tool
def salesforce_client_db_get_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to retrieve a client record from mock Salesforce storage."),
    ],
) -> SalesforceClientLookupResult:
    """Retrieve a Salesforce client record from the mock client database.

    Args:
        uid: UID key of the client record to retrieve.

    Returns:
        SalesforceClientLookupResult indicating whether a record was found and, when present, the structured client payload.
    """
    client_record = get_salesforce_client(uid)
    if client_record is None:
        return SalesforceClientLookupResult(
            uid=uid,
            found=False,
            client_record=None,
            message=f"Client record not found for uid `{uid}`.",
        )

    return SalesforceClientLookupResult(
        uid=uid,
        found=True,
        client_record=client_record,
        message=f"Client record retrieved for uid `{uid}`.",
    )


# TODO: add function tool decorator
@function_tool
def salesforce_client_db_set_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to create or update a client record in mock Salesforce storage."),
    ],
    client_data: Annotated[
        SalesforceClientRecord,
        Field(
            description="Structured client record matching the existing data/salesforce_clients.json schema.",
        ),
    ],
) -> SalesforceClientUpsertResult:
    """Create or update a Salesforce client record in the mock client database.

    Args:
        uid: UID key of the client record to create or update.
        client_data: Structured client payload matching the stored Salesforce client record format.

    Returns:
        SalesforceClientUpsertResult containing the validated record written to disk.
    """
    saved_record = set_salesforce_client(uid, client_data)
    return SalesforceClientUpsertResult(
        uid=uid,
        client_record=saved_record,
        message=f"Client record saved for uid `{uid}`.",
    )


# TODO: add function tool decorator
def salesforce_client_query_tool(
    uid: Annotated[
        str,
        Field(
            description="Lead UID used to check whether the lead already exists in the mock client database.",
        ),
    ],
) -> SalesforceClientQueryResult:
    """Check whether a Salesforce lead already exists as a client.

    Args:
        uid: UID key of the lead record to inspect.

    Returns:
        SalesforceClientQueryResult indicating whether the lead exists and whether a client shares the same first name, last name, and email.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceClientQueryResult(
            uid=uid,
            found=False,
            is_existing_client=False,
            matching_client_uids=[],
            message=f"Lead record not found for uid `{uid}`.",
        )

    matching_client_uids = find_matching_salesforce_client_uids(uid)
    if not matching_client_uids:
        return SalesforceClientQueryResult(
            uid=uid,
            found=True,
            is_existing_client=False,
            matching_client_uids=[],
            message=f"No matching client found for uid `{uid}`.",
        )

    return SalesforceClientQueryResult(
        uid=uid,
        found=True,
        is_existing_client=True,
        matching_client_uids=matching_client_uids,
        message=f"Matching client(s) found for uid `{uid}`: {', '.join(matching_client_uids)}.",
    )


# TODO: add function tool decorator
def salesforce_client_information_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to retrieve Form 1500 information from mock Salesforce storage."),
    ],
) -> SalesforceClientInformationResult:
    """Retrieve Form 1500 information for a Salesforce lead.

    Args:
        uid: UID key of the lead record to inspect.

    Returns:
        SalesforceClientInformationResult indicating whether the lead was found and, when present, the Form 1500 payload and basic completion details.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceClientInformationResult(
            uid=uid,
            found=False,
            form_1500=None,
            is_form_1500_complete=False,
            missing_fields=[],
            message=f"Lead record not found for uid `{uid}`.",
        )

    missing_fields = get_missing_form_1500_fields(lead_record.form_1500)
    return SalesforceClientInformationResult(
        uid=uid,
        found=True,
        form_1500=lead_record.form_1500,
        is_form_1500_complete=not missing_fields,
        missing_fields=missing_fields,
        message=f"Form 1500 information retrieved for uid `{uid}`.",
    )


# TODO: add function tool decorator
def salesforce_lead_db_get_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to retrieve a lead record from mock Salesforce storage."),
    ],
) -> SalesforceLeadLookupResult:
    """Retrieve a Salesforce lead record from the mock lead database.

    Args:
        uid: UID key of the lead record to retrieve.

    Returns:
        SalesforceLeadLookupResult indicating whether a record was found and, when present, the structured lead payload.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceLeadLookupResult(
            uid=uid,
            found=False,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    return SalesforceLeadLookupResult(
        uid=uid,
        found=True,
        lead_record=lead_record,
        message=f"Lead record retrieved for uid `{uid}`.",
    )


# TODO: add function tool decorator
@function_tool
def salesforce_lead_retrieval_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to retrieve all current lead information from mock Salesforce storage."),
    ],
) -> SalesforceLeadLookupResult:
    """Retrieve all current information for a Salesforce lead.

    Args:
        uid: UID key of the lead record to retrieve.

    Returns:
        SalesforceLeadLookupResult indicating whether a record was found and, when present, the structured lead payload.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceLeadLookupResult(
            uid=uid,
            found=False,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    return SalesforceLeadLookupResult(
        uid=uid,
        found=True,
        lead_record=lead_record,
        message=f"Lead record retrieved for uid `{uid}`.",
    )


# TODO: add function tool decorator
def salesforce_lead_db_set_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to create or update a lead record in mock Salesforce storage."),
    ],
    lead_data: Annotated[
        SalesforceLeadRecord,
        Field(description="Structured lead record matching data/salesforce_leads.json."),
    ],
) -> SalesforceLeadUpsertResult:
    """Create or update a Salesforce lead record in the mock lead database.

    Args:
        uid: UID key of the lead record to create or update.
        lead_data: Structured lead payload matching the stored lead record format.

    Returns:
        SalesforceLeadUpsertResult containing the validated record written to disk.
    """
    saved_record = set_salesforce_lead(uid, lead_data)
    return SalesforceLeadUpsertResult(
        uid=uid,
        lead_record=saved_record,
        message=f"Lead record saved for uid `{uid}`.",
    )


# TODO: add function tool decorator
def salesforce_lead_status_update_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to update a lead status in mock Salesforce storage."),
    ],
    updated_label: Annotated[
        LEAD_STATUS_UPDATE,
        Field(
            description="Updated lead status. Valid values are Working and Qualified.",
        ),
    ],
) -> SalesforceLeadStatusUpdateResult:
    """Update the status of a Salesforce lead.

    Args:
        uid: UID key of the lead record to update.
        updated_label: New lead status label to write.

    Returns:
        SalesforceLeadStatusUpdateResult indicating whether the lead was found and, when present, the updated lead payload.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceLeadStatusUpdateResult(
            uid=uid,
            found=False,
            previous_status=None,
            updated_status=None,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    updated_record = update_salesforce_lead_status(uid, updated_label)
    if updated_record is None:
        return SalesforceLeadStatusUpdateResult(
            uid=uid,
            found=False,
            previous_status=None,
            updated_status=None,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    return SalesforceLeadStatusUpdateResult(
        uid=uid,
        found=True,
        previous_status=lead_record.lead_status,
        updated_status=updated_record.lead_status,
        lead_record=updated_record,
        message=f"Lead status updated for uid `{uid}` to `{updated_label}`.",
    )


# TODO: add function tool decorator
def salesforce_client_input_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to apply structured status or Form 1500 updates to a lead."),
    ],
    client_input: Annotated[
        SalesforceClientInputPayload,
        Field(
            description="Structured partial update containing an optional lead status, person status, and/or Form 1500 field updates.",
        ),
    ],
) -> SalesforceClientInputResult:
    """Apply structured client-response updates to a Salesforce lead record.

    Args:
        uid: UID key of the lead record to update.
        client_input: Partial lead update containing a lead status, person status, and/or Form 1500 fields.

    Returns:
        SalesforceClientInputResult indicating whether the lead was found and, when present, the updated lead payload.
    """
    return apply_salesforce_client_input(uid, client_input)


# TODO: add function tool decorator
def meeting_scheduler_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to schedule a meeting in mock Salesforce storage."),
    ],
    start_time: Annotated[
        datetime,
        Field(description="Meeting start datetime in UTC."),
    ],
    end_time: Annotated[
        datetime,
        Field(description="Meeting end datetime in UTC."),
    ],
) -> SalesforceMeetingScheduleResult:
    """Schedule a meeting for a Salesforce lead.

    Args:
        uid: UID key of the lead record to update.
        start_time: Meeting start datetime in UTC.
        end_time: Meeting end datetime in UTC.

    Returns:
        SalesforceMeetingScheduleResult indicating whether the lead was found and, when present, the scheduled meeting and updated lead payload.
    """
    return schedule_salesforce_meeting(uid, start_time, end_time)


# TODO: add function tool decorator
def salesforce_document_uploader_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to append uploaded document paths in mock Salesforce storage."),
    ],
    document_paths: Annotated[
        str | list[str],
        Field(description="A single document path or list of document paths to append to the lead record."),
    ],
) -> SalesforceDocumentUploadResult:
    """Upload one or more documents to Salesforce for a lead.

    Args:
        uid: UID key of the lead record to update.
        document_paths: One document path or a list of document paths to append.

    Returns:
        SalesforceDocumentUploadResult indicating whether the lead was found and, when present, the updated lead payload.
    """
    return upload_salesforce_documents(uid, document_paths)


# TODO: add function tool decorator
def salesforce_lead_query_tool(
    uid: Annotated[
        str,
        Field(description="UID key used to check a lead for duplicates in mock Salesforce storage."),
    ],
) -> SalesforceLeadDuplicateQueryResult:
    """Check whether a Salesforce lead is a duplicate of another lead.

    Args:
        uid: UID key of the lead record to inspect.

    Returns:
        SalesforceLeadDuplicateQueryResult indicating whether the lead exists and whether another lead shares the same first name, last name, and email.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceLeadDuplicateQueryResult(
            uid=uid,
            found=False,
            is_duplicate=False,
            duplicate_uids=[],
            message=f"Lead record not found for uid `{uid}`.",
        )

    duplicate_uids = find_duplicate_salesforce_lead_uids(uid)
    if not duplicate_uids:
        return SalesforceLeadDuplicateQueryResult(
            uid=uid,
            found=True,
            is_duplicate=False,
            duplicate_uids=[],
            message=f"No duplicate leads found for uid `{uid}`.",
        )

    return SalesforceLeadDuplicateQueryResult(
        uid=uid,
        found=True,
        is_duplicate=True,
        duplicate_uids=duplicate_uids,
        message=f"Duplicate lead(s) found for uid `{uid}`: {', '.join(duplicate_uids)}.",
    )


# TODO: add function tool decorator
def salesforce_advisor_db_get_tool(
    advisor_id: Annotated[
        str,
        Field(description="Advisor id key used to retrieve a mock Salesforce advisor record."),
    ],
) -> SalesforceAdvisorLookupResult:
    """Retrieve a Salesforce advisor record from the mock advisor database.

    Args:
        advisor_id: Advisor id key of the advisor record to retrieve.

    Returns:
        SalesforceAdvisorLookupResult indicating whether a record was found and, when present, the structured advisor payload.
    """
    advisor_record = get_salesforce_advisor(advisor_id)
    if advisor_record is None:
        return SalesforceAdvisorLookupResult(
            advisor_id=advisor_id,
            found=False,
            advisor_record=None,
            message=f"Advisor record not found for advisor_id `{advisor_id}`.",
        )

    return SalesforceAdvisorLookupResult(
        advisor_id=advisor_id,
        found=True,
        advisor_record=advisor_record,
        message=f"Advisor record retrieved for advisor_id `{advisor_id}`.",
    )


# TODO: add function tool decorator
def salesforce_advisor_search_tool(
    state: Annotated[
        str,
        Field(
            description="Two-letter state code used to search mock Salesforce advisors by geography. Pass `remote` to force the remote-advisor fallback when no client location is available.",
        ),
    ],
) -> SalesforceAdvisorSearchResult:
    """Search for advisors by state, with a remote fallback when there is no match.

    Args:
        state: Two-letter state code to search for.

    Returns:
        SalesforceAdvisorSearchResult containing all matching advisors, or all remote advisors when there is no state match.
    """
    advisor_records, used_remote_fallback, no_region_based_matches = (
        search_salesforce_advisors_by_state(state)
    )
    if not advisor_records:
        if state.strip().lower() == "remote":
            return SalesforceAdvisorSearchResult(
                state=state,
                found=False,
                used_remote_fallback=used_remote_fallback,
                no_region_based_matches=no_region_based_matches,
                advisor_records=[],
                message="No remote advisors are available.",
            )
        return SalesforceAdvisorSearchResult(
            state=state,
            found=False,
            used_remote_fallback=used_remote_fallback,
            no_region_based_matches=no_region_based_matches,
            advisor_records=[],
            message=f"No advisors found for state `{state}` and no remote fallback advisors are available.",
        )

    if used_remote_fallback:
        if state.strip().lower() == "remote":
            return SalesforceAdvisorSearchResult(
                state=state,
                found=True,
                used_remote_fallback=True,
                no_region_based_matches=no_region_based_matches,
                advisor_records=advisor_records,
                message="No client location was available. Returned remote advisors.",
            )
        return SalesforceAdvisorSearchResult(
            state=state,
            found=True,
            used_remote_fallback=True,
            no_region_based_matches=no_region_based_matches,
            advisor_records=advisor_records,
            message=f"No advisors found for state `{state}`. Returned remote advisors instead.",
        )

    return SalesforceAdvisorSearchResult(
        state=state,
        found=True,
        used_remote_fallback=False,
        no_region_based_matches=False,
        advisor_records=advisor_records,
        message=f"Advisor search returned {len(advisor_records)} advisor(s) for state `{state}`.",
    )


# TODO: add function tool decorator
def advisor_calendar_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to look up the assigned advisor and retrieve available calendar blocks."),
    ],
) -> SalesforceAdvisorCalendarResult:
    """Retrieve available meeting blocks for the advisor assigned to a lead.

    Args:
        uid: Lead UID used to find the assigned advisor record.

    Returns:
        SalesforceAdvisorCalendarResult indicating whether advisor availability was found and, when present, the available meeting blocks.
    """
    return get_salesforce_advisor_calendar(uid)


# TODO: add function tool decorator
def salesforce_advisor_assignment_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to assign an advisor in mock Salesforce storage."),
    ],
    advisor_id: Annotated[
        str,
        Field(description="Advisor id to assign to the lead."),
    ],
) -> SalesforceAdvisorAssignmentResult:
    """Assign an advisor to a lead.

    Args:
        uid: Lead UID to update.
        advisor_id: Advisor id to assign to the lead.

    Returns:
        SalesforceAdvisorAssignmentResult indicating whether the lead and advisor were found and, when successful, the updated lead payload.
    """
    lead_record = get_salesforce_lead(uid)
    if lead_record is None:
        return SalesforceAdvisorAssignmentResult(
            uid=uid,
            advisor_id=advisor_id,
            lead_found=False,
            advisor_found=False,
            lead_record=None,
            message=f"Lead record not found for uid `{uid}`.",
        )

    advisor_record = get_salesforce_advisor(advisor_id)
    if advisor_record is None:
        return SalesforceAdvisorAssignmentResult(
            uid=uid,
            advisor_id=advisor_id,
            lead_found=True,
            advisor_found=False,
            lead_record=None,
            message=f"Advisor record not found for advisor_id `{advisor_id}`.",
        )

    updated_record = assign_salesforce_advisor_to_lead(uid, advisor_id)
    if updated_record is None:
        return SalesforceAdvisorAssignmentResult(
            uid=uid,
            advisor_id=advisor_id,
            lead_found=True,
            advisor_found=True,
            lead_record=None,
            message=f"Advisor assignment failed for uid `{uid}` and advisor_id `{advisor_id}`.",
        )

    return SalesforceAdvisorAssignmentResult(
        uid=uid,
        advisor_id=advisor_id,
        lead_found=True,
        advisor_found=True,
        lead_record=updated_record,
        message=f"Assigned advisor `{advisor_record.advisor_name}` to uid `{uid}`.",
    )


# TODO: add function tool decorator
@function_tool
def salesforce_delete_lead_tool(
    uid: Annotated[
        str,
        Field(description="Lead UID used to delete a lead from mock Salesforce storage."),
    ],
) -> SalesforceLeadDeleteResult:
    """Delete a Salesforce lead.

    Args:
        uid: Lead UID to delete.

    Returns:
        SalesforceLeadDeleteResult indicating whether the lead was found and deleted.
    """
    deleted = delete_salesforce_lead(uid)
    if not deleted:
        return SalesforceLeadDeleteResult(
            uid=uid,
            found=False,
            deleted=False,
            message=f"Lead record not found for uid `{uid}`.",
        )

    return SalesforceLeadDeleteResult(
        uid=uid,
        found=True,
        deleted=True,
        message=f"Lead record deleted for uid `{uid}`.",
    )


salesforce_lead_delete_tool = salesforce_delete_lead_tool


# TODO: add function tool decorator
def salesforce_advisor_db_set_tool(
    advisor_id: Annotated[
        str,
        Field(description="Advisor id key used to create or update a mock Salesforce advisor record."),
    ],
    advisor_data: Annotated[
        SalesforceAdvisorRecord,
        Field(description="Structured advisor record matching data/salesforce_advisors.json."),
    ],
) -> SalesforceAdvisorUpsertResult:
    """Create or update a Salesforce advisor record in the mock advisor database.

    Args:
        advisor_id: Advisor id key of the advisor record to create or update.
        advisor_data: Structured advisor payload matching the stored advisor record format.

    Returns:
        SalesforceAdvisorUpsertResult containing the validated record written to disk.
    """
    saved_record = set_salesforce_advisor(advisor_id, advisor_data)
    return SalesforceAdvisorUpsertResult(
        advisor_id=advisor_id,
        advisor_record=saved_record,
        message=f"Advisor record saved for advisor_id `{advisor_id}`.",
    )


# TODO: add function tool decorator
def salesforce_notification_db_get_tool(
    notification_id: Annotated[
        str,
        Field(description="Notification id key used to retrieve a mock Salesforce notification record."),
    ],
) -> SalesforceNotificationLookupResult:
    """Retrieve a Salesforce notification record from the mock notification database.

    Args:
        notification_id: Notification id key of the notification record to retrieve.

    Returns:
        SalesforceNotificationLookupResult indicating whether a record was found and, when present, the structured notification payload.
    """
    notification_record = get_salesforce_notification(notification_id)
    if notification_record is None:
        return SalesforceNotificationLookupResult(
            notification_id=notification_id,
            found=False,
            notification_record=None,
            message=f"Notification record not found for notification_id `{notification_id}`.",
        )

    return SalesforceNotificationLookupResult(
        notification_id=notification_id,
        found=True,
        notification_record=notification_record,
        message=f"Notification record retrieved for notification_id `{notification_id}`.",
    )


# TODO: add function tool decorator
def salesforce_notification_db_set_tool(
    notification_id: Annotated[
        str,
        Field(description="Notification id key used to create or update a mock Salesforce notification record."),
    ],
    notification_data: Annotated[
        SalesforceNotificationRecord,
        Field(description="Structured notification record matching data/salesforce_notifications.json."),
    ],
) -> SalesforceNotificationUpsertResult:
    """Create or update a Salesforce notification record in the mock notification database.

    Args:
        notification_id: Notification id key of the notification record to create or update.
        notification_data: Structured notification payload matching the stored notification record format.

    Returns:
        SalesforceNotificationUpsertResult containing the validated record written to disk.
    """
    saved_record = set_salesforce_notification(notification_id, notification_data)
    return SalesforceNotificationUpsertResult(
        notification_id=notification_id,
        notification_record=saved_record,
        message=f"Notification record saved for notification_id `{notification_id}`.",
    )


__all__ = [
    "SALESFORCE_CLIENTS_DB_PATH",
    "SALESFORCE_LEADS_DB_PATH",
    "SALESFORCE_ADVISORS_DB_PATH",
    "SALESFORCE_NOTIFICATIONS_DB_PATH",
    "SalesforceAdvisorLookupResult",
    "SalesforceAdvisorAssignmentResult",
    "SalesforceAdvisorCalendarResult",
    "SalesforceAdvisorRecord",
    "SalesforceAdvisorSearchResult",
    "SalesforceAdvisorUpsertResult",
    "SalesforceClientForm1500",
    "SalesforceClientInputForm1500Update",
    "SalesforceClientInputPayload",
    "SalesforceClientInputResult",
    "SalesforceClientInformationResult",
    "SalesforceClientQueryResult",
    "SalesforceClientLookupResult",
    "SalesforceClientRecord",
    "SalesforceClientUpsertResult",
    "SalesforceLeadLookupResult",
    "SalesforceLeadDuplicateQueryResult",
    "SalesforceLeadDeleteResult",
    "SalesforceLeadRecord",
    "SalesforceLeadStatusUpdateResult",
    "SalesforceLeadUpsertResult",
    "SalesforceDocumentUploadResult",
    "SalesforceMeetingRecord",
    "SalesforceMeetingScheduleResult",
    "SalesforceNotificationLookupResult",
    "SalesforceNotificationRecord",
    "SalesforceNotificationUpsertResult",
    "get_salesforce_advisor",
    "get_salesforce_client",
    "get_salesforce_lead",
    "get_salesforce_notification",
    "get_missing_form_1500_fields",
    "apply_salesforce_client_input",
    "schedule_salesforce_meeting",
    "upload_salesforce_documents",
    "find_matching_salesforce_client_uids",
    "find_duplicate_salesforce_lead_uids",
    "assign_salesforce_advisor_to_lead",
    "get_salesforce_advisor_calendar",
    "search_salesforce_advisors_by_state",
    "delete_salesforce_lead",
    "update_salesforce_lead_status",
    "salesforce_delete_lead_tool",
    "meeting_scheduler_tool",
    "salesforce_document_uploader_tool",
    "advisor_calendar_tool",
    "salesforce_advisor_assignment_tool",
    "salesforce_advisor_db_get_tool",
    "salesforce_advisor_db_set_tool",
    "salesforce_advisor_search_tool",
    "salesforce_client_db_get_tool",
    "salesforce_client_db_set_tool",
    "salesforce_client_input_tool",
    "salesforce_client_information_tool",
    "salesforce_client_query_tool",
    "salesforce_lead_db_get_tool",
    "salesforce_lead_db_set_tool",
    "salesforce_lead_retrieval_tool",
    "salesforce_lead_delete_tool",
    "salesforce_lead_query_tool",
    "salesforce_lead_status_update_tool",
    "salesforce_notification_db_get_tool",
    "salesforce_notification_db_set_tool",
    "set_salesforce_advisor",
    "set_salesforce_client",
    "set_salesforce_lead",
    "set_salesforce_notification",
]
