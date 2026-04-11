from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field

INFOTRACK_AGENT_PROMPT = """
TODO: 
- Define Response Ingestion Persona
- Describe the goal for the response ingestion agent
- Document tool usage expectations and guideliens if tools are introduced
- Provide context for high-level scenarios the agent might encounter
- Outline the ingestion procedure for processing inbound emails, and all subsequent agent actions
- Add rules for tool calls, confidence scoring, ambiguity handling, and failure states.
""".strip()


class InfoTrackOutput(BaseModel):
    """Structured response returned by the InfoTrack agent."""
    # TODO: Define the structured response for all values below

    status: Annotated[
        Literal["completed", "partial", "failed"],
        Field(description="Overall InfoTrack workflow status."),
    ]
    # TODO: Add `scenario` for the scenario classification for the current prospect or client
    # TODO: Add `lead_or_client_id` for the Salesforce lead or client identifier when available
    # TODO: Add `meeting_required` for whether scheduling outreach is required in this run
    # TODO: Add `meeting_time_options` for advisor-validated meeting time options included in outreach
    # TODO: Add `meeting_times_source_validated` for whether all listed meeting options came directly from advisor calendar availability
    # TODO: Add `missing_information_requests` for missing data requested from the client, including Form 1500 and goal-related items when applicable
    # TODO: Add `zocks_action_items` for relevant follow-up items identified from Zocks review
    # TODO: Add `email_sent` for whether client outreach email was sent
    # TODO: Add `email_summary` for a brief summary of outreach content sent to the client
    # TODO: Add `actions_taken` for tracking ordered actions completed during this workflow run
    # TODO: Add `gaps` for noting missing fields, contradictory Salesforce data, or non-blocking constraints
    # TODO: Add `escalation_required` for whether human intervention is required
    # TODO: Add `escalation_summary` for a concise handoff note when the workflow is blocked
    # TODO: Add `confidence` for the final scenario and outreach decision confidence score


def make_infotrack_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the InfoTrack agent."""

    return Agent(
        name="InfoTrack Agent",
        instructions=INFOTRACK_AGENT_PROMPT,
        model="gpt-5.4-mini", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[], # TODO: add relevant tools
        output_type=InfoTrackOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


infotrack_agent: Agent = make_infotrack_agent()
