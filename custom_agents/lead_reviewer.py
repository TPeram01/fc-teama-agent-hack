from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field


LEAD_REVIEWER_AGENT_PROMPT = """
TODO: 
- Define Response Ingestion Persona
- Describe the goal for the response ingestion agent
- Document tool usage expectations and guideliens if tools are introduced
- Outline the ingestion procedure for processing inbound emails, and all subsequent agent actions
- Add rules for tool calls, confidence scoring, ambiguity handling, and failure states.
""".strip()


class LeadReviewerOutput(BaseModel):
    """Structured response returned by the lead reviewer agent."""
    # TODO: Define the structured response for all values below

    status: Annotated[
        Literal["completed", "partial", "failed"],
        Field(description="Overall lead-review workflow status."),
    ]
    # TODO: Add `lead_id` for the Salesforce lead identifier when available
    # TODO: Add `lead_disposition` for the final disposition of the reviewed lead
    # TODO: Add `lead_status_after_review` for the final Salesforce lead status after processing, such as `Working`
    # TODO: Add `selected_branch_type` for the branch-routing decision used for advisor assignment
    # TODO: Add `assigned_advisor_id` for the assigned advisor identifier when a qualified lead is routed
    # TODO: Add `assigned_advisor_name` for the assigned advisor display name when available
    # TODO: Add `summary_note` for a brief summary note of actions taken for this lead
    # TODO: Add `actions_taken` for tracking ordered actions completed during lead review
    # TODO: Add `gaps` for noting missing lead data, routing ambiguities, or other non-blocking gaps
    # TODO: Add `escalation_required` for whether human intervention is required
    # TODO: Add `escalation_summary` for a concise handoff note when the workflow is blocked
    # TODO: Add `confidence` for the final lead review and advisor assignment decision confidence score


def make_lead_reviewer_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the lead reviewer agent."""

    return Agent(
        name="Lead Reviewer Agent",
        instructions=LEAD_REVIEWER_AGENT_PROMPT,
        model="gpt-5.4-nano", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[], # TODO: add relevant tools
        output_type=LeadReviewerOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


lead_reviewer_agent: Agent = make_lead_reviewer_agent()
