# Data Guide

This folder is the local data model for the entire prototype. If you are new to the repo, the simplest mental model is:

1. `data/scenarios.json` defines ordered workflow events.
2. Those events point into mocked systems such as email, Salesforce, and Laserfiche.
3. Running the workflow mutates the active JSON files in this folder.
4. The `*_original.json` files are the reset baselines.

Nothing here is a live integration. The JSON files in `data/` are the system of mock records for local runs.

## Quick Orientation

The workflow operates on three event types:

- Salesforce `new_lead` notifications
- inbound client-response emails
- Salesforce `meeting_close` notifications

The `manager` agent receives one payload at a time, then routes to specialist agents:

- `lead_reviewer`: qualifies leads, checks duplicates/existing clients, updates lead status, and assigns advisors
- `response_ingestion`: reads inbound emails, processes attachments, updates Salesforce, schedules meetings, and routes documents
- `infotrack`: reviews missing information, advisor availability, and post-meeting Zocks follow-up

## Directory Map

| Path | Purpose | Mutable at runtime |
| --- | --- | --- |
| `scenarios.json` | Ordered scenario payloads used by the CLI | Yes |
| `emails.json` | Mock inbound email store keyed by `email_id` | Yes, though usually treated as seed data |
| `salesforce_leads.json` | Mock lead records keyed by `UID` | Yes |
| `salesforce_clients.json` | Mock client records keyed by `UID` | Yes |
| `salesforce_advisors.json` | Mock advisor directory and availability keyed by `advisor_id` | Yes, though usually stable |
| `salesforce_notifications.json` | Mock Salesforce notification metadata keyed by `notification_id` | Yes, though usually stable |
| `laserfiche.json` | Mock Laserfiche upload state keyed by `UID` | Yes |
| `sample_input/` | Synthetic PDF attachments used by scenarios | No, unless you add/replace fixtures |
| `cache/` | Cached OCR and compliance-classification results for attachments | Yes, generated |
| `*_original.json` | Reset baselines copied back into the active JSON files | No, unless you intentionally update the baseline |

## How The Data Fits Together

Typical flow:

```text
scenario payload
  -> UID
  -> email_id
  -> salesforce_notification_id

UID
  -> salesforce_leads.json
  -> salesforce_clients.json
  -> laserfiche.json
  -> meetings stored on lead/client records

email_id
  -> emails.json
  -> attachment paths in data/sample_input/
  -> derived OCR/classification cache in data/cache/

salesforce_notification_id
  -> salesforce_notifications.json

advisor_id
  -> salesforce_advisors.json

scenario_id
  -> shared label across scenarios, emails, and notifications
```

The most important join key is `UID`. That is the main cross-system identifier for people moving through the workflow.

## Core Identifiers

### `UID`

Primary person/workflow identifier. Used across:

- scenario payloads
- lead/client records
- inbound emails
- Laserfiche uploads
- meeting scheduling and meeting-close flows

Examples: `UID-2026-0201`, `UID-2026-0306`

### `email_id`

Lookup key inside `emails.json`.

Examples: `email_client_response_0201`, `email_client_response_0309`

### `salesforce_notification_id`

Lookup key inside `salesforce_notifications.json`.

Examples: `NOTIF-2026-0201`, `NOTIF-2026-0312`

### `advisor_id`

Lookup key inside `salesforce_advisors.json`.

Examples: `ADV-1001`, `ADV-1003`

### `scenario_id`

Convenience grouping label shared across scenarios, emails, and notifications. Useful for tracing where a seed record belongs, but not the main runtime routing key.

Examples: `e2e_test`, `scenario_15`, `off_topic`

### `meeting_id`

Sequential meeting identifier stored on lead records and also referenced in meeting-close payload notes.

Examples: `meeting_1`, `meeting_2`

## File-By-File Schemas

## `scenarios.json`

This file drives CLI scenario runs. It has two top-level sections:

- `payload_types`: metadata describing allowed payload shapes
- `scenarios`: ordered scenario definitions

High-level schema:

