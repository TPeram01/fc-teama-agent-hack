from __future__ import annotations

import ast
import json
import re
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


TRACES_DIR = Path("traces_logs")
SPECIALIST_AGENT_TO_LABEL: dict[str, str] = {
    "lead_reviewer_agent": "Lead Reviewer Agent",
    "response_ingestion_agent": "Response Ingestion Agent",
    "infotrack_agent": "InfoTrack Agent",
}
SYSTEM_EVENT_LABELS: dict[str, str] = {
    "run_started": "Run Started",
    "run_completed": "Run Completed",
    "run_failed": "Run Failed",
    "scenario_started": "Scenario Started",
    "scenario_completed": "Scenario Completed",
    "meeting_notes_applied": "Meeting Notes Synced",
}
SYSTEM_EVENT_EMOJI: dict[str, str] = {
    "run_started": "🚀",
    "run_completed": "✅",
    "run_failed": "❌",
    "scenario_started": "🎬",
    "scenario_completed": "🏁",
    "meeting_notes_applied": "📝",
}
TOOL_EMOJI: dict[str, str] = {
    "email_read_tool": "📥",
    "send_email_tool": "📤",
    "advisor_calendar_tool": "📅",
    "meeting_scheduler_tool": "🗓️",
    "salesforce_client_information_tool": "🧾",
    "salesforce_client_input_tool": "🧾",
    "salesforce_document_uploader_tool": "📎",
    "laserfiche_uploader_tool": "🗄️",
    "document_processor_tool": "📄",
    "zocks_reviewer_tool": "📝",
    "ask_human_input_tool": "🧑‍⚖️",
}


class TimelineDetailItem(BaseModel):
    """Structured content shown in the timeline drawer."""

    label: str
    format: Literal["text", "json"] = "text"
    value: str | dict[str, Any] | list[Any] | None = None


class TimelineAttachment(BaseModel):
    """File reference shown inline with a timeline entry."""

    label: str
    path: str


class TimelineEntry(BaseModel):
    """Enriched record displayed in the workflow timeline."""

    id: str
    kind: Literal["system", "payload", "agent", "tool", "approval"]
    event_type: str | None = None
    timestamp: datetime | None = None
    title: str
    summary: str
    body: str | None = None
    actor: str | None = None
    status: str | None = None
    emoji: str | None = None
    is_pending_details: bool = False
    payload_index: int | None = None
    payload_label: str | None = None
    badge: str | None = None
    attachments: list[TimelineAttachment] = Field(default_factory=list)
    detail_items: list[TimelineDetailItem] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class PayloadContext(BaseModel):
    """Runtime payload context used to enrich narrative entries."""

    index: int
    payload: dict[str, Any]
    manager_output: dict[str, Any] | None = None


class TraceRegistry:
    """Queues trace spans so runtime events can be enriched in order."""

    def __init__(self, spans: list[dict[str, Any]]) -> None:
        span_lookup = {str(span.get("id")): span for span in spans}
        self.specialist_spans: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self.tool_spans_by_key: dict[tuple[str | None, str], deque[dict[str, Any]]] = defaultdict(deque)
        self.tool_spans_by_name: dict[str, deque[dict[str, Any]]] = defaultdict(deque)

        for span in spans:
            span_data = span.get("span_data")
            if not isinstance(span_data, dict):
                continue
            if str(span_data.get("type") or "") != "function":
                continue

            name = span_data.get("name")
            if not isinstance(name, str) or not name:
                continue

            if name in SPECIALIST_AGENT_TO_LABEL:
                self.specialist_spans[SPECIALIST_AGENT_TO_LABEL[name]].append(span)
                continue

            actor = _find_ancestor_agent_name(span, span_lookup)
            self.tool_spans_by_key[(actor, name)].append(span)
            self.tool_spans_by_name[name].append(span)

    def consume_specialist(self, agent_name: str | None) -> dict[str, Any] | None:
        if not isinstance(agent_name, str) or not agent_name:
            return None
        queue = self.specialist_spans.get(agent_name)
        if queue:
            return queue.popleft()
        return None

    def consume_tool(
        self,
        agent_name: str | None,
        tool_name: str | None,
    ) -> dict[str, Any] | None:
        if not isinstance(tool_name, str) or not tool_name:
            return None
        queue = self.tool_spans_by_key.get((agent_name, tool_name))
        if queue:
            return queue.popleft()
        fallback = self.tool_spans_by_name.get(tool_name)
        if fallback:
            return fallback.popleft()
        return None


