import type {
  ApprovalSnapshot,
  ApprovalSubmissionRequest,
  ScenarioListItem,
  TimelineEntry,
  WorkflowRunSnapshot,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let detail = response.statusText;
  try {
    const payload = (await response.json()) as { detail?: string };
    detail = payload.detail ?? detail;
  } catch {}

  throw new Error(detail);
}

export async function fetchScenarios(): Promise<ScenarioListItem[]> {
  const response = await fetch(`${API_BASE_URL}/scenarios`, {
    cache: "no-store",
  });
  return parseJsonResponse<ScenarioListItem[]>(response);
}

export async function fetchRuns(): Promise<WorkflowRunSnapshot[]> {
  const response = await fetch(`${API_BASE_URL}/runs`, {
    cache: "no-store",
  });
  return parseJsonResponse<WorkflowRunSnapshot[]>(response);
}

export async function fetchRun(runId: string): Promise<WorkflowRunSnapshot> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}`, {
    cache: "no-store",
  });
  return parseJsonResponse<WorkflowRunSnapshot>(response);
}

export async function fetchRunTimeline(runId: string): Promise<TimelineEntry[]> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/timeline`, {
    cache: "no-store",
  });
  return parseJsonResponse<TimelineEntry[]>(response);
}

export function buildPreviewUrl(path: string): string {
  return `${API_BASE_URL}/files/preview?path=${encodeURIComponent(path)}`;
}

export async function startScenarioRun(
  scenarioId: string,
  resetRuntimeData = true,
): Promise<WorkflowRunSnapshot> {
  const response = await fetch(`${API_BASE_URL}/runs/scenarios/${scenarioId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      reset_runtime_data: resetRuntimeData,
    }),
  });

  return parseJsonResponse<WorkflowRunSnapshot>(response);
}

export async function submitApproval(
  runId: string,
  approvalId: string,
  payload: ApprovalSubmissionRequest,
): Promise<ApprovalSnapshot> {
  const response = await fetch(
    `${API_BASE_URL}/runs/${runId}/approvals/${approvalId}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );

  return parseJsonResponse<ApprovalSnapshot>(response);
}
