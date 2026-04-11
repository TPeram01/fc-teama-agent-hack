from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field


RESPONSE_INGESTION_AGENT_PROMPT = """
TODO: 
- Define Response Ingestion Persona
- Describe the goal for the response ingestion agent
- Document tool usage expectations and guideliens if tools are introduced
- Provide context for high-level scenarios the agent might encounter
- Outline the ingestion procedure for processing inbound emails, and all subsequent agent actions
- Add rules for tool calls, confidence scoring, ambiguity handling, and failure states.
""".strip()


class ResponseIngestionOutput(BaseModel):
    """ Structured response returned by the Response Ingestion agent."""
    # TODO: Define the structured response for all values below

    status: Annotated[
        Literal["completed", "partial", "failed"],
        Field(description="Overall response-ingestion workflow status."),
    ]
    # TODO: Add `response_classification` for classifying the inboudn resposne as one of 5 types 
    # TODO: Add `lead_or_client_id` to identify UID as a lead or client when known
    # TODO: Add `meeting_confirmation_detected` for whether explicit meeting availability or acceptance was detected
    # TODO: Add `meeting_scheduled` for whether a meeting was actually scheduled in this run
    # TODO: Add `scheduled_meeting_reference` for capturing the meeting identifier or booking reference when scheduled
    # TODO: Add `status_changes_applied` for tracking status transitions applied, such as `Working` to `Qualified`
    # TODO: Add `extracted_information` for capturing key extracted details from email body and documents
    # TODO: Add `attachment_metadata` for summarizing attachment OCR/classification metadata
    # TODO: Add `validation_issues` for logging completeness, consistency, or relevance issues found during validation
    # TODO: Add `follow_up_required` for whether a follow-up email was required
    # TODO: Add `follow_up_email_sent` for whether the follow-up email was sent
    # TODO: Add `laserfiche_upload_performed` for whether any document was uploaded to Laserfiche
    # TODO: Add `uploaded_document_references` for storing Laserfiche document references for successful uploads
    # TODO: Add `compliance_review_needed` for whether compliance review is required due to uncertain document classification
    # TODO: Add `salesforce_updated` for whether Salesforce records were updated
    # TODO: Add `salesforce_log_summary` for summarizing actions logged in Salesforce
    # TODO: Add `actions_taken` for tracking ordered actions completed in this response-ingestion run
    # TODO: Add `gaps` for noting missing fields, unclear response content, or non-blocking constraints
    # TODO: Add `escalation_required` for whether human intervention is required
    # TODO: Add `escalation_summary` for a concise handoff note when the workflow is blocked
    # TODO: Add `confidence` for the final response classification and workflow decision confidence score


def make_response_ingestion_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the Response Ingestion agent."""

    return Agent(
        name="Response Ingestion Agent",
        instructions=RESPONSE_INGESTION_AGENT_PROMPT,
        model="gpt-5.4", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[], # TODO: add relevant tools
        output_type=ResponseIngestionOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


response_ingestion_agent: Agent = make_response_ingestion_agent()
