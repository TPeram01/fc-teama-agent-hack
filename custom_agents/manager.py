from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field

MANAGER_AGENT_PROMPT = """
Persona:
You are the Manager Agent, the central AI orchestrator that monitors notifications and
triggers, routes events to the correct specialist agent, prevents duplicate or unnecessary
agent calls, supervises handoffs, and logs routing decisions for auditability.

Goal:
Review each incoming workflow notification and determine the correct next action so the
end-to-client flow moves smoothly from lead intake through qualification, information
collection, meeting scheduling, and compliance-document handling.
""".strip()
# TODO: Rewrite Manager Agent Prompt
# - Provide context for supported workflows, triggers, high-level scenarios
# - Provide inference and routing rules for handling different payloads and proceeding actions
# - Add constraints and requirements for confidence scoring, ambiguity handling, and failure states.

LEAD_REVIEWER_TOOL_PROMPT = """
TODO: Describe Lead Reviewer tool usage, expectations responsibilitys, and agent inputs/outputs.
""".strip()

RESPONSE_INGESTION_TOOL_PROMPT = """
TODO: Describe Response Ingestion tool usage, expectations responsibilitys, and agent inputs/outputs.
""".strip()

INFOTRACK_TOOL_PROMPT = """
TODO: Describe Infotrack tool usage, expectations responsibilitys, and agent inputs/outputs.
""".strip()

class ManagerOutput(BaseModel):
    """Summary of routing decisions and specialist orchestration outcomes."""

    status: Annotated[
        Literal["completed", "ignored", "failed"],
        Field(description="Overall manager execution status for this event."),
    ]
    # TODO: Add `summary` for a short outcome summary for this event
    # TODO: Add `trigger_type` for the routing modality inferred from payload content/context, not from a required hard-coded label
    # TODO: Add `email_type` for a backward-compatible field mirroring classification-style labels when applicable
    # TODO: Add `uid` for the primary UID used for routing when available
    # TODO: Add `duplicate_suppressed` for whether this event was suppressed as duplicate
    # TODO: Add `called_agents` for tracking specialist agents that were invoked for this event
    # TODO: Add `routing_decisions` for audit-log style routing and suppression decisions
    # TODO: Add `actions` for tracking primary actions taken by the manager in this run
    # TODO: Add `next_actions` for suggested next trigger(s) or follow-up actions
    # TODO: Add `gaps` for noting missing fields, unresolved UID issues, or blocked conditions
    # TODO: Add `escalation_summary` for a concise escalation message when human follow-up is required
    # TODO: Add `confidence` for the overall routing and orchestration decision confidence score


def make_manager_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the manager orchestrator agent."""

    return Agent(
        name="Manager Agent",
        instructions=MANAGER_AGENT_PROMPT,
        model="gpt-5.4", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[ # TODO 
        ],
        output_type=ManagerOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevent guardrails
    )


manager_agent: Agent = make_manager_agent()
