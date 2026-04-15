from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from agents import Runner, SQLiteSession, trace
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from custom_agents import ManagerOutput, make_manager_agent
from scripts.reset_runtime_data import restore_runtime_data, save_runtime_data
from tools import update_meeting_notes
from utils import (
    ExecutionReport,
    TelemetryRunHook,
    TelemetrySummary,
    build_execution_report,
    emit_execution_summary,
    setup_run_hooks,
    setup_tracing,
)


AGENT_MAX_TURNS = 25
SCENARIOS_PATH = Path("data/scenarios.json")

load_dotenv(override=True)


class ScenarioDefinition(BaseModel):
    """Scenario definition loaded from data/scenarios.json."""

    id: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    payloads: Annotated[list[dict[str, Any]], Field(default_factory=list)]


class ScenarioCatalog(BaseModel):
    """Collection of scenarios and supported payload types."""

    payload_types: Annotated[list[dict[str, Any]], Field(default_factory=list)]
    scenarios: Annotated[list[ScenarioDefinition], Field(default_factory=list)]


class PayloadExecutionResult(BaseModel):
    """Execution result for a single payload dispatched to the manager."""

    payload_index: Annotated[int, Field(ge=1)]
    payload_total: Annotated[int, Field(ge=1)]
    input_payload: Annotated[dict[str, Any], Field(default_factory=dict)]
    manager_output: Annotated[ManagerOutput, Field()]
    trace_id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]


class SinglePayloadExecutionResult(BaseModel):
    """Execution result returned for a one-off payload run."""

    input_payload: Annotated[dict[str, Any], Field(default_factory=dict)]
    manager_output: Annotated[ManagerOutput, Field()]
    trace_id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]
    telemetry_summary: Annotated[TelemetrySummary, Field()]
    execution_report: Annotated[ExecutionReport, Field()]


class ScenarioExecutionResult(BaseModel):
    """Execution result returned for a multi-payload scenario run."""

    scenario_id: Annotated[str, Field(min_length=1)]
    scenario_name: Annotated[str, Field(min_length=1)]
    payload_results: Annotated[list[PayloadExecutionResult], Field(default_factory=list)]
    trace_id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]
    telemetry_summary: Annotated[TelemetrySummary, Field()]
    execution_report: Annotated[ExecutionReport, Field()]


def load_scenario_catalog() -> ScenarioCatalog:
    """Load the current scenario catalog from disk."""

    if not SCENARIOS_PATH.is_file():
        raise FileNotFoundError(f"{SCENARIOS_PATH} not found.")

    payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    return ScenarioCatalog.model_validate(payload)


def load_scenarios() -> list[ScenarioDefinition]:
    """Load all runnable scenarios from disk."""

    return load_scenario_catalog().scenarios


def get_scenario_definition(scenario_id: str) -> ScenarioDefinition:
    """Return a single scenario definition by id."""

    for scenario in load_scenarios():
        if scenario.id == scenario_id:
            return scenario

    raise KeyError(f"Scenario '{scenario_id}' not found.")


def list_scenarios_for_cli() -> list[str]:
    """Render the scenario catalog for CLI display."""

    output: list[str] = []
    for scenario in load_scenarios():
        output.append(f"{scenario.id}:")
        output.append(f"  {scenario.description}")
        output.append("")
    return output


def restore_runtime_state() -> tuple[Path, ...]:
    """Restore mutable runtime JSON files from their preserved originals."""

    return restore_runtime_data()


def save_runtime_state() -> tuple[Path, ...]:
    """Persist the current mutable runtime JSON files as the new originals."""

    return save_runtime_data()


async def emit_runtime_event(
    event_queue: asyncio.Queue[dict[str, Any]] | None,
    event_type: str,
    **payload: Any,
) -> None:
    """Push a structured runtime event onto the shared event queue."""

    if event_queue is None:
        return

    event = {
        "type": event_type,
        "timestamp": payload.pop("timestamp", None),
        **payload,
    }
    if event["timestamp"] is None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()

    await event_queue.put(event)