def build_run_timeline(snapshot: dict[str, Any]) -> list[TimelineEntry]:
    """Build a chat-like timeline from runtime events and saved trace bundles."""

    events = [event for event in snapshot.get("events") or [] if isinstance(event, dict)]
    payload_contexts = _build_payload_contexts(snapshot)
    trace_registry = TraceRegistry(_load_trace_spans(snapshot.get("trace_id")))

    entries: list[TimelineEntry] = []
    current_payload_index: int | None = None
    specialist_result_summaries: dict[int, str] = {}
    pending_specialist_end_events: dict[str, tuple[dict[str, Any], int | None, PayloadContext | None]] = {}
    specialist_start_entry_indexes: dict[str, deque[int]] = defaultdict(deque)

    for event in events:
        event_type = str(event.get("type") or "unknown")

        if event_type == "payload_started":
            payload_index = _coerce_int(event.get("payload_index"))
            if payload_index is None:
                continue
            current_payload_index = payload_index
            context = payload_contexts.get(payload_index)
            if context is None:
                continue
            entries.append(_build_payload_notification(event, context))
            continue

        if event_type == "payload_completed":
            continue

        if event_type in SYSTEM_EVENT_LABELS:
            entries.append(_build_system_entry(event, current_payload_index))
            continue

        if event_type == "approval_requested":
            entries.append(_build_approval_requested_entry(event, current_payload_index))
            continue

        if event_type in {"approval_resolved", "approval_cancelled"}:
            entries.append(_build_approval_resolution_entry(event, current_payload_index))
            continue

        if event_type == "agent_start":
            entry = _build_agent_status_entry(event, current_payload_index, started=True)
            entries.append(entry)
            if entry.title in SPECIALIST_AGENT_TO_LABEL.values():
                specialist_start_entry_indexes[entry.title].append(len(entries) - 1)
            continue

        if event_type == "agent_end":
            payload_context = payload_contexts.get(current_payload_index)
            agent_name = str(event.get("agent_name") or "Agent")
            if agent_name in SPECIALIST_AGENT_TO_LABEL.values():
                pending_specialist_end_events[agent_name] = (
                    event,
                    current_payload_index,
                    payload_context,
                )
                continue
            entries.append(_build_agent_status_entry(event, current_payload_index, started=False, payload_context=payload_context))
            continue

        if event_type == "tool_start":
            tool_name = str(event.get("tool_name") or "")
            agent_name = event.get("agent_name") if isinstance(event.get("agent_name"), str) else None
            payload_context = payload_contexts.get(current_payload_index)

            if tool_name == "ask_human_input_tool":
                continue

            if tool_name in SPECIALIST_AGENT_TO_LABEL:
                previous_summary = specialist_result_summaries.get(current_payload_index or 0)
                entries.append(
                    _build_manager_call_entry(
                        tool_name=tool_name,
                        payload_context=payload_context,
                        payload_index=current_payload_index,
                        event=event,
                        previous_specialist_summary=previous_summary,
                    )
                )
                continue

            continue

        if event_type == "tool_end":
            tool_name = str(event.get("tool_name") or "")
            agent_name = event.get("agent_name") if isinstance(event.get("agent_name"), str) else None
            payload_context = payload_contexts.get(current_payload_index)

            if tool_name == "ask_human_input_tool":
                continue

            if tool_name in SPECIALIST_AGENT_TO_LABEL:
                trace_span = trace_registry.consume_specialist(SPECIALIST_AGENT_TO_LABEL[tool_name])
                entry = _build_specialist_result_entry(
                    tool_name=tool_name,
                    payload_context=payload_context,
                    payload_index=current_payload_index,
                    trace_span=trace_span,
                    event=event,
                )
                specialist_label = SPECIALIST_AGENT_TO_LABEL[tool_name]
                start_indexes = specialist_start_entry_indexes.get(specialist_label)
                start_index = start_indexes.popleft() if start_indexes else None
                if start_index is not None:
                    _merge_specialist_result_into_start(entries[start_index], entry)
                else:
                    entries.append(entry)
                if current_payload_index is not None:
                    specialist_result_summaries[current_payload_index] = entry.summary
                pending_agent_end = pending_specialist_end_events.pop(
                    specialist_label,
                    None,
                )
                if pending_agent_end is not None and start_index is None:
                    end_event, end_payload_index, end_payload_context = pending_agent_end
                    entries.append(
                        _build_agent_status_entry(
                            end_event,
                            end_payload_index,
                            started=False,
                            payload_context=end_payload_context,
                        )
                    )
                continue

            trace_span = trace_registry.consume_tool(agent_name, tool_name)
            entries.append(
                _build_tool_result_entry(
                    tool_name=tool_name,
                    agent_name=agent_name,
                    payload_index=current_payload_index,
                    trace_span=trace_span,
                    event=event,
                )
            )

    for end_event, end_payload_index, end_payload_context in pending_specialist_end_events.values():
        entries.append(
            _build_agent_status_entry(
                end_event,
                end_payload_index,
                started=False,
                payload_context=end_payload_context,
            )
        )

    return entries


def _build_payload_contexts(snapshot: dict[str, Any]) -> dict[int, PayloadContext]:
    input_payloads = [
        payload for payload in snapshot.get("input_payloads") or [] if isinstance(payload, dict)
    ]
    manager_outputs = _extract_manager_outputs(snapshot)
    return {
        index: PayloadContext(
            index=index,
            payload=payload,
            manager_output=manager_outputs.get(index),
        )
        for index, payload in enumerate(input_payloads, start=1)
    }


