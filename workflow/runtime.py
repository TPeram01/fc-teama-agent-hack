from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from utils import (
    ExecutionReport,
    ExecutionReportAgent,
    ExecutionReportTool,
    TelemetryTotals,
    calculate_cost,
    calculate_tool_costs,
)
from .context import (
    WorkflowExecutionContext,
    reset_workflow_execution_context,
    set_workflow_execution_context,
)
from .runner import (
    ScenarioDefinition,
    SinglePayloadExecutionResult,
    get_scenario_definition,
    load_scenarios,
    run_scenario_by_id,
    run_single_payload,
)


RUN_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})
ACTIVE_RUN_STATUSES: frozenset[str] = frozenset({"queued", "running", "awaiting_approval"})
_EVENT_SENTINEL = object()


class RunConflictError(RuntimeError):
    """Raised when a new run is requested while another run is active."""


class RunNotFoundError(KeyError):
    """Raised when a requested run does not exist."""


class ApprovalNotFoundError(KeyError):
    """Raised when a requested approval does not exist."""


class ApprovalStateError(RuntimeError):
    """Raised when a requested approval is no longer pending."""


class ScenarioListItem(BaseModel):
    """Slim scenario metadata returned to the frontend."""

    id: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    payload_count: Annotated[int, Field(ge=0)]
    payload_types: Annotated[list[str], Field(default_factory=list)]


class ApprovalSnapshot(BaseModel):
    """Serializable approval state exposed via the API."""

    approval_id: Annotated[str, Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=1)]
    status: Annotated[Literal["pending", "resolved", "cancelled"], Field()]
    requested_at: Annotated[datetime, Field()]
    resolved_at: Annotated[datetime | None, Field(default=None)]
    response_text: Annotated[str | None, Field(default=None)]


class WorkflowRunSnapshot(BaseModel):
    """Serializable state for a workflow run."""

    run_id: Annotated[str, Field(min_length=1)]
    run_kind: Annotated[Literal["payload", "scenario"], Field()]
    status: Annotated[
        Literal["queued", "running", "awaiting_approval", "completed", "failed"],
        Field(),
    ]
    scenario_id: Annotated[str | None, Field(default=None)]
    scenario_name: Annotated[str | None, Field(default=None)]
    input_payloads: Annotated[list[dict[str, Any]], Field(default_factory=list)]
    started_at: Annotated[datetime, Field()]
    completed_at: Annotated[datetime | None, Field(default=None)]
    trace_id: Annotated[str | None, Field(default=None)]
    session_id: Annotated[str | None, Field(default=None)]
    approvals: Annotated[list[ApprovalSnapshot], Field(default_factory=list)]
    event_count: Annotated[int, Field(ge=0)]
    events: Annotated[list[dict[str, Any]], Field(default_factory=list)]
    live_execution_report: Annotated[ExecutionReport | None, Field(default=None)]
    result: Annotated[dict[str, Any] | None, Field(default=None)]
    error_message: Annotated[str | None, Field(default=None)]


@dataclass(slots=True)
class LiveAgentProgressState:
    """Internal aggregate usage for a single agent during a live run."""

    name: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0


@dataclass(slots=True)
class PendingApprovalState:
    """Internal approval state for a workflow run."""

    approval_id: str
    prompt: str
    requested_at: datetime
    future: asyncio.Future[str] = field(repr=False)
    status: str = "pending"
    resolved_at: datetime | None = None
    response_text: str | None = None

    def to_snapshot(self) -> ApprovalSnapshot:
        return ApprovalSnapshot(
            approval_id=self.approval_id,
            prompt=self.prompt,
            status=self.status,  # type: ignore[arg-type]
            requested_at=self.requested_at,
            resolved_at=self.resolved_at,
            response_text=self.response_text,
        )