```json
{
  "payload_types": [
    {
      "payload_type": "salesforce_notification",
      "required_fields": ["UID", "salesforce_notification_id", "salesforce_trigger_type"],
      "salesforce_trigger_type_options": ["new_lead", "meeting_close"]
    },
    {
      "payload_type": "inbound_email",
      "required_fields": ["email_id"]
    }
  ],
  "scenarios": [
    {
      "id": "scenario_name",
      "description": "Human-readable description",
      "payloads": [
        {
          "payload_type": "salesforce_notification",
          "UID": "UID-2026-0201",
          "salesforce_notification_id": "NOTIF-2026-0201",
          "salesforce_trigger_type": "new_lead"
        },
        {
          "payload_type": "inbound_email",
          "UID": "UID-2026-0201",
          "email_id": "email_client_response_0201"
        },
        {
          "payload_type": "salesforce_notification",
          "UID": "UID-2026-0201",
          "salesforce_notification_id": "NOTIF-2026-0202",
          "salesforce_trigger_type": "meeting_close",
          "meeting_notes": {
            "meeting_id": "meeting_1",
            "zocks_summary": "Meeting summary text",
            "zocks_action_items": ["Follow-up item 1", "Follow-up item 2"]
          }
        }
      ]
    }
  ]
}
```

Important notes:

- `payloads` are processed in order.
- A single scenario can model a full end-to-end lifecycle by alternating notification and inbound-email payloads.
- For `meeting_close` payloads, the scenario payload itself carries the Zocks-style notes used to update the lead record.
- `salesforce_trigger_type` is a run payload field. It is not the same field as `notification_type` in `salesforce_notifications.json`.

## `emails.json`

This is the mocked inbound mailbox. The top-level structure is:

```json
{
  "emails_by_id": {
    "email_client_response_0201": {
      "...": "email record"
    }
  }
}
```

High-level email schema:

```json
{
  "id": "email_client_response_0201",
  "scenario_id": "e2e_test",
  "email_type": "Client Response",
  "thread_id": "thread_uid_2026_0201_intro",
  "UID": "UID-2026-0201",
  "uid": "UID-2026-0201",
  "from": {
    "name": "Client Name",
    "email": "client@example.com"
  },
  "to": [
    {
      "name": "Advisor Intake",
      "email": "advisor-intake@firm.example"
    }
  ],
  "cc": [],
  "subject": "Re: ...",
  "received_at": "2026-04-02T08:15:00-07:00",
  "body_text": "Full inbound body text",
  "attachments": [
    {
      "filename": "data/sample_input/Some_File.pdf",
      "content_type": "application/pdf",
      "summary": "Short description of the attachment"
    }
  ],
  "response_classification_expected": "scenario_1"
}
```

Important notes:

- Both `UID` and `uid` appear in records for compatibility. Keep them aligned.
- `response_classification_expected` is a seed-data hint for the scenario. It is not a trusted system field.
- `attachments[].filename` should normally point to a file in `data/sample_input/`.
- `received_at` is stored with a timezone offset.
- Some emails are intentionally off-topic or contain unreadable/problematic attachments to exercise guardrails and partial-processing behavior.

## `salesforce_leads.json`

This is the main mutable workflow state store. It holds leads and prospect records keyed by `UID`.

High-level lead schema:

```json
{
  "UID-2026-0201": {
    "uid": "UID-2026-0201",
    "lead_status": "New",
    "person_status": "Lead",
    "advisor_name": null,
    "advisor_id": null,
    "first_name": "Amelia",
    "last_name": "Carter",
    "email": "amelia.carter@example.com",
    "form_1500": { "...": "see shared form schema below" },
    "meetings": null,
    "document": [
      "/absolute/or/relative/path/to/uploaded/non-compliance-document.pdf"
    ]
  }
}
```

Field behavior:

- `lead_status` is typically one of `New`, `Working`, or `Qualified`.
- `person_status` is typically `Lead`, `Prospect`, or `Prospective Buyer`.
- `advisor_name` and `advisor_id` are usually filled in after lead review.
- `meetings` starts as `null` and becomes a list of meeting records once meetings are scheduled.
- `document` is optional and appears after uploads through the mocked Salesforce document uploader.

This file is the one most likely to change during a run:

- status updates
- advisor assignment
- Form 1500 merges
- meeting creation
- Zocks note updates on meetings
- non-compliance document upload paths

## `salesforce_clients.json`

This stores existing-client records keyed by `UID`. It uses the same shared person/Form 1500 structure as leads, but it does not have lead workflow fields like `lead_status` or `person_status`.

High-level client schema:

```json
{
  "UID-2026-0001": {
    "uid": "UID-2026-0001",
    "advisor_name": null,
    "advisor_id": null,
    "first_name": "Jordan",
    "last_name": "Lee",
    "email": "jordan.lee@example.com",
    "form_1500": { "...": "see shared form schema below" },
    "meetings": null
  }
}
```

