"""FastAPI shim to trigger the workflow via HTTP.

Install deps:
    uv add fastapi uvicorn
Run locally:
    uv run uvicorn api:app --reload
Open docs:
    http://localhost:8000/docs
Request body (paste into /docs):
{
    "trigger_source": "email",
    "message_id": "zoom-inv-286764152e",
    "metadata": {}
}

Example:
    curl -X POST "http://localhost:8000/agents/run" \
      -H "accept: application/json" \
      -H "Content-Type: application/json" \
      -d '{
        "trigger_source": "email",
        "message_id": "zoom-inv-286764152e",
        "metadata": {}
      }'
"""

from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, status
from agents import (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
)
from pydantic import BaseModel, Field

from custom_agents import ManagerOutput
from main import run_manager
from utils import emit_execution_summary

app = FastAPI(
    title="First Command Lead Intake Agent API",
    description="API surface area that runs the Invoice Approval Manager workflow.",
)


class ManagerRunResponse(BaseModel):
    """Schema returned by the run endpoint with run context."""

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


@app.get("/", tags=["health"])
async def read_root() -> dict[str, str]:
    """Confirm the service is alive."""
    return {"service": "firstcommand-lead-ingestion", "status": "ok"}


@app.post(
    "/agents/run",
    tags=["agents"],
    response_model=ManagerRunResponse,
    summary="Execute the Invoice Approval Manager workflow",
    status_code=status.HTTP_200_OK,
)
async def run_agents_endpoint(
    payload: dict[str, Any],
    trace_id: str | None = None,
    session_id: str | None = None,
    scenario_name: str | None = None,
) -> ManagerRunResponse:
    """Execute the Invoice Approval Manager for the provided email payload."""

    try:
        output, run_hooks, resolved_trace_id, resolved_session_id = await run_manager(
            payload,
            trace_id=trace_id,
            session_id=session_id,
        )
        summary = run_hooks.export_summary()
        emit_execution_summary(summary)
        return ManagerRunResponse(
            manager_output=output,
            input_payload=payload,
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
            scenario_name=scenario_name,
        )
    except InputGuardrailTripwireTriggered as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request blocked because the email violated an input guardrail.",
        ) from exc
    except OutputGuardrailTripwireTriggered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent response was rejected by an output guardrail.",
        ) from exc
    except ToolInputGuardrailTripwireTriggered as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tool execution was blocked by an input guardrail.",
        ) from exc
    except ToolOutputGuardrailTripwireTriggered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tool execution was rejected by an output guardrail.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed unexpectedly: {exc}",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
