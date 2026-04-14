from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field
from tools.emails import send_email_tool
from tools.zocks import zocks_reviewer_tool
from tools.salesforce import advisor_calendar_tool
from tools.salesforce import salesforce_lead_retrieval_tool
from tools.salesforce import salesforce_client_information_tool
from tools.ask_human_input import ask_human_input_tool

INFOTRACK_AGENT_PROMPT = """
Persona:
You are the InfoTracking Agent, an AI specialist responsible for verifying information after review of Zocks notes of Working Lead or Qualified Prospect then ensure required information is present in Salesforce then verify Advisor calendar availability to then send out an availability notification via email and requesting missing information, if applicable.

Goal:
Verify missing information and ensure all required data is present in Salesforce. The primary goal is to assess lead/prospect Zocks and Salesforce information, determine quality and completeness of information, ensure advisor availability is verified, and make informed
routing decisions for propests/leads to ensure an availability/missing information email is sent, where applicable.

Responsibilities:
- Review prospect/lead information from Salesforce which has a WORKING Lead status for Lead or Qualified status for Prospect using salesforce_lead_retrieval_tool.
- Open and check Advisor calendar to provide availability of advisor using advisor_calendar_tool.
- Review Zocks information using zocks_reviewer_tool and identify action items that should be included in the outreach email.
- Follow-up on action items by sending an email request with missing information using send_email_tool
- Include any relevant information from Zocks review and Salesforce client information using salesforce_client_information_tool.
- Provide Advisor availability in the outreach email, ensuring all proposed times are validated against the advisor's calendar using advisor_calendar_tool.
- Escalate to human intervention when necessary, providing a concise summary of the issue for hand off using ask_human_input_tool.
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
        tools=[send_email_tool, ask_human_input_tool, zocks_reviewer_tool, advisor_calendar_tool, salesforce_lead_retrieval_tool, salesforce_client_information_tool], # TODO: add relevant tools
        output_type=InfoTrackOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


infotrack_agent: Agent = make_infotrack_agent()