def _format_scenario_name(scenario_id: str) -> str:
    return scenario_id.replace("_", " ").title()


def _build_workflow_name(scenario_name: str | None) -> str:
    return f"Finance Workflow - {scenario_name}" if scenario_name else "Finance Workflow"


async def _apply_meeting_close_notes(
    payload: dict[str, Any],
    event_queue: asyncio.Queue[dict[str, Any]] | None,
) -> None:
    if payload.get("payload_type") != "salesforce_notification":
        return

    if payload.get("salesforce_trigger_type") != "meeting_close":
        return

    uid = payload.get("UID")
    meeting_notes = payload.get("meeting_notes")
    if not uid or not meeting_notes:
        return

    print("Meeting close detected. Pushing Zocks notes to Salesforce.")
    update_meeting_notes(uid, meeting_notes)
    await emit_runtime_event(
        event_queue,
        "meeting_notes_applied",
        uid=uid,
        meeting_id=meeting_notes.get("meeting_id"),
    )


async def run_manager(
    payload: dict[str, Any],
    run_hooks: TelemetryRunHook | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    scenario_name: str | None = None,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    payload_index: int = 1,
    payload_total: int = 1,
) -> tuple[ManagerOutput, TelemetryRunHook, str, str]:
    """Execute the manager agent for a single payload."""

    run_hooks = run_hooks or setup_run_hooks(
        verbose=False,
        save_traces=True,
        event_queue=event_queue,
    )
    session_id = session_id or uuid.uuid4().hex
    if trace_id is None:
        trace_id, _ = setup_tracing()

    session = SQLiteSession(session_id=session_id)
    workflow_name = _build_workflow_name(scenario_name)
    payload_type = str(payload.get("payload_type") or "unknown")
    trigger_type = payload.get("salesforce_trigger_type")

    print("[Run] Payload: provided JSON")
    print(f"[Run] Workflow name: {workflow_name}")
    print(f"[Run] Session: {session.session_id}")
    print(f"[Run] Payload type: {payload_type}")
    if trigger_type:
        print(f"[Run] Notification: {trigger_type}")
    print("[Run] Dispatching to Manager agent...\n")

    await emit_runtime_event(
        event_queue,
        "payload_started",
        payload_index=payload_index,
        payload_total=payload_total,
        payload_type=payload_type,
        uid=payload.get("UID"),
        email_id=payload.get("email_id"),
        trigger_type=trigger_type,
        trace_id=trace_id,
        session_id=session_id,
    )

    await _apply_meeting_close_notes(payload, event_queue)

    manager_agent = make_manager_agent(hooks=run_hooks)

    with trace(workflow_name=workflow_name, trace_id=trace_id):
        result = await Runner().run(
            starting_agent=manager_agent,
            input=json.dumps(payload),
            hooks=run_hooks,
            session=session,
            max_turns=AGENT_MAX_TURNS,
        )

    output: ManagerOutput = result.final_output

    print("Manager summary:")
    print(f"  summary  : {output.summary or 'n/a'}")
    print(f"  status   : {output.status}")
    print(f"  email    : {output.email_type or 'n/a'}")
    print(f"  actions  : {', '.join(output.actions) if output.actions else 'n/a'}")
    print(f"  gaps     : {', '.join(output.gaps) if output.gaps else 'n/a'}")
    print(f"  escalate : {output.escalation_summary or 'n/a'}")

    await emit_runtime_event(
        event_queue,
        "payload_completed",
        payload_index=payload_index,
        payload_total=payload_total,
        payload_type=payload_type,
        uid=payload.get("UID"),
        email_id=payload.get("email_id"),
        trigger_type=trigger_type,
        manager_status=output.status,
        manager_summary=output.summary,
        trace_id=trace_id,
        session_id=session_id,
    )

    return output, run_hooks, trace_id, session_id


