# Guidelines
- Start with data preparation (already completed for you)
- Use test-driven development. Find and run an appropriate scenario (`SCENARIOS.md`), assess the results, and look at the trace. Make your edits, and iterate.
- Periodically run `uv run evals.py`, check your evals dashboard, and tune the judge for in-depth evaluation while building.


# Checklist 
1. Start with **evaluations**:
   Run the "Initial Scenarios" (`SCENARIOS.md`) with the initial setup (this includes just the manager with a minimal prompt) and take a look at the results. Open up the trace urls and familiarize yourself with the trace dashboard. Then go ahead and run `uv run evals.py` to run evaluations with our LLM as judge. Click on the evals url to see the results, and take a look at the `evals/eval_agents.py` to understand the judge prompt. As we make changes, continue to run `uv run evals.py` to evaluate your accuracy and assist with debugging. You may need to delete old traces in `traces_logs/` to purge old runs.

2. Implement the **manager agent**.
   Update `custom_agents/manager.py` to rewrite the manager instructions, complete the specialist-tool descriptions for lead review, response ingestion, and InfoTrack, and finish the structured manager output schema used by `main.py` and `api.py`. If the manager interface changes, also update `custom_agents/__init__.py` and any manager-output handling in `main.py`. Test using the `e2e_test` scenario.

3. Implement the lead **reviewer agent**.
   Update `custom_agents/lead_reviewer.py` to write the lead-review prompt, complete the structured output model, and attach the Salesforce and human-in-the-loop tools needed for qualification, duplicate and existing-client checks, status updates, advisor search, advisor assignment, and lead deletion flows. Once the specialist is working, register it as a tool in `custom_agents/manager.py` and keep `custom_agents/__init__.py` aligned if exports change. Test using the `new_lead` scenario.

4. Implement the **InfoTrack agent**.
   Update `custom_agents/infotrack.py` to define the InfoTrack instructions, finalize its structured output, and connect the tools needed for missing-information outreach, advisor-calendar lookup, meeting-option generation, Zocks review, and follow-up email handling. After that, wire the specialist into `custom_agents/manager.py` so the manager can call it only for the appropriate qualified-lead and meeting-close paths. Test using the `meeting_confirmation`.

5. Implement the **response ingestion agent**.
   Update `custom_agents/response_ingestion.py` to define the inbound-email processing instructions, finalize the structured output fields, and connect the tools needed for email reading, attachment processing, Salesforce updates, meeting scheduling, follow-up messaging, and Laserfiche-versus-Salesforce document routing. When the agent surface is complete, register it in `custom_agents/manager.py` and keep any related exports synchronized in `custom_agents/__init__.py`. Test using the `meeting_close_follow_up`.

6. Implement the **agent-level guardrails** and attach them to the right agents.
   Update `guardrails/agent_guardrails.py` to complete the moderation, spam/noise, prompt-injection/malware, and analysis-confidence guardrails, re-export them from `guardrails/__init__.py` as needed, and attach them in the appropriate files under `custom_agents/`. Make sure the manager and specialist agents use the right input and output guardrails for routing safety, ambiguity handling, and low-confidence outcomes.

7. Implement the **tool-level guardrails** and attach them to the right tools.
   Update `guardrails/tool_guardrails.py` and `guardrails/__init__.py` as needed, then add the appropriate tool decorators and guardrails across the files in `tools/`. This includes wiring email moderation and PII filtering to `tools/emails.py`, prompt-injection and compliance guardrails to `tools/document_processor.py`, and any additional tool guardrails that belong on the Salesforce, Laserfiche, calculator, template, Zocks, and HITL tool surfaces.

8. Run **test scenarios** and use evals to improve the workflow based on the results.
   Use `evals.py` and `evals/eval_agents.py` to run the current trace-based evaluation flow from `traces_logs/`, and review the judge output for routing, tool-use, safety, and efficiency issues. Based on the results, update the affected files in `custom_agents/`, `guardrails/`, and `tools/`. Try running through all of the scenarios listed under "Feature Testing" in `SCENARIOS.md`.

