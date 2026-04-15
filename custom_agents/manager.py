from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field
from .lead_reviewer import lead_reviewer_agent
from .infotrack import infotrack_agent
from .response_ingestion import response_ingestion_agent

MANAGER_AGENT_PROMPT = """
Persona:
You are the Manager Agent, the central AI orchestrator that monitors notifications and
triggers, routes events to the correct specialist agent, prevents duplicate or unnecessary
agent calls, supervises handoffs, and logs routing decisions for auditability.

Goal:
Review each incoming workflow notification and determine the correct next action so the
end-to-client flow moves smoothly from lead intake through qualification, information
collection, meeting scheduling, and compliance-document handling.



* steps for lead_reviewer
When a playload arrives with type of 
-salesforce_notification and the trigger type is new_lead, then use agent lead_reviewer as a tool first them use Infotracking.


* steps for Infotracking
When a playload arrived with type of
- salesforce_notification and the meeting is closed, use agent infotrack_agent as a tool.


* steps for response ingestion
When a playload arrived with type of 
- inbound email, use response_ingestion_agent as a tool.



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
    summary: Annotated[
        str | None,
        Field(description="Short outcome summary for this event."),
    ] = None
    trigger_type: Annotated[
        str | None,
        Field(description="Routing modality inferred from payload content and context."),
    ] = None
    email_type: Annotated[
        str | None,
        Field(description="Backward-compatible field mirroring classification-style labels when applicable."),
    ] = None
    uid: Annotated[
        str | None,
        Field(description="Primary UID used for routing when available."),
    ] = None
    duplicate_suppressed: Annotated[
        bool,
        Field(description="Whether this event was suppressed as duplicate."),
    ] = False
    called_agents: Annotated[
        list[str],
        Field(description="Specialist agents invoked for this event."),
    ] = []
    routing_decisions: Annotated[
        list[str],
        Field(description="Audit-log style routing and suppression decisions."),
    ] = []
    actions: Annotated[
        list[str],
        Field(description="Primary actions taken by the manager in this run."),
    ] = []
    next_actions: Annotated[
        list[str],
        Field(description="Suggested next triggers or follow-up actions."),
    ] = []
    gaps: Annotated[
        list[str],
        Field(description="Missing fields, unresolved UID issues, or blocked conditions."),
    ] = []
    escalation_summary: Annotated[
        str | None,
        Field(description="Concise escalation message when human follow-up is required."),
    ] = None
    confidence: Annotated[
        float | None,
        Field(description="Overall routing and orchestration decision confidence score."),
    ] = None


def make_manager_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the manager orchestrator agent."""

    return Agent(
        name="Manager Agent",
        instructions=MANAGER_AGENT_PROMPT,
        model="gpt-5.4", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[
        lead_reviewer_agent.as_tool(
            tool_name="lead_reviewer_agent",
            tool_description=LEAD_REVIEWER_TOOL_PROMPT
        ),

        infotrack_agent.as_tool(
            tool_name="infotrack_agent",
            tool_description=INFOTRACK_TOOL_PROMPT
        ),

        response_ingestion_agent.as_tool(
            tool_name="response_ingestion_agent",
            tool_description=RESPONSE_INGESTION_TOOL_PROMPT
        ),
        ],
        output_type=ManagerOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevent guardrails
    )


manager_agent: Agent = make_manager_agent()