async def run_single_payload(
    payload: dict[str, Any],
    scenario_name: str | None = None,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    reset_runtime_data_at_start: bool = False,
) -> SinglePayloadExecutionResult:
    """Execute a single payload run and return the structured result."""

    if reset_runtime_data_at_start:
        restored_paths = restore_runtime_state()
        await emit_runtime_event(
            event_queue,
            "runtime_reset",
            restored_paths=[str(path) for path in restored_paths],
        )

    output, run_hooks, trace_id, session_id = await run_manager(
        payload=payload,
        scenario_name=scenario_name,
        event_queue=event_queue,
    )
    telemetry_summary = run_hooks.export_summary()
    execution_report = build_execution_report(telemetry_summary)
    emit_execution_summary(telemetry_summary)

    return SinglePayloadExecutionResult(
        input_payload=payload,
        manager_output=output,
        trace_id=trace_id,
        session_id=session_id,
        telemetry_summary=telemetry_summary,
        execution_report=execution_report,
    )


async def run_scenario_inputs(
    inputs: list[dict[str, Any]],
    scenario_id: str,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    reset_runtime_data_at_start: bool = False,
) -> ScenarioExecutionResult:
    """Execute a full scenario using the ordered payload list."""

    if not inputs:
        raise ValueError(f"Scenario '{scenario_id}' has no payloads to run.")

    scenario_name = _format_scenario_name(scenario_id)
    if reset_runtime_data_at_start:
        restored_paths = restore_runtime_state()
        await emit_runtime_event(
            event_queue,
            "runtime_reset",
            restored_paths=[str(path) for path in restored_paths],
        )

    await emit_runtime_event(
        event_queue,
        "scenario_started",
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        payload_total=len(inputs),
    )

    run_hooks: TelemetryRunHook | None = None
    trace_id: str | None = None
    session_id: str | None = None
    payload_results: list[PayloadExecutionResult] = []

    for index, payload in enumerate(inputs, start=1):
        print(
            f"\n[Run] Input {index}/{len(inputs)} "
            "=========================================================>>\n"
        )
        output, run_hooks, trace_id, session_id = await run_manager(
            payload=payload,
            run_hooks=run_hooks,
            trace_id=trace_id,
            session_id=session_id,
            scenario_name=scenario_name,
            event_queue=event_queue,
            payload_index=index,
            payload_total=len(inputs),
        )
        payload_results.append(
            PayloadExecutionResult(
                payload_index=index,
                payload_total=len(inputs),
                input_payload=payload,
                manager_output=output,
                trace_id=trace_id,
                session_id=session_id,
            )
        )
        print(
            f"\n[Complete] Input {index}/{len(inputs)} "
            "===================================================||\n"
        )

    if run_hooks is None or trace_id is None or session_id is None:
        raise RuntimeError("Scenario execution finished without telemetry context.")

    telemetry_summary = run_hooks.export_summary()
    execution_report = build_execution_report(telemetry_summary)
    emit_execution_summary(telemetry_summary)

    await emit_runtime_event(
        event_queue,
        "scenario_completed",
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        payload_total=len(inputs),
        trace_id=trace_id,
        session_id=session_id,
    )

    return ScenarioExecutionResult(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        payload_results=payload_results,
        trace_id=trace_id,
        session_id=session_id,
        telemetry_summary=telemetry_summary,
        execution_report=execution_report,
    )


async def run_scenario_by_id(
    scenario_id: str,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    reset_runtime_data_at_start: bool = False,
) -> ScenarioExecutionResult:
    """Load a scenario definition from disk and execute it."""

    scenario = get_scenario_definition(scenario_id)
    return await run_scenario_inputs(
        inputs=scenario.payloads,
        scenario_id=scenario.id,
        event_queue=event_queue,
        reset_runtime_data_at_start=reset_runtime_data_at_start,
    )
