export type ScenarioListItem = {
  id: string;
  description: string;
  payload_count: number;
  payload_types: string[];
};

export type ApprovalSnapshot = {
  approval_id: string;
  prompt: string;
  status: "pending" | "resolved" | "cancelled";
  requested_at: string;
  resolved_at: string | null;
  response_text: string | null;
};

export type RunEvent = {
  type: string;
  timestamp: string;
  sequence: number;
  run_id: string;
  [key: string]: unknown;
};

export type TimelineDetailItem = {
  label: string;
  format: "text" | "json";
  value: string | Record<string, unknown> | unknown[] | null;
};

export type TimelineAttachment = {
  label: string;
  path: string;
};

export type TimelineEntry = {
  id: string;
  kind: "system" | "payload" | "agent" | "tool" | "approval";
  event_type: string | null;
  timestamp: string | null;
  title: string;
  summary: string;
  body: string | null;
  actor: string | null;
  status: string | null;
  emoji: string | null;
  is_pending_details: boolean;
  payload_index: number | null;
  payload_label: string | null;
  badge: string | null;
  attachments: TimelineAttachment[];
  detail_items: TimelineDetailItem[];
  raw: Record<string, unknown> | null;
};

export type WorkflowRunSnapshot = {
  run_id: string;
  run_kind: "payload" | "scenario";
  status: "queued" | "running" | "awaiting_approval" | "completed" | "failed";
  scenario_id: string | null;
  scenario_name: string | null;
  input_payloads: Array<Record<string, unknown>>;
  started_at: string;
  completed_at: string | null;
  trace_id: string | null;
  session_id: string | null;
  approvals: ApprovalSnapshot[];
  event_count: number;
  events: RunEvent[];
  live_execution_report: ExecutionReport | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
};

export type ExecutionReportAgent = {
  name: string;
  model: string | null;
  total_tokens: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
  cost: number;
};

export type ExecutionReportTool = {
  name: string;
  calls: number;
  cost: number;
};

export type ExecutionReport = {
  started_at: string;
  duration_seconds: number;
  agent_count: number;
  agents: ExecutionReportAgent[];
  tools: ExecutionReportTool[];
  totals: {
    input_tokens: number;
    output_tokens: number;
    cached_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
    requests: number;
  };
  total_agent_cost: number;
  total_tool_cost: number;
  total_cost: number;
};

export type StartScenarioRunRequest = {
  reset_runtime_data: boolean;
};

export type ApprovalSubmissionRequest = {
  decision?: "approve" | "reject";
  response_text?: string;
};
