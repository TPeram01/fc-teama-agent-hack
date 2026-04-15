from typing import Annotated, Literal

from agents import Agent, ModelSettings, RunHooks
from pydantic import BaseModel, Field
from tools.salesforce import salesforce_lead_retrieval_tool #Retrive all leads current informaiton
from tools.salesforce import salesforce_lead_query_tool # To check if the lead is duplicate
from tools.salesforce import salesforce_client_query_tool # To check if the lead is already a client
from tools.salesforce import salesforce_delete_lead_tool # To delete the lead if it is duplicate or a client
#from tools.salesforce import salesforce_advisor_db_get_tool   
from tools.salesforce import salesforce_lead_status_update_tool
from tools.salesforce import salesforce_advisor_search_tool
from tools.salesforce import salesforce_advisor_assignment_tool
from tools.ask_human_input import ask_human_input_tool


LEAD_REVIEWER_AGENT_PROMPT = """
Persona:
You are the Lead Reviewer Agent, an AI specialist responsible for reviewing new lead notifications from Salesforce, assessing lead quality, determining lead disposition, and making informed routing decisions for qualified leads to ensure they are assigned to the appropriate advisors for follow-up if there is no advisor assigned already.

Goal:
Your primary goal is to assess incoming lead information, determine lead quality, set status to working, and make informed
routing decisions for leads to ensure they are assigned to the appropriate advisors for follow-up. Provide short summary of your decisions and reasoning for each event.

Responsibilities:
- Review new lead notifications from Salesforce which has a NEW_LEAD status using salesforce_lead_retrieval_tool.
- Check if this lead is already a client in Salesforce using salesforce_client_query_tool, if so, delete the lead using salesforce_delete_lead_tool.    
- Check if this lead is already a lead existing in Salesforce, if so, delete one lead which has less information usingsalesforce_delete_lead_tool and keep the other lead. 
- Determine lead disposition (e.g., New_lead, working, unqualified, needs more info) using salesforce_lead_status_update_tool.
- Example: if the lead status is new lead then update the status to working.
- If there is no advisor assigned, assign qualified leads to the most suitable advisor based on lead attributes and advisor expertise. Use salesforce_advisor_search_tool to find appropriate advisors and use salesforce_advisor_assignment_tool to assign the advisor to the lead.
- If the lead has no location, ask the user with ask_human_input_tool whether it is acceptable to use a remote advisor (Yes/No). If the user responds No, ask the user to provide a location and then use that location and salesforce_advisor_search_tool to assign an advisor to the lead. If the lead does have a location, use salesforce_advisor_search_tool to find an advisor for that area and assign the lead accordingly.
- Escalate to human intervention when necessary, providing a concise summary of the issue for hand off.
- Example: If the agent was not able to determine who is the right advisor to assign the lead to, then escalate to human intervention with a summary of the issue.
- If you cannot determine if the Salesforce notification is a new lead, use ask_human_input_tool.

""".strip()


#- Provide a summary note of actions taken for each lead, including any gaps or ambiguities in the lead data
#- Assess lead quality based on provided information and predefined criteria


#TODO: 
#- Define Response Ingestion Persona
#- Describe the goal for the response ingestion agent
#- Document tool usage expectations and guideliens if tools are introduced
#- Outline the ingestion procedure for processing inbound emails, and all subsequent agent actions
#- Add rules for tool calls, confidence scoring, ambiguity handling, and failure states.
#""".strip()


class LeadReviewerOutput(BaseModel):
    """Structured response returned by the lead reviewer agent."""
    # TODO: Define the structured response for all values below

    status: Annotated[
        Literal["completed", "partial", "failed"],
        Field(description="Overall lead-review workflow status."),
    ]
    lead_id: Annotated[
        str | None,
        Field(description="Salesforce lead identifier when available."),
    ] = None
    # TODO: Add `lead_disposition` for the final disposition of the reviewed lead
    lead_disposition: Annotated[
        str | None,
        Field(description="Final disposition of the reviewed lead."),
    ] = None
    # TODO: Add `lead_status_after_review` for the final Salesforce lead status after processing, such as `Working`
    lead_status_after_review: Annotated[
        str | None,
        Field(description="Final Salesforce lead status after processing."),
    ] = None
    # TODO: Add `selected_branch_type` for the branch-routing decision used for advisor assignment
    selected_branch_type: Annotated[
        str | None,
        Field(description="Branch-routing decision used for advisor assignment."),
    ] = None
    # TODO: Add `assigned_advisor_id` for the assigned advisor identifier when a qualified lead is routed
    assigned_advisor_id: Annotated[
        str | None,
        Field(description="Assigned advisor identifier when a qualified lead is routed."),
    ] = None
    # TODO: Add `assigned_advisor_name` for the assigned advisor display name when available
    assigned_advisor_name: Annotated[
        str | None,
        Field(description="Assigned advisor display name when available."),
    ] = None
    # TODO: Add `summary_note` for a brief summary note of actions taken for this lead
    summary_note: Annotated[
        str | None,
        Field(description="Brief summary note of actions taken for this lead."),
    ] = None
    # TODO: Add `actions_taken` for tracking ordered actions completed during lead review
    actions_taken: Annotated[
        list[str],
        Field(description="Ordered actions completed during lead review."),
    ] = []
    # TODO: Add `gaps` for noting missing lead data, routing ambiguities, or other non-blocking gaps
    gaps: Annotated[
        list[str],
        Field(description="Missing lead data, routing ambiguities, or other non-blocking gaps."),
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
    # TODO: Add `confidence` for the final lead review and advisor assignment decision confidence score
    confidence: Annotated[
        float | None,
        Field(description="Final lead review and advisor assignment decision confidence score."),
    ] = None


def make_lead_reviewer_agent(hooks: RunHooks | None = None) -> Agent:
    """Create the lead reviewer agent."""

    return Agent(
        name="Lead Reviewer Agent",
        instructions=LEAD_REVIEWER_AGENT_PROMPT,
        model="gpt-5.4-nano", # TODO: update approriate model for response ingestion
        model_settings=ModelSettings(tool_choice="auto", parallel_tool_calls=False),
        tools=[
            salesforce_lead_retrieval_tool,
            salesforce_lead_status_update_tool,
            salesforce_lead_query_tool, 
            salesforce_client_query_tool, 
            salesforce_lead_status_update_tool, 
            salesforce_delete_lead_tool, 
            salesforce_advisor_search_tool,
            salesforce_advisor_assignment_tool,
            ask_human_input_tool,
               ], # TODO: add relevant tools
        output_type=LeadReviewerOutput,
        input_guardrails=[],
        output_guardrails=[], # TODO: add relevant guardrails
    )


lead_reviewer_agent: Agent = make_lead_reviewer_agent()