def _extract_manager_outputs(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result = snapshot.get("result")
    if not isinstance(result, dict):
        return {}

    payload_results = result.get("payload_results")
    if isinstance(payload_results, list):
        outputs: dict[int, dict[str, Any]] = {}
        for item in payload_results:
            if not isinstance(item, dict):
                continue
            payload_index = item.get("payload_index")
            manager_output = item.get("manager_output")
            if isinstance(payload_index, int) and isinstance(manager_output, dict):
                outputs[payload_index] = manager_output
        return outputs

    manager_output = result.get("manager_output")
    if isinstance(manager_output, dict):
        return {1: manager_output}
    return {}


def _build_payload_notification(
    event: dict[str, Any],
    context: PayloadContext,
) -> TimelineEntry:
    label, body = _payload_notification_text(context.payload)
    return TimelineEntry(
        id=f"payload-start-{context.index}",
        kind="payload",
        event_type="payload_started",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=label,
        summary=label,
        body=body,
        status=None,
        emoji=_payload_emoji(context.payload),
        payload_index=context.index,
        payload_label=f"Payload {context.index}",
        badge=str(context.payload.get("payload_type") or "payload"),
        detail_items=[TimelineDetailItem(label="Payload", format="json", value=context.payload)],
        raw=event,
    )


def _payload_notification_text(payload: dict[str, Any]) -> tuple[str, str | None]:
    payload_type = str(payload.get("payload_type") or "unknown")
    uid = payload.get("UID")

    if payload_type == "inbound_email":
        email_id = payload.get("email_id")
        title = "New Email Notification"
        body = f"Email ID: {email_id}" if email_id else "Incoming client email received."
        return title, body

    trigger = str(payload.get("salesforce_trigger_type") or "")
    if payload_type == "salesforce_notification":
        if trigger == "new_lead":
            title = "New Salesforce Notification / New Lead"
        elif trigger == "meeting_close":
            title = "New Salesforce Notification / Meeting Close"
        else:
            title = "New Salesforce Notification"
        body = f"UID: {uid}" if uid else None
        return title, body

    return "New Workflow Notification", None


def _payload_emoji(payload: dict[str, Any]) -> str:
    if str(payload.get("payload_type") or "") == "inbound_email":
        return "🔔"
    return "🔔"


def _build_system_entry(event: dict[str, Any], payload_index: int | None) -> TimelineEntry:
    event_type = str(event.get("type") or "unknown")
    return TimelineEntry(
        id=f"system-{event.get('sequence') or event_type}",
        kind="system",
        event_type=event_type,
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=SYSTEM_EVENT_LABELS[event_type],
        summary=_system_summary(event),
        body=None,
        actor=None,
        status=None,
        emoji=SYSTEM_EVENT_EMOJI.get(event_type, "•"),
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge=None,
        detail_items=[TimelineDetailItem(label="Event", format="json", value=event)],
        raw=event,
    )


def _system_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "unknown")
    if event_type == "run_started":
        return "Workflow execution started."
    if event_type == "run_completed":
        return "Workflow execution completed successfully."
    if event_type == "run_failed":
        return str(event.get("error_message") or "Workflow execution failed.")
    if event_type == "scenario_started":
        return f"Started scenario {event.get('scenario_name') or 'scenario'}."
    if event_type == "scenario_completed":
        return f"Finished scenario {event.get('scenario_name') or 'scenario'}."
    if event_type == "meeting_notes_applied":
        meeting_id = event.get("meeting_id")
        return f"Synced Zocks meeting notes into Salesforce for {meeting_id}." if meeting_id else "Synced meeting notes into Salesforce."
    return "Workflow event."


def _build_approval_requested_entry(
    event: dict[str, Any],
    payload_index: int | None,
) -> TimelineEntry:
    prompt = str(event.get("prompt") or "Human approval is required.")
    return TimelineEntry(
        id=f"approval-request-{event.get('sequence') or 'pending'}",
        kind="approval",
        event_type="approval_requested",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title="Approval Needed",
        summary="Approval requested before the workflow could continue.",
        body=prompt,
        actor="Human Review",
        status="pending",
        emoji="🧑‍⚖️",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge="approval",
        detail_items=[TimelineDetailItem(label="Prompt", value=prompt)],
        raw=event,
    )


def _build_approval_resolution_entry(
    event: dict[str, Any],
    payload_index: int | None,
) -> TimelineEntry:
    event_type = str(event.get("type") or "approval_resolved")
    response = str(event.get("response_text") or "Approval updated.")
    return TimelineEntry(
        id=f"approval-resolution-{event.get('sequence') or event_type}",
        kind="approval",
        event_type=event_type,
        timestamp=_parse_timestamp(event.get("timestamp")),
        title="Approval Updated",
        summary=response,
        body=None,
        actor="Human Review",
        status="resolved" if event_type == "approval_resolved" else "cancelled",
        emoji="👍" if event_type == "approval_resolved" else "🚫",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge="approval",
        detail_items=[TimelineDetailItem(label="Event", format="json", value=event)],
        raw=event,
    )


def _build_agent_status_entry(
    event: dict[str, Any],
    payload_index: int | None,
    *,
    started: bool,
    payload_context: PayloadContext | None = None,
) -> TimelineEntry:
    agent_name = str(event.get("agent_name") or "Agent")
    if started:
        summary = f"{agent_name} started."
    else:
        summary = _agent_finish_summary(agent_name, payload_context)
    return TimelineEntry(
        id=f"agent-status-{event.get('sequence') or agent_name}",
        kind="agent",
        event_type="agent_start" if started else "agent_end",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=agent_name,
        summary=summary,
        body=None,
        actor=agent_name,
        status="running" if started else "completed",
        emoji="🤖",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge="agent",
        detail_items=[TimelineDetailItem(label="Event", format="json", value=event)],
        raw=event,
    )


def _agent_finish_summary(
    agent_name: str,
    payload_context: PayloadContext | None,
) -> str:
    if "manager" in agent_name.lower() and payload_context and payload_context.manager_output:
        summary = payload_context.manager_output.get("summary")
        if isinstance(summary, str) and summary:
            return summary
    return f"{agent_name} finished."