This file is mainly used to:

- identify whether a new lead is already an existing client
- provide a client-side analog to lead records

## Shared `form_1500` Schema

The same nested structure is used inside both lead and client records.

High-level schema:

```json
{
  "first_name": "Amelia",
  "last_name": "Carter",
  "date_of_birth": "1994-08-17",
  "marital_status": "Single",
  "email": "amelia.carter@example.com",
  "mobile_phone": "555-0311",
  "city": "Phoenix",
  "state": "AZ",
  "service_affiliation": "Veteran",
  "branch_of_service": "Air Force",
  "military_status": "Veteran",
  "rank_or_pay_grade": "O-3",
  "projected_retirement_date": null,
  "spouse_name": null,
  "dependents_count": 0,
  "primary_goal": "Retirement planning",
  "annual_household_income": 138000,
  "monthly_expenses": 6100,
  "liquid_cash": 28000,
  "retirement_account_balance": 92000,
  "total_debt_balance": 19000,
  "risk_tolerance": "Moderate",
  "life_insurance_coverage": 250000,
  "estate_documents_in_place": false,
  "planning_notes": "Free-text planning context"
}
```

Notes:

- This schema is intentionally broad. Many fields may be `null` on first contact.
- Response ingestion can merge partial updates from inbound emails and extracted documents.
- `first_name`, `last_name`, and `email` are duplicated at both the top level and inside `form_1500`.

## Shared `meetings` Schema

When meetings are scheduled, records use this shape:

```json
[
  {
    "start_time": "2026-04-09T20:00:00Z",
    "end_time": "2026-04-09T21:00:00Z",
    "meeting_id": "meeting_1",
    "zocks_summary": "Optional summary after the meeting closes",
    "zocks_action_items": [
      "Optional follow-up action",
      "Another follow-up action"
    ]
  }
]
```

Notes:

- Times are stored in UTC.
- `zocks_summary` and `zocks_action_items` may be `null` until a meeting-close event updates them.
- `meeting_id` is sequential per lead.

## `salesforce_advisors.json`

This file stores advisor routing targets keyed by `advisor_id`.

High-level schema:

```json
{
  "ADV-1001": {
    "advisor_id": "ADV-1001",
    "advisor_name": "Alex Morgan",
    "skills": [
      "retirement_planning",
      "military_benefits",
      "portfolio_review"
    ],
    "branch_type": "remote",
    "state": "AZ",
    "available_blocks": [
      "2026-04-07T16:00:00Z",
      "2026-04-07T18:00:00Z"
    ]
  }
}
```

Notes:

- `skills` is used for best-fit advisor selection.
- `state` is the advisor coverage state, usually a two-letter USPS code.
- `branch_type` is used in routing decisions. Current examples include `remote` and `in_person`.
- `available_blocks` is the calendar source for proposed meeting times and is stored in UTC.

## `salesforce_notifications.json`

This file stores mock Salesforce notification metadata keyed by `notification_id`.

High-level schema:

```json
{
  "NOTIF-2026-0201": {
    "notification_id": "NOTIF-2026-0201",
    "scenario_id": "e2e_test",
    "notification_type": "new_lead_creation",
    "first_name": "Amelia",
    "last_name": "Carter",
    "email": "amelia.carter@example.com",
    "description": "New lead created from intake workflow."
  }
}
```

Notes:

- This is metadata for the mocked notification system, not the canonical run payload schema.
- The scenario payload field is `salesforce_trigger_type` with values like `new_lead` and `meeting_close`.
- The notification record field is `notification_type` with values like `new_lead_creation` and `meeting_close`.
- Meeting-close scenario payloads may include rich `meeting_notes`, but the notification metadata here is intentionally lightweight.

## `laserfiche.json`

This file is the mocked compliance-document repository. Its shape is intentionally simple:

```json
{
  "metadata": {
    "version": "1.0",
    "description": "Mock Laserfiche repository for compliance uploads."
  },
  "UID-2026-0201": [
    "data/sample_input/Amelia_Carter_Driver_License.pdf"
  ]
}
```

Notes:

- Each dynamic top-level UID maps directly to a list of uploaded attachment paths.
- The Laserfiche mock does not store rich document metadata, only the attachment paths.
- Compliance-relevant documents should end up here, not in the Salesforce `document` list.

## `cache/`

