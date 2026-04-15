"""FastAPI surface for scenario execution, live events, and HITL approvals.

Run locally:
    uv run uvicorn api:app --reload
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from custom_agents import ManagerOutput
from scripts.reset_runtime_data import restore_runtime_data
from workflow.runner import run_single_payload
from workflow.runtime import (
    ApprovalNotFoundError,
    ApprovalSnapshot,
    ApprovalStateError,
    RunConflictError,
    RunNotFoundError,
    ScenarioListItem,
    WorkflowRunSnapshot,
    encode_sse_event,
    workflow_runtime,
)
from workflow.timeline import TimelineEntry, build_run_timeline


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await workflow_runtime.shutdown()


app = FastAPI(
    title="First Command Workflow Control Plane",
    description=(
        "Browser-facing control plane for scenario execution, event streaming, "
        "and human-in-the-loop approvals."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREVIEW_ROOTS: tuple[Path, ...] = (Path("data/sample_input").resolve(),)


class ManagerRunResponse(BaseModel):
    """Synchronous response returned by the compatibility run endpoint."""

    manager_output: Annotated[
        ManagerOutput,
        Field(..., description="Structured output from the manager agent."),
    ]
    input_payload: Annotated[
        dict[str, Any],
        Field(..., description="Input payload provided to the workflow."),
    ]
    trace_id: Annotated[
        str,
        Field(..., description="Trace identifier for observability tooling."),
    ]
    session_id: Annotated[
        str,
        Field(..., description="Session identifier used for the run."),
    ]
    scenario_name: Annotated[
        str | None,
        Field(default=None, description="Scenario name, if provided by the caller."),
    ]


class StartRunRequest(BaseModel):
    """Shared options for starting a new asynchronous run."""

    reset_runtime_data: Annotated[
        bool,
        Field(
            default=True,
            description="Whether to restore mutable runtime JSON files before execution.",
        ),
    ]


class StartPayloadRunRequest(StartRunRequest):
    """Request body used to start a one-off payload run."""

    payload: Annotated[dict[str, Any], Field(default_factory=dict)]
    scenario_name: Annotated[
        str | None,
        Field(default=None, description="Optional display name for the run."),
    ]


class ApprovalSubmissionRequest(BaseModel):
    """Payload used to resolve a pending HITL approval."""

    decision: Annotated[
        Literal["approve", "reject"] | None,
        Field(
            default=None,
            description="Optional shortcut that maps to a default response string.",
        ),
    ]
    response_text: Annotated[
        str | None,
        Field(
            default=None,
            description="Explicit text returned to the tool. Overrides the decision shortcut when provided.",
        ),
    ]


class RuntimeResetResponse(BaseModel):
    """Response returned when runtime JSON files are restored."""

    restored_paths: Annotated[list[str], Field(default_factory=list)]


def _normalize_approval_response(request: ApprovalSubmissionRequest) -> str:
    if request.response_text is not None and request.response_text.strip():
        return request.response_text.strip()
    if request.decision == "approve":
        return "approved"
    if request.decision == "reject":
        return "declined"
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Provide either response_text or decision to resolve an approval.",
    )


def _resolve_preview_path(path: str) -> Path:
    resolved = Path(path).resolve(strict=False)
    for allowed_root in PREVIEW_ROOTS:
        if resolved.is_relative_to(allowed_root):
            return resolved

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="File path is not allowed for preview.",
    )


@app.get("/", tags=["health"])
async def read_root() -> dict[str, str]:
    """Confirm the service is alive."""

    return {"service": "firstcommand-control-plane", "status": "ok"}


@app.get(
    "/scenarios",
    tags=["scenarios"],
    response_model=list[ScenarioListItem],
    summary="List available runnable scenarios",
)
async def list_scenarios_endpoint() -> list[ScenarioListItem]:
    """Return the current scenario catalog."""

    return workflow_runtime.list_scenarios()


@app.get(
    "/runs",
    tags=["runs"],
    response_model=list[WorkflowRunSnapshot],
    summary="List known workflow runs",
)
async def list_runs_endpoint() -> list[WorkflowRunSnapshot]:
    """Return known workflow runs."""

    return await workflow_runtime.list_runs()


@app.get(
    "/runs/{run_id}",
    tags=["runs"],
    response_model=WorkflowRunSnapshot,
    summary="Fetch the current state of a workflow run",
)
async def get_run_endpoint(run_id: str) -> WorkflowRunSnapshot:
    """Return a single run snapshot."""

    try:
        return await workflow_runtime.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get(
    "/runs/{run_id}/timeline",
    tags=["runs"],
    response_model=list[TimelineEntry],
    summary="Fetch the enriched timeline for a workflow run",
)
async def get_run_timeline_endpoint(run_id: str) -> list[TimelineEntry]:
    """Return enriched timeline records for a workflow run."""

    try:
        snapshot = await workflow_runtime.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return build_run_timeline(snapshot.model_dump(mode="json"))


@app.get(
    "/files/preview",
    tags=["files"],
    summary="Preview an attachment referenced by the workflow timeline",
)
async def preview_file_endpoint(
    path: Annotated[str, Query(min_length=1)],
) -> FileResponse:
    """Return a safe inline preview for supported sample-input files."""

    resolved = _resolve_preview_path(path)
    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview file '{path}' was not found.",
        )

    media_type, _ = mimetypes.guess_type(str(resolved))
    return FileResponse(
        path=resolved,
        media_type=media_type or "application/octet-stream",
        filename=resolved.name,
        headers={"Content-Disposition": f'inline; filename="{resolved.name}"'},
    )


@app.post(
    "/runs/scenarios/{scenario_id}",
    tags=["runs"],
    response_model=WorkflowRunSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a scenario run",
)
async def start_scenario_run_endpoint(
    scenario_id: str,
    request: StartRunRequest,
) -> WorkflowRunSnapshot:
    """Start an asynchronous scenario run."""

    try:
        return await workflow_runtime.start_scenario_run(
            scenario_id,
            reset_runtime_data=request.reset_runtime_data,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RunConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@app.post(
    "/runs/payload",
    tags=["runs"],
    response_model=WorkflowRunSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a single-payload run",
)
async def start_payload_run_endpoint(
    request: StartPayloadRunRequest,
) -> WorkflowRunSnapshot:
    """Start an asynchronous single-payload run."""

    try:
        return await workflow_runtime.start_payload_run(
            request.payload,
            scenario_name=request.scenario_name,
            reset_runtime_data=request.reset_runtime_data,
        )
    except RunConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@app.get(
    "/runs/{run_id}/events",
    tags=["runs"],
    summary="Subscribe to live workflow events via SSE",
)
async def stream_run_events_endpoint(run_id: str) -> StreamingResponse:
    """Stream historical and live events for a run over SSE."""

    try:
        snapshot = await workflow_runtime.get_run(run_id)
        history, listener = await workflow_runtime.subscribe(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    async def event_generator() -> AsyncIterator[str]:
        try:
            for event in history:
                yield encode_sse_event(event)

            if snapshot.status in {"completed", "failed"}:
                return

            while True:
                try:
                    event = await asyncio.wait_for(listener.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                yield encode_sse_event(event)
                event_type = str(event.get("type") or "unknown")
                if event_type in {"run_completed", "run_failed"}:
                    return
        finally:
            await workflow_runtime.unsubscribe(run_id, listener)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/runs/{run_id}/approvals/{approval_id}",
    tags=["approvals"],
    response_model=ApprovalSnapshot,
    summary="Resolve a pending HITL approval",
)
async def resolve_approval_endpoint(
    run_id: str,
    approval_id: str,
    request: ApprovalSubmissionRequest,
) -> ApprovalSnapshot:
    """Resolve a pending approval with browser-supplied text."""

    response_text = _normalize_approval_response(request)

    try:
        return await workflow_runtime.submit_approval(
            run_id=run_id,
            approval_id=approval_id,
            response_text=response_text,
        )
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ApprovalStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@app.post(
    "/runtime/reset",
    tags=["runtime"],
    response_model=RuntimeResetResponse,
    summary="Reset mutable runtime JSON files to their preserved originals",
)
async def reset_runtime_endpoint() -> RuntimeResetResponse:
    """Restore mutable runtime JSON files to their clean baseline."""

    restored_paths = restore_runtime_data()
    return RuntimeResetResponse(
        restored_paths=[str(path) for path in restored_paths]
    )


@app.post(
    "/agents/run",
    tags=["agents"],
    response_model=ManagerRunResponse,
    summary="Execute a single payload synchronously",
    status_code=status.HTTP_200_OK,
)
async def run_agents_endpoint(
    payload: dict[str, Any],
    scenario_name: str | None = None,
) -> ManagerRunResponse:
    """Execute the manager workflow synchronously for a single payload."""

    try:
        result = await run_single_payload(
            payload=payload,
            scenario_name=scenario_name,
            reset_runtime_data_at_start=False,
        )
        return ManagerRunResponse(
            manager_output=result.manager_output,
            input_payload=result.input_payload,
            trace_id=result.trace_id,
            session_id=result.session_id,
            scenario_name=scenario_name,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed unexpectedly: {exc}",
        ) from exc


@app.options("/runs/{run_id}/events", include_in_schema=False)
async def options_run_events_endpoint(run_id: str) -> Response:
    """Handle preflight requests for the SSE endpoint."""

    return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