def _build_manager_call_entry(
    *,
    tool_name: str,
    payload_context: PayloadContext | None,
    payload_index: int | None,
    event: dict[str, Any],
    previous_specialist_summary: str | None,
) -> TimelineEntry:
    specialist_label = SPECIALIST_AGENT_TO_LABEL[tool_name]
    summary = _manager_call_summary(tool_name, payload_context, previous_specialist_summary)
    return TimelineEntry(
        id=f"manager-call-{event.get('sequence') or tool_name}",
        kind="agent",
        event_type="manager_call",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title="Manager Agent",
        summary=summary,
        body=None,
        actor="Manager Agent",
        status=None,
        emoji="🤖",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge=specialist_label,
        detail_items=[TimelineDetailItem(label="Event", format="json", value=event)],
        raw=event,
    )


def _manager_call_summary(
    tool_name: str,
    payload_context: PayloadContext | None,
    previous_specialist_summary: str | None,
) -> str:
    payload = payload_context.payload if payload_context else {}
    payload_type = str(payload.get("payload_type") or "")
    trigger_type = str(payload.get("salesforce_trigger_type") or "")

    if tool_name == "lead_reviewer_agent":
        return "Calling Lead Reviewer Agent to handle the new lead notification."

    if tool_name == "response_ingestion_agent":
        return "Calling Response Ingestion Agent to process the inbound email and any attachments."

    if tool_name == "infotrack_agent":
        if previous_specialist_summary:
            return f"{previous_specialist_summary} Proceeding to call InfoTrack Agent."
        if payload_type == "salesforce_notification" and trigger_type == "meeting_close":
            return "Calling InfoTrack Agent to handle the meeting-close follow-up."
        return "Calling InfoTrack Agent to handle outreach and follow-up."

    return f"Calling {SPECIALIST_AGENT_TO_LABEL.get(tool_name, tool_name)}."


def _build_agent_call_entry(
    agent_name: str,
    payload_index: int | None,
    summary: str,
    event: dict[str, Any],
) -> TimelineEntry:
    return TimelineEntry(
        id=f"agent-call-{event.get('sequence') or agent_name}",
        kind="agent",
        event_type="tool_call",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=agent_name,
        summary=summary,
        body=None,
        actor=agent_name,
        status=None,
        emoji="🤖",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge="agent",
        detail_items=[TimelineDetailItem(label="Event", format="json", value=event)],
        raw=event,
    )


def _tool_call_intent(
    agent_name: str | None,
    tool_name: str,
    payload_context: PayloadContext | None,
) -> str:
    if tool_name == "salesforce_lead_retrieval_tool":
        return "Calling the Salesforce Lead Retrieval Tool to retrieve the lead record."
    if tool_name == "salesforce_client_query_tool":
        return "Calling the Salesforce Client Query Tool to check for an existing client."
    if tool_name == "salesforce_lead_query_tool":
        return "Calling the Salesforce Lead Query Tool to look for duplicate leads."
    if tool_name == "salesforce_lead_status_update_tool":
        return "Calling the Salesforce Lead Status Update Tool to move the lead into the correct workflow state."
    if tool_name == "salesforce_advisor_search_tool":
        return "Calling the Salesforce Advisor Search Tool to find the best available advisor."
    if tool_name == "salesforce_advisor_assignment_tool":
        return "Calling the Salesforce Advisor Assignment Tool to assign the selected advisor."
    if tool_name == "salesforce_client_information_tool":
        return "Calling the Salesforce Client Information Tool to review the latest client record."
    if tool_name == "advisor_calendar_tool":
        return "Calling the Advisor Calendar Tool to get validated meeting availability."
    if tool_name == "zocks_reviewer_tool":
        return "Calling the Zocks Reviewer Tool to review the latest meeting notes."
    if tool_name == "email_read_tool":
        return "Calling the Email Read Tool to read the incoming email."
    if tool_name == "send_email_tool":
        return "Calling the Send Email Tool to send follow-up outreach."
    if tool_name == "meeting_scheduler_tool":
        return "Calling the Meeting Scheduler Tool to book the confirmed appointment."
    if tool_name == "salesforce_client_input_tool":
        return "Calling the Salesforce Client Input Tool to update Salesforce with the latest information."
    if tool_name == "document_processor_tool":
        return "Calling the Document Processor Tool to inspect the attachment."
    if tool_name == "laserfiche_uploader_tool":
        return "Calling the Laserfiche Uploader Tool to store the compliance document."
    if tool_name == "salesforce_document_uploader_tool":
        return "Calling the Salesforce Document Uploader Tool to store the attachment."
    return f"Calling {tool_name.replace('_', ' ')}."


def _build_specialist_result_entry(
    *,
    tool_name: str,
    payload_context: PayloadContext | None,
    payload_index: int | None,
    trace_span: dict[str, Any] | None,
    event: dict[str, Any],
) -> TimelineEntry:
    span_data = trace_span.get("span_data") if isinstance(trace_span, dict) else None
    output_payload = _parse_json_like(span_data.get("output") if isinstance(span_data, dict) else None)
    input_payload = _parse_json_like(span_data.get("input") if isinstance(span_data, dict) else None)
    summary = _specialist_result_summary(tool_name, output_payload, payload_context)
    details = [TimelineDetailItem(label="Why", value=summary)]
    if input_payload is not None:
        details.append(_detail_item("Input", input_payload))
    if output_payload is not None:
        details.append(_detail_item("Output", output_payload))
    details.append(TimelineDetailItem(label="Event", format="json", value=event))
    return TimelineEntry(
        id=f"specialist-result-{event.get('sequence') or tool_name}",
        kind="agent",
        event_type="specialist_result",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=SPECIALIST_AGENT_TO_LABEL[tool_name],
        summary=summary,
        body=None,
        actor=SPECIALIST_AGENT_TO_LABEL[tool_name],
        status=None,
        emoji="🤖",
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge=SPECIALIST_AGENT_TO_LABEL[tool_name],
        detail_items=details,
        raw=event,
    )