This folder stores generated OCR/classification cache files for attachments processed by `tools/document_processor.py`.

Typical cache schema:

```json
{
  "path": "data/sample_input/Amelia_Carter_Driver_License.pdf",
  "extension": "pdf",
  "result": {
    "path": "data/sample_input/Amelia_Carter_Driver_License.pdf",
    "extension": "pdf",
    "content": "Extracted OCR text and summary",
    "compliance_related": true,
    "compliance_confidence": 0.93,
    "justification": "Why the document was classified this way"
  },
  "compliance_related": true,
  "compliance_confidence": 0.93,
  "justification": "Why the document was classified this way",
  "cached_at": "2026-04-01T23:50:24.685927Z"
}
```

Notes:

- Cache filenames are derived from normalized attachment filenames.
- Older cache files may omit some newer fields such as `compliance_confidence`; the loader is backward compatible.
- These files are generated artifacts and can be regenerated by rerunning document-processing scenarios.

## `sample_input/`

This folder holds the synthetic attachment fixtures referenced by inbound emails.

Current fixture categories include:

- identity documents: driver's licenses and ID cards
- household budget worksheets
- account summaries and retirement balance sheets
- beneficiary worksheet examples
- intentionally corrupted/unreadable files
- malicious or prompt-injection-style attachments for guardrail testing

These files are referenced by `emails.json` attachment paths and are the source material for `data/cache/`.

## Active Files vs Baselines

The active top-level JSON files are:

- `scenarios.json`
- `emails.json`
- `salesforce_leads.json`
- `salesforce_clients.json`
- `salesforce_advisors.json`
- `salesforce_notifications.json`
- `laserfiche.json`

Each has a sibling baseline:

- `scenarios_original.json`
- `emails_original.json`
- `salesforce_leads_original.json`
- `salesforce_clients_original.json`
- `salesforce_advisors_original.json`
- `salesforce_notifications_original.json`
- `laserfiche_original.json`

Reset behavior:

- `main.py` restores the active top-level JSON files from the `*_original.json` baselines at startup.
- `api.py` imports `main.py`, so starting the API also triggers that restore.
- `scripts/reset_runtime_data.py` performs the same restore explicitly.
- `main.py --save-runtime-data` copies the current active JSON files back into their `*_original.json` siblings.

Practical rule:

- If you want a change to survive the next reset, update the baseline too.
- If you only edit the active file, your change is temporary.

## Common Mutation Patterns

During a normal run, expect these changes:

- `salesforce_leads.json`
  - `lead_status` changes from `New` to `Working` to `Qualified`
  - `advisor_id` and `advisor_name` are assigned
  - `form_1500` fields are merged from email/document input
  - `meetings` are appended
  - `document` upload paths are appended
- `laserfiche.json`
  - compliance-related attachment paths are appended under the `UID`
- `cache/`
  - OCR/classification outputs are created or refreshed

Usually unchanged unless you intentionally edit them:

- `salesforce_clients.json`
- `salesforce_advisors.json`
- `salesforce_notifications.json`
- `emails.json`

## Adding Or Updating Scenario Data

When you add a new scenario, the clean path is:

1. Add or choose a `UID` in `salesforce_leads.json` or `salesforce_clients.json`, depending on the use case.
2. Add any needed notification metadata to `salesforce_notifications.json`.
3. Add any needed inbound email records to `emails.json`.
4. Add any new attachment PDFs to `sample_input/`.
5. Add the ordered payload sequence to `scenarios.json`.
6. Run the scenario.
7. If the resulting state is the new intended baseline, save it back to the `*_original.json` files.

For document-heavy scenarios:

1. Add the attachment file under `sample_input/`.
2. Reference it from `emails.json`.
3. Let the document processor build the corresponding cache file during the first run.

## Common Gotchas

- `UID` is the main join key. If it is wrong or inconsistent, the workflow will feel broken everywhere.
- `UID` and `uid` in email records should match.
- `salesforce_trigger_type` in scenario payloads is not the same field as `notification_type` in notification metadata.
- `available_blocks` and stored meeting times are UTC strings, while inbound email text may refer to local timezones.
- The active JSON files may already contain mutated runtime state from a previous run. Reset before debugging data issues.
- If you forget to update `*_original.json`, your scenario edits will disappear on the next restore.
- Attachment paths should be exact whenever possible. The document processor does attempt some path normalization, but you should not rely on that as your primary workflow.