@dataclass(slots=True)
class WorkflowRunState:
    """Internal mutable state for a workflow run."""

    run_id: str
    run_kind: Literal["payload", "scenario"]
    input_payloads: list[dict[str, Any]]
    started_at: datetime
    status: Literal["queued", "running", "awaiting_approval", "completed", "failed"]
    scenario_id: str | None = None
    scenario_name: str | None = None
    completed_at: datetime | None = None
    trace_id: str | None = None
    session_id: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    approvals: dict[str, PendingApprovalState] = field(default_factory=dict)
    live_agents: dict[str, LiveAgentProgressState] = field(default_factory=dict)
    live_tool_usage: dict[str, int] = field(default_factory=dict)
    live_execution_report: ExecutionReport | None = None
    listeners: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list, repr=False)
    event_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue, repr=False)
    event_task: asyncio.Task[None] | None = field(default=None, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    approval_broker: "RunApprovalBroker | None" = field(default=None, repr=False)

    def to_snapshot(self) -> WorkflowRunSnapshot:
        return WorkflowRunSnapshot(
            run_id=self.run_id,
            run_kind=self.run_kind,
            status=self.status,
            scenario_id=self.scenario_id,
            scenario_name=self.scenario_name,
            input_payloads=self.input_payloads,
            started_at=self.started_at,
            completed_at=self.completed_at,
            trace_id=self.trace_id,
            session_id=self.session_id,
            approvals=[approval.to_snapshot() for approval in self.approvals.values()],
            event_count=len(self.events),
            events=self.events.copy(),
            live_execution_report=self.live_execution_report,
            result=self.result,
            error_message=self.error_message,
        )


class RunApprovalBroker:
    """Async approval broker used by the HITL tool during a browser-backed run."""

    def __init__(self, run: WorkflowRunState) -> None:
        self.run = run
        self._approval_lock = asyncio.Lock()

    async def request(self, prompt: str) -> str:
        """Create a pending approval request and wait for a response."""

        approval_id = uuid.uuid4().hex
        approval = PendingApprovalState(
            approval_id=approval_id,
            prompt=prompt,
            requested_at=datetime.now(timezone.utc),
            future=asyncio.get_running_loop().create_future(),
        )

        async with self._approval_lock:
            self.run.approvals[approval_id] = approval

        await self.run.event_queue.put(
            {
                "type": "approval_requested",
                "approval_id": approval_id,
                "prompt": prompt,
                "requested_at": approval.requested_at.isoformat(),
            }
        )

        return await approval.future

    async def submit_response(
        self,
        approval_id: str,
        response_text: str,
    ) -> ApprovalSnapshot:
        """Resolve a pending approval request."""

        async with self._approval_lock:
            approval = self.run.approvals.get(approval_id)
            if approval is None:
                raise ApprovalNotFoundError(
                    f"Approval '{approval_id}' was not found for run '{self.run.run_id}'."
                )

            if approval.status != "pending" or approval.future.done():
                raise ApprovalStateError(
                    f"Approval '{approval_id}' is no longer pending."
                )

            approval.status = "resolved"
            approval.response_text = response_text
            approval.resolved_at = datetime.now(timezone.utc)
            approval.future.set_result(response_text)

        await self.run.event_queue.put(
            {
                "type": "approval_resolved",
                "approval_id": approval_id,
                "response_text": response_text,
                "resolved_at": approval.resolved_at.isoformat(),
            }
        )

        return approval.to_snapshot()

    async def cancel_pending(self, reason: str) -> None:
        """Cancel any unresolved approvals when a run fails or shuts down."""

        cancelled: list[PendingApprovalState] = []
        async with self._approval_lock:
            for approval in self.run.approvals.values():
                if approval.status != "pending" or approval.future.done():
                    continue

                approval.status = "cancelled"
                approval.response_text = reason
                approval.resolved_at = datetime.now(timezone.utc)
                approval.future.set_exception(RuntimeError(reason))
                cancelled.append(approval)

        for approval in cancelled:
            await self.run.event_queue.put(
                {
                    "type": "approval_cancelled",
                    "approval_id": approval.approval_id,
                    "response_text": reason,
                    "resolved_at": approval.resolved_at.isoformat(),
                }
            )


class WorkflowRuntime:
    """In-memory run registry and execution coordinator for the UI-backed workflow."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRunState] = {}
        self._registry_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()

    def list_scenarios(self) -> list[ScenarioListItem]:
        """Return the current scenario catalog."""

        scenarios: list[ScenarioDefinition] = load_scenarios()
        return [
            ScenarioListItem(
                id=scenario.id,
                description=scenario.description,
                payload_count=len(scenario.payloads),
                payload_types=[
                    str(payload.get("payload_type") or "unknown")
                    for payload in scenario.payloads
                ],
            )
            for scenario in scenarios
        ]

    async def list_runs(self) -> list[WorkflowRunSnapshot]:
        """Return all known runs, newest first."""

        async with self._registry_lock:
            runs = sorted(
                self._runs.values(),
                key=lambda run: run.started_at,
                reverse=True,
            )
            return [run.to_snapshot() for run in runs]

    async def get_run(self, run_id: str) -> WorkflowRunSnapshot:
        """Return a single run snapshot."""

        async with self._registry_lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(f"Run '{run_id}' was not found.")
            return run.to_snapshot()

    async def start_scenario_run(
        self,
        scenario_id: str,
        *,
        reset_runtime_data: bool,
    ) -> WorkflowRunSnapshot:
        """Start an asynchronous scenario run."""

        scenario = get_scenario_definition(scenario_id)
        run = WorkflowRunState(
            run_id=uuid.uuid4().hex,
            run_kind="scenario",
            scenario_id=scenario.id,
            scenario_name=scenario.id.replace("_", " ").title(),
            input_payloads=scenario.payloads,
            started_at=datetime.now(timezone.utc),
            status="queued",
        )
        run.live_execution_report = self._build_live_execution_report_locked(run)

        async with self._registry_lock:
            self._ensure_no_active_run_locked()
            self._runs[run.run_id] = run
            run.event_task = asyncio.create_task(self._consume_run_events(run))
            run.task = asyncio.create_task(
                self._execute_scenario_run(
                    run=run,
                    scenario_id=scenario.id,
                    reset_runtime_data=reset_runtime_data,
                )
            )
            return run.to_snapshot()

    async def start_payload_run(
        self,
        payload: dict[str, Any],
        *,
        scenario_name: str | None,
        reset_runtime_data: bool,
    ) -> WorkflowRunSnapshot:
        """Start an asynchronous single-payload run."""

        run = WorkflowRunState(
            run_id=uuid.uuid4().hex,
            run_kind="payload",
            input_payloads=[payload],
            started_at=datetime.now(timezone.utc),
            status="queued",
            scenario_name=scenario_name,
        )
        run.live_execution_report = self._build_live_execution_report_locked(run)

        async with self._registry_lock:
            self._ensure_no_active_run_locked()
            self._runs[run.run_id] = run
            run.event_task = asyncio.create_task(self._consume_run_events(run))
            run.task = asyncio.create_task(
                self._execute_payload_run(
                    run=run,
                    payload=payload,
                    scenario_name=scenario_name,
                    reset_runtime_data=reset_runtime_data,
                )
            )
            return run.to_snapshot()

    async def submit_approval(
        self,
        run_id: str,
        approval_id: str,
        response_text: str,
    ) -> ApprovalSnapshot:
        """Resolve a pending approval for a run."""

        async with self._registry_lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(f"Run '{run_id}' was not found.")
            broker = run.approval_broker

        if broker is None:
            raise ApprovalNotFoundError(
                f"Run '{run_id}' does not have an active approval broker."
            )

        return await broker.submit_response(approval_id, response_text)

    async def subscribe(self, run_id: str) -> tuple[list[dict[str, Any]], asyncio.Queue[dict[str, Any]]]:
        """Subscribe to live events for a run and return the history plus queue."""

        listener: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._registry_lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(f"Run '{run_id}' was not found.")
            history = run.events.copy()
            run.listeners.append(listener)
            return history, listener

    async def unsubscribe(self, run_id: str, listener: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove an event subscriber from a run."""

        async with self._registry_lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.listeners = [item for item in run.listeners if item is not listener]

    async def shutdown(self) -> None:
        """Cancel all background tasks owned by the runtime."""

        async with self._registry_lock:
            runs = list(self._runs.values())

        for run in runs:
            if run.task and not run.task.done():
                run.task.cancel()
            if run.event_task and not run.event_task.done():
                await run.event_queue.put(_EVENT_SENTINEL)

        for run in runs:
            if run.task:
                with contextlib.suppress(asyncio.CancelledError):
                    await run.task
            if run.event_task:
                with contextlib.suppress(asyncio.CancelledError):
                    await run.event_task

    def _ensure_no_active_run_locked(self) -> None:
        for run in self._runs.values():
            if run.status in ACTIVE_RUN_STATUSES:
                raise RunConflictError(
                    f"Run '{run.run_id}' is still active with status '{run.status}'."
                )

    async def _execute_scenario_run(
        self,
        *,
        run: WorkflowRunState,
        scenario_id: str,
        reset_runtime_data: bool,
    ) -> None:
        async with self._execution_lock:
            broker = RunApprovalBroker(run)
            run.approval_broker = broker
            token = set_workflow_execution_context(
                WorkflowExecutionContext(run_id=run.run_id, approval_handler=broker)
            )
            try:
                await run.event_queue.put(
                    {
                        "type": "run_started",
                        "run_kind": run.run_kind,
                        "scenario_id": run.scenario_id,
                        "scenario_name": run.scenario_name,
                    }
                )
                result = await run_scenario_by_id(
                    scenario_id,
                    event_queue=run.event_queue,
                    reset_runtime_data_at_start=reset_runtime_data,
                )
                await self._mark_run_completed(run, result.model_dump(mode="json"))
            except Exception as exc:
                await self._mark_run_failed(run, str(exc))
            finally:
                await broker.cancel_pending("Run ended before approval was resolved.")
                reset_workflow_execution_context(token)
                await run.event_queue.put(_EVENT_SENTINEL)

    async def _execute_payload_run(
        self,
        *,
        run: WorkflowRunState,
        payload: dict[str, Any],
        scenario_name: str | None,
        reset_runtime_data: bool,
    ) -> None:
        async with self._execution_lock:
            broker = RunApprovalBroker(run)
            run.approval_broker = broker
            token = set_workflow_execution_context(
                WorkflowExecutionContext(run_id=run.run_id, approval_handler=broker)
            )
            try:
                await run.event_queue.put(
                    {
                        "type": "run_started",
                        "run_kind": run.run_kind,
                        "scenario_name": scenario_name,
                    }
                )
                result = await run_single_payload(
                    payload,
                    scenario_name=scenario_name,
                    event_queue=run.event_queue,
                    reset_runtime_data_at_start=reset_runtime_data,
                )
                await self._mark_run_completed(run, result.model_dump(mode="json"))
            except Exception as exc:
                await self._mark_run_failed(run, str(exc))
            finally:
                await broker.cancel_pending("Run ended before approval was resolved.")
                reset_workflow_execution_context(token)
                await run.event_queue.put(_EVENT_SENTINEL)

    async def _mark_run_completed(
        self,
        run: WorkflowRunState,
        result: dict[str, Any],
    ) -> None:
        run.result = result
        execution_report = result.get("execution_report")
        if isinstance(execution_report, dict):
            run.live_execution_report = ExecutionReport.model_validate(execution_report)
        trace_id = result.get("trace_id")
        session_id = result.get("session_id")
        if isinstance(trace_id, str) and trace_id:
            run.trace_id = trace_id
        if isinstance(session_id, str) and session_id:
            run.session_id = session_id
        run.completed_at = datetime.now(timezone.utc)
        run.status = "completed"

        await run.event_queue.put(
            {
                "type": "run_completed",
                "run_kind": run.run_kind,
                "trace_id": run.trace_id,
                "session_id": run.session_id,
            }
        )

    async def _mark_run_failed(self, run: WorkflowRunState, error_message: str) -> None:
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        run.status = "failed"

        await run.event_queue.put(
            {
                "type": "run_failed",
                "error_message": error_message,
            }
        )

    async def _consume_run_events(self, run: WorkflowRunState) -> None:
        while True:
            event = await run.event_queue.get()
            if event is _EVENT_SENTINEL:
                break
            if not isinstance(event, dict):
                continue
            await self._publish_event(run.run_id, event)

    async def _publish_event(self, run_id: str, event: dict[str, Any]) -> None:
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str):
            timestamp = datetime.now(timezone.utc).isoformat()

        normalized_event = {
            **event,
            "timestamp": timestamp,
        }

        async with self._registry_lock:
            run = self._runs.get(run_id)
            if run is None:
                return

            normalized_event["sequence"] = len(run.events) + 1
            normalized_event["run_id"] = run.run_id

            if "trace_id" in normalized_event and normalized_event["trace_id"]:
                run.trace_id = str(normalized_event["trace_id"])
            if "session_id" in normalized_event and normalized_event["session_id"]:
                run.session_id = str(normalized_event["session_id"])

            event_type = str(normalized_event.get("type") or "unknown")
            if event_type == "run_started":
                run.status = "running"
            elif event_type == "approval_requested":
                run.status = "awaiting_approval"
            elif event_type in {"approval_resolved", "approval_cancelled"}:
                pending_exists = any(
                    approval.status == "pending"
                    for approval in run.approvals.values()
                )
                if not pending_exists and run.status not in RUN_TERMINAL_STATUSES:
                    run.status = "running"
            elif event_type == "run_completed":
                run.status = "completed"
            elif event_type == "run_failed":
                run.status = "failed"

            self._update_live_execution_report_locked(run, normalized_event)
            run.events.append(normalized_event)
            listeners = run.listeners.copy()

        for listener in listeners:
            await listener.put(normalized_event)

    def _get_live_agent_state_locked(
        self,
        run: WorkflowRunState,
        agent_name: str,
    ) -> LiveAgentProgressState:
        agent_state = run.live_agents.get(agent_name)
        if agent_state is None:
            agent_state = LiveAgentProgressState(name=agent_name)
            run.live_agents[agent_name] = agent_state
        return agent_state

    def _update_live_execution_report_locked(
        self,
        run: WorkflowRunState,
        event: dict[str, Any],
    ) -> None:
        event_type = str(event.get("type") or "unknown")

        if event_type == "agent_start":
            agent_name = event.get("agent_name")
            if isinstance(agent_name, str) and agent_name:
                self._get_live_agent_state_locked(run, agent_name)

        if event_type == "agent_end":
            agent_name = event.get("agent_name")
            if isinstance(agent_name, str) and agent_name:
                agent_state = self._get_live_agent_state_locked(run, agent_name)
                model_name = event.get("model")
                if isinstance(model_name, str) and model_name:
                    agent_state.model = model_name
                agent_state.input_tokens += int(event.get("input_tokens") or 0)
                agent_state.output_tokens += int(event.get("output_tokens") or 0)
                agent_state.cached_tokens += int(event.get("cached_tokens") or 0)
                agent_state.reasoning_tokens += int(event.get("reasoning_tokens") or 0)
                agent_state.requests += int(event.get("requests") or 0)

        if event_type == "tool_start":
            tool_name = event.get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                run.live_tool_usage[tool_name] = run.live_tool_usage.get(tool_name, 0) + 1

        run.live_execution_report = self._build_live_execution_report_locked(run)

    def _build_live_execution_report_locked(
        self,
        run: WorkflowRunState,
    ) -> ExecutionReport:
        agent_reports: list[ExecutionReportAgent] = []
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        reasoning_tokens = 0
        requests = 0

        for agent_state in run.live_agents.values():
            input_tokens += agent_state.input_tokens
            output_tokens += agent_state.output_tokens
            cached_tokens += agent_state.cached_tokens
            reasoning_tokens += agent_state.reasoning_tokens
            requests += agent_state.requests

            agent_reports.append(
                ExecutionReportAgent(
                    name=agent_state.name,
                    model=agent_state.model,
                    total_tokens=agent_state.input_tokens + agent_state.output_tokens,
                    requests=agent_state.requests,
                    input_tokens=agent_state.input_tokens,
                    output_tokens=agent_state.output_tokens,
                    cached_tokens=agent_state.cached_tokens,
                    reasoning_tokens=agent_state.reasoning_tokens,
                    cost=calculate_cost(
                        agent_state.input_tokens,
                        agent_state.output_tokens,
                        agent_state.model,
                        agent_state.cached_tokens,
                    ),
                )
            )

        tool_costs = calculate_tool_costs(run.live_tool_usage)
        tool_reports = [
            ExecutionReportTool(
                name=tool_name,
                calls=count,
                cost=tool_costs.get(tool_name, 0.0),
            )
            for tool_name, count in sorted(run.live_tool_usage.items())
        ]

        totals = TelemetryTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=input_tokens + output_tokens,
            requests=requests,
        )
        total_agent_cost = sum(agent.cost for agent in agent_reports)
        total_tool_cost = sum(tool.cost for tool in tool_reports)

        return ExecutionReport(
            started_at=run.started_at,
            duration_seconds=(
                (run.completed_at or datetime.now(timezone.utc)) - run.started_at
            ).total_seconds(),
            agent_count=len(agent_reports),
            agents=agent_reports,
            tools=tool_reports,
            totals=totals,
            total_agent_cost=total_agent_cost,
            total_tool_cost=total_tool_cost,
            total_cost=total_agent_cost + total_tool_cost,
        )


workflow_runtime = WorkflowRuntime()


def encode_sse_event(event: dict[str, Any]) -> str:
    """Encode a single run event as an SSE message."""

    payload = json.dumps(event)
    return f"data: {payload}\n\n"