def _merge_specialist_result_into_start(
    start_entry: TimelineEntry,
    result_entry: TimelineEntry,
) -> None:
    start_entry.event_type = "agent_summary"
    start_entry.summary = result_entry.summary
    start_entry.body = result_entry.body
    start_entry.status = "completed"
    start_entry.badge = result_entry.badge
    start_entry.attachments = result_entry.attachments
    start_entry.detail_items = result_entry.detail_items
    start_entry.raw = result_entry.raw


def _specialist_result_summary(
    tool_name: str,
    output_payload: dict[str, Any] | list[Any] | str | None,
    payload_context: PayloadContext | None,
) -> str:
    if not isinstance(output_payload, str):
        return f"{SPECIALIST_AGENT_TO_LABEL[tool_name]} completed."

    if tool_name == "lead_reviewer_agent":
        advisor = _extract_repr_field(output_payload, "assigned_advisor_name")
        status_after = _extract_repr_field(output_payload, "lead_status_after_review")
        disposition = _extract_repr_field(output_payload, "lead_disposition")
        if advisor and status_after and disposition == "qualified":
            return f"Lead Reviewer Agent correctly processed the lead, assigned advisor {advisor}, and set the lead to {status_after}."
        summary_note = _extract_repr_field(output_payload, "summary_note")
        if isinstance(summary_note, str) and summary_note:
            return summary_note

    if tool_name == "response_ingestion_agent":
        meeting_scheduled = _extract_repr_field(output_payload, "meeting_scheduled")
        follow_up_email_sent = _extract_repr_field(output_payload, "follow_up_email_sent")
        salesforce_updated = _extract_repr_field(output_payload, "salesforce_updated")
        if meeting_scheduled and salesforce_updated and follow_up_email_sent:
            return "Response Ingestion Agent processed the email, scheduled the meeting, updated Salesforce, and sent a confirmation email."
        escalation_summary = _extract_repr_field(output_payload, "escalation_summary")
        if isinstance(escalation_summary, str) and escalation_summary:
            return escalation_summary

    if tool_name == "infotrack_agent":
        email_summary = _extract_repr_field(output_payload, "email_summary")
        if isinstance(email_summary, str) and email_summary:
            return email_summary

    actions = _extract_repr_field(output_payload, "actions_taken")
    if isinstance(actions, list) and actions:
        action = str(actions[0]).rstrip(".")
        return f"{SPECIALIST_AGENT_TO_LABEL[tool_name]} completed: {action}."

    return f"{SPECIALIST_AGENT_TO_LABEL[tool_name]} completed."


def _build_tool_result_entry(
    *,
    tool_name: str,
    agent_name: str | None,
    payload_index: int | None,
    trace_span: dict[str, Any] | None,
    event: dict[str, Any],
) -> TimelineEntry:
    span_data = trace_span.get("span_data") if isinstance(trace_span, dict) else None
    input_payload = _parse_json_like(
        span_data.get("input") if isinstance(span_data, dict) else None
    )
    event_output_payload = _parse_json_like(event.get("tool_output"))
    output_payload = (
        event_output_payload
        if event_output_payload is not None
        else _parse_json_like(span_data.get("output") if isinstance(span_data, dict) else None)
    )
    summary, body = _format_tool_result(tool_name, input_payload, output_payload)
    is_pending_details = _tool_details_pending(
        tool_name,
        trace_span,
        event_output_payload,
        output_payload,
        body,
    )
    attachments = _extract_tool_attachments(tool_name, input_payload, output_payload)
    detail_items = [TimelineDetailItem(label="Why", value=_tool_result_reasoning(tool_name))]
    if input_payload is not None:
        detail_items.append(_detail_item("Input", input_payload))
    if output_payload is not None:
        detail_items.append(_detail_item("Output", output_payload))
    detail_items.append(TimelineDetailItem(label="Event", format="json", value=event))
    return TimelineEntry(
        id=f"tool-result-{event.get('sequence') or tool_name}",
        kind="tool",
        event_type="tool_result",
        timestamp=_parse_timestamp(event.get("timestamp")),
        title=_format_tool_title(tool_name),
        summary=summary,
        body=body,
        actor=agent_name,
        status="completed",
        emoji=TOOL_EMOJI.get(tool_name, "🛠️"),
        is_pending_details=is_pending_details,
        payload_index=payload_index,
        payload_label=f"Payload {payload_index}" if payload_index else None,
        badge=tool_name,
        attachments=attachments,
        detail_items=detail_items,
        raw=event,
    )


def _tool_result_reasoning(tool_name: str) -> str:
    if tool_name == "email_read_tool":
        return "The workflow needed the contents of the incoming email before it could decide what to do next."
    if tool_name == "send_email_tool":
        return "The workflow needed to communicate the next step back to the client."
    if tool_name == "meeting_scheduler_tool":
        return "The workflow had enough information to book the confirmed appointment."
    if tool_name == "laserfiche_uploader_tool":
        return "The attachment was routed to Laserfiche because it was treated as a compliance document."
    if tool_name == "salesforce_document_uploader_tool":
        return "The attachment was routed to Salesforce as a standard document."
    return f"The workflow called {tool_name.replace('_', ' ')} to continue processing this step."