9. Check evals for the **mock exam**.
   Delete all existing traces in the `/traces_logs` folder, and run all 8 scenarios listed uner **Mock Exam** in `SCENARIOS.md`. Then run `uv run evals.py` and take a look at the judge's evaluation of agent performance across all 8 scenarios and assess your % score. This will help identify any existing gaps in the workflow. Continue to refine until you are happy with the performance.

10. **Run the API** and validate the end-to-end flow.
   Validate the end-to-end workflow through `api.py` and `main.py`, including scenario runs from `data/scenarios.json`, manager routing, specialist handoffs, guardrail failures, and the final structured response returned by `POST /agents/run`. Update those files if request parsing, workflow wiring, runtime reset behavior, or execution-summary reporting need to be corrected.

# Stretch Goals
1. Optimize cost and latency.
   Reduce token usage, unnecessary tool calls, and avoidable agent handoffs while preserving workflow quality. Validate this with benchmark runs of `e2e_simple_scenario`, `e2e_test`, `corrupted_attachment`, and `parallel_e2e_test` rather than a dedicated stretch-goal scenario.

2. Add additional guardrails.
   Extend `guardrails/agent_guardrails.py` and `guardrails/tool_guardrails.py` with extra safety and quality checks, such as contradiction detection, hallucination checks, or better escalation on uncertainty, and keep `guardrails/__init__.py` aligned. Relevant scenarios: `contradictory_client_input`, `unsupported_document_claim`.

3. Expand the eval dataset and harden the workflow.
   Add more scenarios, then use the results to refine prompts, reduce unnecessary steps, and improve reliability across `main.py`, `custom_agents/`, `tools/`, and `evals/`. This goal is validated by broadening the scenario set itself, especially with `contradictory_client_input`, `unsupported_document_claim`, `same_case_multi_event_resume`, `interleaved_case_session_isolation`, `manual_review_queue_ambiguous_document`, and `manual_review_queue_remote_fallback`.

4. Redact PII from saved traces.
   Mask or remove sensitive client data before traces are written so traces remain useful for debugging without exposing raw PII. Validate this by inspecting traces generated from scenarios with rich client data such as `meeting_confirmation`, `e2e_test`, and `contradictory_client_input` rather than by adding a dedicated scenario.

5. Support local-only traces.
   Add a mode that keeps traces entirely local for privacy-sensitive development and demos. Validate this by running existing scenarios such as `new_lead`, `meeting_confirmation`, or `e2e_test` with the local-only mode enabled and confirming no remote trace upload occurs.

6. Maintain per-case sessions.
   Create a dedicated session for each case so the manager and specialists can revisit prior context across multiple related events. Relevant scenarios: `same_case_multi_event_resume`, `interleaved_case_session_isolation`.

7. Add regression-style scenario tests.
   Turn key scenarios into automated assertions for routing decisions, tool use, and final record updates so regressions are caught before manual eval runs. Build this suite around `new_lead`, `meeting_confirmation`, `meeting_close_follow_up`, `ambiguous_document`, `corrupted_attachment`, and `parallel_e2e_test`.

8. Build a manual review queue for escalations.
   Persist low-confidence, blocked, or human-approval-required cases into a simple review queue so operators can resume them consistently. Relevant scenarios: `manual_review_queue_ambiguous_document`, `manual_review_queue_remote_fallback`.


---

# Available Components
1. Specialist agents.
   - `lead_reviewer`: *Qualifies new Salesforce leads, checks for existing clients or duplicates, updates lead status, and assigns advisors.*
   - `infotrack`: *Handles missing-information outreach, advisor-calendar availability, and post-meeting follow-up using Zocks notes.*
   - `response_ingestion`: *Processes inbound client emails, reviews attachments, updates Salesforce, schedules meetings, and routes documents.*

