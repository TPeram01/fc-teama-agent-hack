# SCENARIOS

## Initial Scenarios

1. `e2e_test` (initial test): *End-to-end happy path with documents, scheduling, post-meeting follow-up, and final approval so users can see the full workflow and quickly spot what is broken.*
2. `new_lead` (lead reviewer testing): *Single new-lead scenario for qualification, advisor assignment, status updates, and introductory outreach.*
3. `meeting_confirmation` (response ingestion testing): *Inbound email scenario for explicit meeting confirmation, Form 1500 updates, and split document routing across compliance and non-compliance paths.*
4. `meeting_close_follow_up` (infotrack testing): *Single meeting-close scenario where InfoTrack must send combined next-step outreach and request missing Form 1500 fields.*
5. `e2e_simple_scenario` (simple end-to-end test): *Lead-to-close workflow where the client provides all intake data in the first reply, sends no documents, and moves through a streamlined end-to-end flow.*

## Feature Testing

1. `duplicate_lead_detection` (duplicate lead testing): *Single new-lead scenario where the incoming UID is a duplicate of an existing lead, used to test duplicate detection, disqualification, and discard behavior.*
2. `existing_client_detection` (existing client testing): *Single new-lead scenario where the incoming record matches an existing client, used to test existing-client detection and prevention of duplicate onboarding.*
3. `off_topic_email_blocked` (off-topic guardrail testing): *New lead replies with a completely unrelated email, used to test on-topic filtering and ensure the workflow does not continue on irrelevant client input.*
4. `email_prompt_injection` (email prompt injection testing): *Single inbound email containing explicit instruction-manipulation text, used to test prompt-injection detection on email bodies.*
5. `attachment_prompt_injection` (attachment prompt injection testing): *Single inbound email with a normal body and a malicious attachment, used to test prompt-injection detection on extracted attachment text.*
6. `new_lead_missing_location` (missing location routing testing): *Single new-lead scenario with no city or state data, used to test remote-routing fallback and required human approval before assignment.*
7. `ambiguous_document` (low-confidence document testing): *Single inbound email with a readable but ambiguous document, used to test low-confidence document classification and escalation to manual or compliance review instead of blind routing.*
8. `corrupted_attachment` (document corruption testing): *End-to-end workflow with multiple attachments including one corrupted file, used to test partial document failure handling, follow-up on unreadable files, and safe continuation of the broader workflow.*

## Mock Exam

1. `e2e_test` (initial test): *End-to-end happy path with documents, scheduling, post-meeting follow-up, and final approval, used as the primary benchmark scenario.*
2. `e2e_simple_scenario` (simple end-to-end test): *Lead-to-close workflow where the client provides all intake data in the first reply and sends no documents, used as a fast full-workflow benchmark.*
3. `revision_loop_e2e` (revision workflow testing): *End-to-end workflow where the client requests a revision meeting before approving the final plan, used to test multi-meeting state progression and revision handling.*
4. `corrupted_attachment` (document corruption testing): *End-to-end workflow with multiple attachments including one corrupted file, used to test partial document failure handling in a realistic full-lifecycle case.*
5. `new_lead_remote_fallback` (remote routing): *Single new-lead workflow in a state with no local advisors, used to test remote fallback, human approval, and successful downstream routing.*
6. `financial_plan_approval` (completion follow-up testing): *Single meeting-close scenario where the financial plan is approved, used to test concise end-state client sendoff behavior.*
7. `ambiguous_document` (low-confidence document testing): *Inbound email with a readable but ambiguous document, used to test whether the workflow handles uncertainty safely during a scored run.*
8. `parallel_e2e_test` (parallel case handling testing): *Interleaved multi-case scenario that runs `e2e_test` and `corrupted_attachment` in parallel by alternating payloads, used to test state isolation, concurrent case handling, and robustness under mixed workloads.*

## Stretch Goals

1. `contradictory_client_input` (contradiction guardrail testing): *Single inbound email where the client provides details that conflict with previously stored Form 1500 data, used to test contradiction detection and safe escalation instead of silent overwrites.*
2. `unsupported_document_claim` (unsupported attachment claim testing): *Single inbound email where the client says an attachment contains requested details, but the attachment itself does not support that claim, used to test hallucination resistance and uncertainty handling.*
3. `same_case_multi_event_resume` (case-session continuity testing): *Single case progresses from new lead to client reply to meeting close, used to test whether the workflow revisits prior case context across separate related events.*
4. `interleaved_case_session_isolation` (session isolation testing): *Two cases progress through alternating events, used to test per-case session reuse while preserving isolation between concurrent workflows.*
5. `manual_review_queue_ambiguous_document` (manual review queue testing): *Single inbound email with an ambiguous attachment, used to test whether the workflow queues the case for manual review instead of routing the document blindly.*
6. `manual_review_queue_remote_fallback` (manual review queue testing): *Single new-lead scenario in a state with no local advisors, used to test whether the workflow creates a manual review item for remote fallback approval.*
