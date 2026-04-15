from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field
from tools.emails import email_read_tool, send_email_tool
from tools.laserfiche import laserfiche_uploader_tool
from tools.salesforce import salesforce_document_uploader_tool, salesforce_client_input_tool, meeting_scheduler_tool, salesforce_lead_retrieval_tool
from tools.document_processor import document_processor_tool
from tools.ask_human_input import ask_human_input_tool





RESPONSE_INGESTION_AGENT_PROMPT = """
TODO
Persona:
You are the Response Ingestion Agent, an AI specialist responsible for handleing response emails from clients and booking meetings with clients, uploading documetents, classifying documents and updating lead data in Salesforce.

Goal:
Handling response emails and ingest data from email and/or documents, classifying documents and uploading documents. You are able to schedule meeting with the lead and update record in Salesforce. Provide short summary of your decisions and reasoning for each event.

Responsibilities:
- When a meeting confirmation email is receved from the lead/prospect/client read the email using email_read_tool, then use meeting_scheduler_tool to schedule the meeting.
- When a client response email contains attachments, process and classify these attachments using the document_processor_tool
- Upload processed and classified attachement into laserfiche using laserfiche_uploader_tool if the attachment is related to complience.
- Upload processed attachement into Salesforce using salesforce_document_uploader_tool


- When a email response is receved from the client with requested optional information, then ingest that data into Salesforce using salesforce_client_input_tool along with exisitng lead/client/prospect populated fields retreved using salesforce_lead_retrieval_tool, when is lead status is working and the record has minimum information, then update the lead_status to Qualifed.


- If there are any data inconsistencies or issues in the attachment or email body, reach out to client about these inconsistencies, incomplete or issues in the data using send_email_tool.
- If you come across any ambigous attachments use ask_human_input_tool.
""".strip()


class ResponseIngestionOutput(BaseModel):
    """ Structured response returned by the Response Ingestion agent."""
    # TODO: Define the structured response for all values below

    status: Annotated[
        Literal["completed", "partial", "failed"],
        Field(description="Overall response-ingestion workflow status."),
    ]   
    # TODO: Add `response_classification` for classifying the inboudn resposne as one of 5 types 
    response_classification: Annotated[
        str | None,
        Field(description="Classification of the inbound response."),
    ] = None
    # TODO: Add `lead_or_client_id` to identify UID as a lead or client when known
    lead_or_client_id: Annotated[
        str | None,
        Field(description="Lead or client identifier when known."),
    ] = None
    # TODO: Add `meeting_confirmation_detected` for whether explicit meeting availability or acceptance was detected
    meeting_confirmation_detected: Annotated[
        bool,
        Field(description="Whether explicit meeting availability or acceptance was detected."),
    ] = False
    # TODO: Add `meeting_scheduled` for whether a meeting was actually scheduled in this run
    meeting_scheduled: Annotated[
        bool,
        Field(description="Whether a meeting was actually scheduled in this run."),
    ] = False


    # TODO: Add `scheduled_meeting_reference` for capturing the meeting identifier or booking reference when scheduled
    scheduled_meeting_reference: Annotated[
        str | None,
        Field(description="Meeting identifier or booking reference when scheduled."),
    ] = None
    # TODO: Add `status_changes_applied` for tracking status transitions applied, such as `Working` to `Qualified`
    status_changes_applied: Annotated[
        str | None,
        Field(description="Status transitions applied during processing."),
    ] = []
    # # TODO: Add `extracted_information` for capturing key extracted details from email body and documents
    # extracted_information: Annotated[
    #     list[str],
    #     Field(description="Key extracted details from the email body and documents."),
    # ] = []
    # # TODO: Add `attachment_metadata` for summarizing attachment OCR/classification metadata
    # attachment_metadata: Annotated[
    #     list[str],
    #     Field(description="Attachment OCR and classification metadata summary."),
    # ] = []



    # TODO: Add `validation_issues` for logging completeness, consistency, or relevance issues found during validation
    validation_issues: Annotated[
        list[str],
        Field(description="Completeness, consistency, or relevance issues found during validation."),
    ] = []
    # TODO: Add `follow_up_required` for whether a follow-up email was required
    follow_up_required: Annotated[
        bool,
        Field(description="Whether a follow-up email was required."),
    ] = False
    # TODO: Add `follow_up_email_sent` for whether the follow-up email was sent
    follow_up_email_sent: Annotated[
        bool,
        Field(description="Whether the follow-up email was sent."),
    ] = False
    # TODO: Add `laserfiche_upload_performed` for whether any document was uploaded to Laserfiche
    laserfiche_upload_performed: Annotated[
        bool,
        Field(description="Whether any document was uploaded to Laserfiche."),
    ] = False
    # TODO: Add `uploaded_document_references` for storing Laserfiche document references for successful uploads
    uploaded_document_references: Annotated[
        list[str],
        Field(description="Laserfiche document references for successful uploads."),
    ] = []
    # TODO: Add `compliance_review_needed` for whether compliance review is required due to uncertain document classification
    compliance_review_needed: Annotated[
        bool,
        Field(description="Whether compliance review is required due to uncertain document classification."),
    ] = False
    # TODO: Add `salesforce_updated` for whether Salesforce records were updated
    salesforce_updated: Annotated[
        bool,
        Field(description="Whether Salesforce records were updated."),
    ] = False
    # TODO: Add `salesforce_log_summary` for summarizing actions logged in Salesforce
    salesforce_log_summary: Annotated[
        str | None,
        Field(description="Summary of actions logged in Salesforce."),
    ] = None
    # TODO: Add `actions_taken` for tracking ordered actions completed in this response-ingestion run
    actions_taken: Annotated[
        list[str],
        Field(description="Ordered actions completed in this response-ingestion run."),
    ] = []
    # TODO: Add `gaps` for noting missing fields, unclear response content, or non-blocking constraints
    gaps: Annotated[
        list[str],
        Field(description="Missing fields, unclear response content, or non-blocking constraints."),
    ] = []
    # TODO: Add `escalation_required` for whether human intervention is required
    escalation_required: Annotated[
        bool,
        Field(description="Whether human intervention is required."),
    ] = False
    # TODO: Add `escalation_summary` for a concise handoff note when the workflow is blocked
    escalation_summary: Annotated[
        str | None,
        Field(description="Concise handoff note when the workflow is blocked."),
    ] = None
    # TODO: Add `confidence` for the final response classification and workflow decision confidence score
    confidence: Annotated[
        float | None,
        Field(description="Final response classification and workflow decision confidence score."),
    ] = None


def make_response_ingestion_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the Response Ingestion agent."""

    return Agent(
        name="Response Ingestion Agent",
        instructions=RESPONSE_INGESTION_AGENT_PROMPT,
        model="gpt-5.4", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[
            email_read_tool,
            laserfiche_uploader_tool,
            salesforce_document_uploader_tool,
            salesforce_client_input_tool,
            meeting_scheduler_tool,
            send_email_tool,
            document_processor_tool,
            ask_human_input_tool,
            salesforce_lead_retrieval_tool
            ], # TODO: add relevant tools
        output_type=ResponseIngestionOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


response_ingestion_agent: Agent = make_response_ingestion_agent()