2. Tools.
   - `ask_human_input_tool`: *Prompts a human operator for a short text answer when the workflow needs manual confirmation or missing information.*
   - `calculate_tool`: *Performs basic arithmetic operations so agents can offload deterministic numeric calculations.*
   - `email_template_loader_tool`: *Loads a predefined email template from disk.*
   - `send_email_tool`: *Sends a mock outbound email and returns the normalized sent payload.*
   - `email_read_tool`: *Loads and normalizes an inbound email record from mock storage.*
   - `document_processor_tool`: *Loads email attachments, extracts readable content, and classifies compliance relevance.*
   - `laserfiche_uploader_tool`: *Stores an attachment path in the mock Laserfiche system for a UID.*
   - `zocks_reviewer_tool`: *Retrieves the latest stored Zocks meeting summary and action items for a lead.*
   - `salesforce_client_db_get_tool`: *Retrieves a client record from the mock Salesforce client database.*
   - `salesforce_client_db_set_tool`: *Creates or updates a client record in the mock Salesforce client database.*
   - `salesforce_client_query_tool`: *Checks whether a lead already exists as a client.*
   - `salesforce_client_information_tool`: *Retrieves Form 1500 information and missing-field details for a lead.*
   - `salesforce_lead_db_get_tool`: *Retrieves a lead record from the mock Salesforce lead database.*
   - `salesforce_lead_retrieval_tool`: *Retrieves the full current lead record used during lead review.*
   - `salesforce_lead_db_set_tool`: *Creates or updates a lead record in the mock Salesforce lead database.*
   - `salesforce_lead_status_update_tool`: *Updates a lead's Salesforce status.*
   - `salesforce_client_input_tool`: *Applies structured client-response updates to a lead record.*
   - `meeting_scheduler_tool`: *Schedules a meeting for a lead in the mock Salesforce system.*
   - `salesforce_document_uploader_tool`: *Appends one or more document paths to a lead's Salesforce record.*
   - `salesforce_lead_query_tool`: *Checks whether a lead is a duplicate of another lead.*
   - `salesforce_advisor_db_get_tool`: *Retrieves an advisor record from the mock Salesforce advisor database.*
   - `salesforce_advisor_search_tool`: *Searches for advisors by state and falls back to remote advisors when needed.*
   - `advisor_calendar_tool`: *Retrieves available meeting blocks for the advisor assigned to a lead.*
   - `salesforce_advisor_assignment_tool`: *Assigns an advisor to a lead record.*
   - `salesforce_delete_lead_tool`: *Deletes a lead from the mock Salesforce system.*
   - `salesforce_advisor_db_set_tool`: *Creates or updates an advisor record in the mock Salesforce advisor database.*
   - `salesforce_notification_db_get_tool`: *Retrieves a Salesforce notification record from mock storage.*
   - `salesforce_notification_db_set_tool`: *Creates or updates a Salesforce notification record in mock storage.*

3. Agent-level guardrails.
   - `moderation_guardrail`: *Checks final agent output with the moderation API and blocks unsafe content.*
   - `spam_and_noise_guard_rail`: *Rejects empty, unrelated, or nonsensical workflow inputs before an agent continues.*
   - `prompt_injection_and_malware_guardrail`: *Detects prompt injection or malicious instruction text at the agent-input level.*
   - `analysis_confidence_guardrail`: *Trips when an agent returns a confidence score below the required threshold.*

4. Tool-level guardrails.
   - `email_moderation_guardrail`: *Blocks unsafe or inappropriate outbound email content.*
   - `client_on_topic_guardrail`: *Rejects inbound emails that are clearly unrelated to the onboarding workflow.*
   - `email_prompt_injection_guardrail`: *Rejects inbound emails that try to manipulate the agent with instruction-level attacks.*
   - `pii_filter`: *Blocks outbound email drafts that include prohibited PII or sensitive financial details.*
   - `pii_filter_output_guardrail`: *Rechecks normalized outbound email payloads for prohibited PII before they are returned.*
   - `attachment_prompt_injection_guardrail`: *Rejects extracted attachment text that contains prompt-injection-style content.*
   - `document_compliance_confidence_guardrail`: *Blocks attachment-processing results when compliance classification confidence is too low.*
   - `sql_read_only_guardrail`: *Rejects non-read-only SQL statements and allows only safe query shapes.*