def _tool_details_pending(
    tool_name: str,
    trace_span: dict[str, Any] | None,
    event_output_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
    body: str | None,
) -> bool:
    if event_output_payload is not None:
        return False
    if trace_span is None:
        return True
    if output_payload is not None:
        return False
    if tool_name in {
        "email_read_tool",
        "send_email_tool",
        "meeting_scheduler_tool",
        "laserfiche_uploader_tool",
        "salesforce_document_uploader_tool",
        "advisor_calendar_tool",
        "document_processor_tool",
        "salesforce_client_input_tool",
    }:
        return True
    return body is None


def _extract_tool_attachments(
    tool_name: str,
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> list[TimelineAttachment]:
    if tool_name == "email_read_tool":
        attachments = _extract_list_field(output_payload, "attachments")
        return [
            TimelineAttachment(
                label=Path(
                    str(item.get("filename") or "[unnamed attachment]")
                ).name,
                path=str(item.get("filename") or ""),
            )
            for item in attachments
            if isinstance(item, dict) and item.get("filename")
        ]

    if tool_name == "laserfiche_uploader_tool":
        path = _extract_string_field(output_payload, "attachment_path") or _extract_string_field(
            input_payload, "attachment_path"
        )
        if path:
            return [TimelineAttachment(label=Path(path).name, path=path)]
        return []

    if tool_name == "salesforce_document_uploader_tool":
        document_paths = _extract_list_field(output_payload, "uploaded_documents")
        if not document_paths and isinstance(input_payload, dict):
            raw = input_payload.get("document_paths")
            if isinstance(raw, list):
                document_paths = raw
            elif isinstance(raw, str):
                document_paths = [raw]
        return [
            TimelineAttachment(label=Path(str(path)).name, path=str(path))
            for path in document_paths
            if str(path)
        ]

    if tool_name == "document_processor_tool":
        path = _extract_string_field(input_payload, "path") or _extract_string_field(
            input_payload, "attachment_path"
        )
        if path:
            return [TimelineAttachment(label=Path(path).name, path=path)]

    return []


def _format_tool_result(
    tool_name: str,
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    if tool_name == "email_read_tool":
        return _format_email_read_result(input_payload, output_payload)
    if tool_name == "send_email_tool":
        return _format_send_email_result(input_payload, output_payload)
    if tool_name == "meeting_scheduler_tool":
        return _format_meeting_scheduler_result(input_payload, output_payload)
    if tool_name == "laserfiche_uploader_tool":
        return _format_laserfiche_result(input_payload, output_payload)
    if tool_name == "salesforce_document_uploader_tool":
        return _format_salesforce_document_result(input_payload, output_payload)
    if tool_name == "advisor_calendar_tool":
        return _format_calendar_result(input_payload, output_payload)
    if tool_name == "salesforce_client_information_tool":
        uid = _extract_string_field(input_payload, "uid")
        return (
            f"Loading Salesforce client information for {uid}." if uid else "Loading Salesforce client information.",
            _prefixed_result(_extract_string_field(output_payload, "message")),
        )
    if tool_name == "salesforce_client_input_tool":
        return _format_salesforce_input_result(input_payload, output_payload)
    if tool_name == "document_processor_tool":
        return _format_document_processor_result(input_payload, output_payload)
    if tool_name == "zocks_reviewer_tool":
        return _format_zocks_result(input_payload, output_payload)
    if tool_name == "salesforce_lead_retrieval_tool":
        uid = _extract_string_field(input_payload, "uid")
        lead_name = _extract_string_field(output_payload, "lead_name")
        lead_result = lead_name or _extract_string_field(output_payload, "message")
        if lead_name:
            lead_result = f"Retrieved lead {lead_name}."
        return (
            f"Searching for lead with UID: {uid}." if uid else "Searching for the lead record.",
            _prefixed_result(lead_result),
        )
    if tool_name == "salesforce_client_query_tool":
        return (
            "Searching for clients with matching name and email address.",
            _prefixed_result(
                _extract_string_field(output_payload, "message") or _stringify_output(output_payload)
            ),
        )
    if tool_name == "salesforce_lead_query_tool":
        return (
            "Searching for duplicate leads in Salesforce.",
            _prefixed_result(
                _extract_string_field(output_payload, "message") or _stringify_output(output_payload)
            ),
        )
    if tool_name == "salesforce_lead_status_update_tool":
        return (
            "Updating the lead status in Salesforce.",
            _prefixed_result(
                _extract_string_field(output_payload, "message") or _stringify_output(output_payload)
            ),
        )
    if tool_name == "salesforce_advisor_search_tool":
        return (
            "Searching for a suitable advisor.",
            _prefixed_result(
                _extract_string_field(output_payload, "message") or _stringify_output(output_payload)
            ),
        )
    if tool_name == "salesforce_advisor_assignment_tool":
        advisor_name = _extract_string_field(output_payload, "advisor_name")
        result = _extract_string_field(output_payload, "message") or _stringify_output(output_payload)
        if advisor_name:
            result = f"Assigned advisor {advisor_name}."
        return ("Assigning the selected advisor.", _prefixed_result(result))

    return (
        f"Completed {tool_name.replace('_', ' ')}.",
        _prefixed_result(_stringify_output(output_payload)),
    )


def _format_email_read_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    if isinstance(output_payload, str) and "blocked" in output_payload.lower():
        return ("Inbound email was blocked during reading.", output_payload)

    sender = _extract_string_field(output_payload, "sender_email")
    subject = _extract_string_field(output_payload, "subject")
    body = _extract_string_field(output_payload, "body_text")
    recipients = _extract_list_field(output_payload, "recipients")
    cc = _extract_list_field(output_payload, "cc_recipients")
    attachments = _extract_list_field(output_payload, "attachments")

    summary = "Received and read the inbound email."
    if sender and subject:
        summary = f"Received inbound email from {sender} with subject '{subject}'."

    lines: list[str] = []
    lines.append("Incoming email")
    if sender:
        lines.append(f"From: {sender}")
    if recipients:
        lines.append(f"To: {', '.join(str(item) for item in recipients)}")
    if cc:
        lines.append(f"CC: {', '.join(str(item) for item in cc)}")
    if subject:
        lines.append(f"Subject: {subject}")
    if attachments:
        attachment_names = []
        for item in attachments:
            if isinstance(item, dict):
                attachment_names.append(
                    Path(str(item.get("filename") or "[unnamed attachment]")).name
                )
            else:
                attachment_names.append(Path(str(item)).name)
        lines.append(f"Attachments: {', '.join(attachment_names)}")
    if body:
        lines.append("")
        lines.append(body)
    return summary, "\n".join(lines) if lines else None


def _format_send_email_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    to = _extract_list_field(input_payload, "to")
    cc = _extract_list_field(input_payload, "cc")
    subject = _extract_string_field(input_payload, "subject")
    body = _extract_string_field(input_payload, "text")
    summary = f"Sent outbound email '{subject}'." if subject else "Sent outbound email."
    if to:
        summary = f"{summary.rstrip('.')} to {', '.join(str(item) for item in to)}."
    lines: list[str] = []
    lines.append("Outgoing email")
    if to:
        lines.append(f"To: {', '.join(str(item) for item in to)}")
    if cc:
        lines.append(f"CC: {', '.join(str(item) for item in cc)}")
    if subject:
        lines.append(f"Subject: {subject}")
    if body:
        lines.append("")
        lines.append(body)
    return summary, "\n".join(lines) if lines else None


def _format_meeting_scheduler_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    start_time = _extract_string_field(input_payload, "start_time")
    uid = _extract_string_field(input_payload, "uid")
    meeting_id = _extract_string_field(output_payload, "meeting_id") or _extract_nested_string(output_payload, "meeting_record", "meeting_id")
    formatted_start_time = _display_datetime(start_time)
    summary = (
        f"Scheduled the appointment for {formatted_start_time}."
        if formatted_start_time
        else "Scheduled the meeting."
    )
    lines: list[str] = []
    if uid:
        lines.append(f"UID: {uid}")
    if meeting_id:
        lines.append(f"Meeting ID: {meeting_id}")
    if formatted_start_time:
        lines.append(f"Scheduled at: {formatted_start_time}")
    message = _extract_string_field(output_payload, "message")
    if message:
        lines.append(f"Result: {message}")
    return summary, "\n".join(lines) if lines else None


def _format_laserfiche_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    path = _extract_string_field(output_payload, "attachment_path") or _extract_string_field(input_payload, "attachment_path")
    uid = _extract_string_field(output_payload, "uid") or _extract_string_field(input_payload, "uid")
    filename = Path(path).name if path else "file"
    summary = f"Uploaded {filename} to Laserfiche."
    lines: list[str] = [f"Result: File {filename} uploaded to Laserfiche."]
    if uid:
        lines.append(f"UID: {uid}")
    if path:
        lines.append(f"Path: {path}")
    body = "\n".join(lines) if lines else None
    return summary, body


def _format_salesforce_document_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    uploaded = _extract_list_field(output_payload, "uploaded_documents")
    uid = _extract_string_field(output_payload, "uid") or _extract_string_field(input_payload, "uid")
    if uploaded:
        file_names = [Path(str(item)).name for item in uploaded]
        summary = f"Uploaded {file_names[0]} to Salesforce."
        lines = ["Result: Uploaded document into Salesforce."]
        if uid:
            lines.append(f"UID: {uid}")
        lines.append(f"Files: {', '.join(file_names)}")
        body = "\n".join(lines)
        return summary, body
    return (
        "Uploaded document metadata to Salesforce.",
        _prefixed_result(_stringify_output(output_payload)),
    )


def _format_calendar_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    blocks = _extract_list_field(output_payload, "available_blocks")
    advisor = _extract_string_field(output_payload, "advisor_name")
    summary = (
        f"Found {len(blocks)} available meeting times."
        if blocks
        else "Checked advisor calendar availability."
    )
    lines: list[str] = []
    if advisor:
        lines.append(f"Advisor: {advisor}")
    if blocks:
        lines.append("Available times:")
        lines.extend(
            f"- {_display_datetime(str(block)) or str(block)}" for block in blocks
        )
    return summary, "\n".join(lines) if lines else None


def _format_salesforce_input_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    updated_fields = _extract_list_field(output_payload, "updated_fields")
    uid = _extract_string_field(output_payload, "uid") or _extract_string_field(input_payload, "uid")
    if updated_fields:
        summary = (
            f"Updated the Salesforce client record for {uid}."
            if uid
            else "Updated Salesforce."
        )
        body = "Result: Updated Salesforce fields.\n" + "\n".join(
            f"- {field}" for field in updated_fields
        )
        return summary, body
    message = _extract_string_field(output_payload, "message")
    return (
        f"Updated Salesforce for {uid}." if uid else "Updated Salesforce.",
        _prefixed_result(message),
    )


def _format_document_processor_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    attachment_path = _extract_string_field(input_payload, "path") or _extract_string_field(input_payload, "attachment_path")
    filename = Path(attachment_path).name if attachment_path else "attachment"
    compliance_flag = _extract_string_field(output_payload, "compliance_related")
    justification = _extract_string_field(output_payload, "justification") or _extract_string_field(output_payload, "message")
    summary = f"Processed attachment {filename}."
    if compliance_flag:
        summary = f"Processed attachment {filename} and classified it as {'compliance-related' if compliance_flag == 'True' else 'non-compliance'}."
    return summary, _prefixed_result(justification)


def _format_zocks_result(
    input_payload: dict[str, Any] | list[Any] | str | None,
    output_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[str, str | None]:
    summary = _extract_string_field(output_payload, "zocks_summary")
    action_items = _extract_list_field(output_payload, "zocks_action_items")
    title = "Reviewed the latest Zocks meeting notes."
    if action_items:
        body = "\n".join(
            [f"Result: {summary}" if summary else "Result: Reviewed Zocks notes."]
            + [f"- {item}" for item in action_items]
        ).strip()
        return title, body
    return title, _prefixed_result(summary)


def _format_tool_title(name: str) -> str:
    titles = {
        "email_read_tool": "Incoming Email",
        "send_email_tool": "Outgoing Email",
        "meeting_scheduler_tool": "Meeting Scheduled",
        "laserfiche_uploader_tool": "Laserfiche Upload",
        "salesforce_document_uploader_tool": "Salesforce Document Upload",
        "advisor_calendar_tool": "Advisor Availability",
        "salesforce_client_information_tool": "Salesforce Client Information",
        "salesforce_client_input_tool": "Salesforce Update",
        "document_processor_tool": "Document Review",
        "zocks_reviewer_tool": "Zocks Notes Review",
        "salesforce_lead_retrieval_tool": "Salesforce Lead Lookup",
        "salesforce_client_query_tool": "Existing Client Check",
        "salesforce_lead_query_tool": "Duplicate Lead Check",
        "salesforce_advisor_search_tool": "Advisor Search",
        "salesforce_advisor_assignment_tool": "Advisor Assignment",
    }
    return titles.get(name, name.replace("_", " ").title())


def _extract_nested_string(
    value: dict[str, Any] | list[Any] | str | None,
    field_name: str,
    nested_key: str,
) -> str | None:
    if not isinstance(value, dict):
        return None
    nested = value.get(field_name)
    if isinstance(nested, dict):
        raw = nested.get(nested_key)
        return raw if isinstance(raw, str) and raw else None
    return None


def _stringify_output(value: dict[str, Any] | list[Any] | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _prefixed_result(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("Result:"):
        return value
    return f"Result: {value}"


def _display_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return value
    month = parsed.strftime("%b")
    hour = parsed.strftime("%I").lstrip("0") or "0"
    return f"{month} {parsed.day}, {hour}:{parsed.strftime('%M %p')} UTC"


def _load_trace_spans(trace_id: Any) -> list[dict[str, Any]]:
    if not isinstance(trace_id, str) or not trace_id:
        return []

    path = TRACES_DIR / f"{trace_id}.json"
    if not path.is_file():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    spans = payload.get("spans")
    if not isinstance(spans, list):
        return []
    return [span for span in spans if isinstance(span, dict)]


def _find_ancestor_agent_name(
    span: dict[str, Any],
    span_lookup: dict[str, dict[str, Any]],
) -> str | None:
    parent_id = span.get("parent_id")
    while isinstance(parent_id, str) and parent_id:
        parent = span_lookup.get(parent_id)
        if parent is None:
            break
        span_data = parent.get("span_data")
        if isinstance(span_data, dict) and str(span_data.get("type") or "") == "agent":
            name = span_data.get("name")
            return str(name) if isinstance(name, str) else None
        parent_id = parent.get("parent_id")
    return None


def _parse_json_like(value: Any) -> dict[str, Any] | list[Any] | str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return str(value)

    stripped = value.strip()
    if not stripped:
        return None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    return parsed if isinstance(parsed, (dict, list)) else stripped


def _extract_string_field(
    value: dict[str, Any] | list[Any] | str | None,
    field_name: str,
) -> str | None:
    if isinstance(value, dict):
        raw = value.get(field_name)
        return raw if isinstance(raw, str) and raw else None
    if isinstance(value, str):
        extracted = _extract_repr_field(value, field_name)
        return extracted if isinstance(extracted, str) and extracted else None
    return None


def _extract_list_field(
    value: dict[str, Any] | list[Any] | str | None,
    field_name: str,
) -> list[Any]:
    if isinstance(value, dict):
        raw = value.get(field_name)
        return raw if isinstance(raw, list) else []
    if isinstance(value, str):
        extracted = _extract_repr_field(value, field_name)
        return extracted if isinstance(extracted, list) else []
    return []


def _extract_repr_field(value: str, field_name: str) -> Any:
    pattern = re.compile(rf"{re.escape(field_name)}=(.+?)(?= \w+=|$)", flags=re.DOTALL)
    match = pattern.search(value)
    if not match:
        return None

    raw = match.group(1).strip().rstrip(",")
    if raw in {"None", "null"}:
        return None
    if raw in {"True", "False"}:
        return raw

    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw.strip("'\"")


def _detail_item(
    label: str,
    value: dict[str, Any] | list[Any] | str,
) -> TimelineDetailItem:
    if isinstance(value, str):
        return TimelineDetailItem(label=label, value=value)
    return TimelineDetailItem(label=label, format="json", value=value)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None
