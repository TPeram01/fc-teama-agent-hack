"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useRef,
  useState,
} from "react";
import type { UIEvent } from "react";

import {
  API_BASE_URL,
  buildPreviewUrl,
  fetchRun,
  fetchRuns,
  fetchRunTimeline,
  fetchScenarios,
  startScenarioRun,
  submitApproval,
} from "../lib/api";
import type {
  ApprovalSnapshot,
  ExecutionReport,
  ScenarioListItem,
  TimelineAttachment,
  TimelineDetailItem,
  TimelineEntry,
  WorkflowRunSnapshot,
} from "../lib/types";
import styles from "./control-plane.module.css";

type MainTab = "timeline" | "usage" | "detailedSummary" | "payloads";
type TimelineFilter = "all" | TimelineEntry["kind"];

const MAIN_TABS: Array<{ id: MainTab; label: string }> = [
  { id: "timeline", label: "Timeline" },
  { id: "usage", label: "Usage" },
  { id: "detailedSummary", label: "Detailed Summary" },
  { id: "payloads", label: "Payloads" },
];

const TIMELINE_FILTERS: Array<{ id: TimelineFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "payload", label: "Payloads" },
  { id: "agent", label: "Agents" },
  { id: "tool", label: "Tools" },
  { id: "approval", label: "Approvals" },
  { id: "system", label: "System" },
];

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "n/a";
  }

  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatTimelineTime(value: string | null): string {
  if (!value) {
    return "n/a";
  }

  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatTimelineRailParts(
  value: string | null,
): { date: string; time: string; meridiem: string } {
  if (!value) {
    return {
      date: "n/a",
      time: "n/a",
      meridiem: "",
    };
  }

  const date = new Date(value);
  const dateLabel = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
  const timeLabel = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
    hour12: true,
  }).format(date);
  const match = timeLabel.match(/^(.*)\s([AP]M)$/);

  if (!match) {
    return {
      date: dateLabel,
      time: timeLabel,
      meridiem: "",
    };
  }

  return {
    date: dateLabel,
    time: match[1],
    meridiem: match[2],
  };
}

function timelineRailLabel(entry: TimelineEntry): string | null {
  if (entry.event_type === "run_started" || entry.event_type === "run_completed") {
    return "Workflow";
  }

  if (entry.event_type === "run_failed") {
    return "Workflow";
  }

  if (entry.event_type === "scenario_started" || entry.event_type === "scenario_completed") {
    const scenarioName = entry.raw?.["scenario_name"];
    return typeof scenarioName === "string" && scenarioName ? scenarioName : "Scenario";
  }

  if (entry.kind === "payload") {
    return entry.payload_label ?? entry.badge ?? "Payload";
  }

  if (entry.kind === "approval") {
    return "Human Review";
  }

  if (entry.kind === "tool") {
    return entry.actor ?? "Tool";
  }

  if (entry.kind === "agent") {
    return entry.actor ?? entry.badge ?? "Agent";
  }

  return null;
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return new Intl.NumberFormat("en-US").format(value);
}

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(value);
}

function formatDurationSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return `${value.toFixed(2)}s`;
}

function formatKindLabel(kind: TimelineEntry["kind"]): string {
  switch (kind) {
    case "payload":
      return "Payload";
    case "agent":
      return "Agent";
    case "tool":
      return "Tool";
    case "approval":
      return "Approval";
    default:
      return "System";
  }
}

function getPendingApproval(
  run: WorkflowRunSnapshot | null,
): ApprovalSnapshot | undefined {
  return run?.approvals.find((approval) => approval.status === "pending");
}

function getExecutionReport(run: WorkflowRunSnapshot | null): ExecutionReport | null {
  if (run?.live_execution_report) {
    return run.live_execution_report;
  }

  const result = run?.result as
    | {
        execution_report?: ExecutionReport;
      }
    | undefined;

  return result?.execution_report ?? null;
}

function renderJson(value: Record<string, unknown> | unknown[]): string {
  return JSON.stringify(value, null, 2);
}

function bubbleTone(entry: TimelineEntry): string {
  const toneByKind = (() => {
    switch (entry.kind) {
      case "payload":
        return styles.bubblePayload;
      case "agent":
        return styles.bubbleAgent;
      case "tool":
        return styles.bubbleTool;
      case "approval":
        return styles.bubbleApproval;
      default:
        return styles.bubbleSystem;
    }
  })();

  const toolVariant =
    entry.badge === "email_read_tool"
      ? styles.bubbleToolInbound
      : entry.badge === "send_email_tool"
        ? styles.bubbleToolOutbound
        : entry.badge === "meeting_scheduler_tool"
          ? styles.bubbleToolScheduled
          : "";

  return `${toneByKind} ${toolVariant}`.trim();
}

function renderEntryTitle(entry: TimelineEntry) {
  if (entry.kind === "tool" && entry.actor) {
    return (
      <div className={styles.toolTitleStack}>
        <span className={styles.toolActorPill}>{entry.actor}</span>
        <strong>{entry.title}</strong>
      </div>
    );
  }

  return <strong>{entry.title}</strong>;
}

function Bubble({
  entry,
  isActive,
  onSelect,
  onPreviewAttachment,
}: {
  entry: TimelineEntry;
  isActive: boolean;
  onSelect: (entryId: string) => void;
  onPreviewAttachment: (attachment: TimelineAttachment) => void;
}) {
  return (
    <div
      className={`${styles.bubbleRow} ${bubbleTone(entry)} ${
        isActive ? styles.bubbleActive : ""
      }`}
      onClick={() => {
        onSelect(entry.id);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(entry.id);
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className={styles.bubbleAvatar}>
        <span>{entry.emoji ?? "•"}</span>
      </div>
      <div className={styles.bubbleBody}>
        <div className={styles.bubbleMeta}>
          <div className={styles.bubbleTitleRow}>{renderEntryTitle(entry)}</div>
          <div className={styles.bubbleChips}>
            <span className={styles.kindChip}>{formatKindLabel(entry.kind)}</span>
            {entry.actor && entry.kind !== "tool" ? (
              <span className={styles.kindChip}>{entry.actor}</span>
            ) : null}
            {entry.payload_label ? (
              <span className={styles.kindChip}>{entry.payload_label}</span>
            ) : null}
            {entry.status ? <span className={styles.kindChip}>{entry.status}</span> : null}
          </div>
        </div>
        <p>{entry.summary}</p>
        {entry.is_pending_details ? (
          <div className={styles.loadingBody} aria-live="polite">
            <span className={styles.loadingSpinner} aria-hidden="true" />
            <span>Loading full tool output...</span>
          </div>
        ) : null}
        {entry.body && !entry.is_pending_details ? (
          <div className={styles.bubbleBodyText}>{entry.body}</div>
        ) : null}
        {entry.attachments.length > 0 ? (
          <div className={styles.attachmentRow}>
            {entry.attachments.map((attachment) => (
              <button
                key={`${entry.id}-${attachment.path}`}
                className={styles.attachmentChip}
                onClick={(event) => {
                  event.stopPropagation();
                  onPreviewAttachment(attachment);
                }}
                type="button"
              >
                <span aria-hidden="true">📄</span>
                <span>{attachment.label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function SystemMarker({ entry }: { entry: TimelineEntry }) {
  return (
    <div className={styles.systemMarker}>
      <span className={styles.systemEmoji}>{entry.emoji ?? "•"}</span>
      <div className={styles.systemCopy}>
        <strong>{entry.title}</strong>
        <p>{entry.summary}</p>
      </div>
    </div>
  );
}

function StatusRow({
  entry,
  isActive,
  onSelect,
}: {
  entry: TimelineEntry;
  isActive: boolean;
  onSelect: (entryId: string) => void;
}) {
  return (
    <button
      className={`${styles.statusRow} ${isActive ? styles.statusRowActive : ""}`}
      onClick={() => {
        onSelect(entry.id);
      }}
      type="button"
    >
      <span className={styles.statusEmoji}>{entry.emoji ?? "🤖"}</span>
      <strong>{entry.summary}</strong>
    </button>
  );
}

function PayloadNotice({
  entry,
  isActive,
  onSelect,
  showDivider = false,
}: {
  entry: TimelineEntry;
  isActive: boolean;
  onSelect: (entryId: string) => void;
  showDivider?: boolean;
}) {
  return (
    <>
      {showDivider ? (
        <div className={styles.payloadDivider} aria-hidden="true">
          <hr className={styles.payloadDividerLine} />
        </div>
      ) : null}
      <button
        className={`${styles.payloadNotice} ${isActive ? styles.payloadNoticeActive : ""}`}
        onClick={() => {
          onSelect(entry.id);
        }}
        type="button"
      >
        <span className={styles.payloadNoticeIcon}>{entry.emoji ?? "🔔"}</span>
        <div className={styles.payloadNoticeCopy}>
          <div className={styles.payloadNoticeMeta}>
            <strong>{entry.title}</strong>
          </div>
          {entry.body ? <p>{entry.body}</p> : null}
        </div>
      </button>
    </>
  );
}

function ThreadItem({
  entry,
  isActive,
  onSelect,
  showPayloadDivider = false,
  onPreviewAttachment,
}: {
  entry: TimelineEntry;
  isActive: boolean;
  onSelect: (entryId: string) => void;
  showPayloadDivider?: boolean;
  onPreviewAttachment: (attachment: TimelineAttachment) => void;
}) {
  if (entry.kind === "system") {
    return <SystemMarker entry={entry} />;
  }

  if (entry.kind === "payload") {
    return (
      <PayloadNotice
        entry={entry}
        isActive={isActive}
        onSelect={onSelect}
        showDivider={showPayloadDivider}
      />
    );
  }

  if (entry.kind === "approval") {
    return (
      <Bubble
        entry={entry}
        isActive={isActive}
        onSelect={onSelect}
        onPreviewAttachment={onPreviewAttachment}
      />
    );
  }

  if (entry.event_type === "agent_start" || entry.event_type === "agent_end") {
    return <StatusRow entry={entry} isActive={isActive} onSelect={onSelect} />;
  }

  return (
    <Bubble
      entry={entry}
      isActive={isActive}
      onSelect={onSelect}
      onPreviewAttachment={onPreviewAttachment}
    />
  );
}

function TimelineItem({
  entry,
  index,
  total,
  isActive,
  onSelect,
  showPayloadDivider = false,
  onPreviewAttachment,
}: {
  entry: TimelineEntry;
  index: number;
  total: number;
  isActive: boolean;
  onSelect: (entryId: string) => void;
  showPayloadDivider?: boolean;
  onPreviewAttachment: (attachment: TimelineAttachment) => void;
}) {
  const rail = formatTimelineRailParts(entry.timestamp);
  const label = timelineRailLabel(entry);

  return (
    <div
      className={`${styles.timelineItem} ${
        index === 0 ? styles.timelineItemFirst : ""
      } ${index === total - 1 ? styles.timelineItemLast : ""}`.trim()}
    >
      <time className={styles.timelineRail} dateTime={entry.timestamp ?? undefined}>
        <span>{rail.date}</span>
        <span>{rail.time}</span>
        {rail.meridiem ? <span>{rail.meridiem}</span> : null}
        {label ? <span className={styles.timelineRailLabel}>{label}</span> : null}
      </time>
      <div className={styles.timelineNode} aria-hidden="true">
        <span className={styles.timelineDot} />
      </div>
      <div className={styles.timelineItemBody}>
        <ThreadItem
          entry={entry}
          isActive={isActive}
          onSelect={onSelect}
          showPayloadDivider={showPayloadDivider}
          onPreviewAttachment={onPreviewAttachment}
        />
      </div>
    </div>
  );
}

function PayloadCard({
  payload,
  index,
}: {
  payload: Record<string, unknown>;
  index: number;
}) {
  const payloadType = String(payload["payload_type"] ?? "unknown");
  const triggerType =
    typeof payload["salesforce_trigger_type"] === "string"
      ? payload["salesforce_trigger_type"]
      : null;

  return (
    <article className={styles.payloadCard}>
      <div className={styles.payloadHeader}>
        <div>
          <p className={styles.overline}>Payload {index + 1}</p>
          <h3>{payloadType.replaceAll("_", " ")}</h3>
        </div>
        {triggerType ? <span className={styles.kindChip}>{triggerType}</span> : null}
      </div>
      <div className={styles.payloadMeta}>
        <span>UID {String(payload["UID"] ?? "n/a")}</span>
        <span>Email {String(payload["email_id"] ?? "n/a")}</span>
      </div>
      <details className={styles.drawerSection}>
        <summary>Raw payload</summary>
        <pre>{renderJson(payload)}</pre>
      </details>
    </article>
  );
}

function DetailSection({
  item,
  defaultOpen = false,
}: {
  item: TimelineDetailItem;
  defaultOpen?: boolean;
}) {
  return (
    <details className={styles.drawerSection} open={defaultOpen}>
      <summary>{item.label}</summary>
      {item.format === "json" ? (
        <pre>{renderJson((item.value ?? {}) as Record<string, unknown> | unknown[])}</pre>
      ) : (
        <div className={styles.drawerText}>{String(item.value ?? "")}</div>
      )}
    </details>
  );
}

export function ControlPlane() {
  const [scenarios, setScenarios] = useState<ScenarioListItem[]>([]);
  const [runs, setRuns] = useState<WorkflowRunSnapshot[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunSnapshot | null>(null);
  const [timelineEntries, setTimelineEntries] = useState<TimelineEntry[]>([]);
  const [selectedTimelineId, setSelectedTimelineId] = useState<string | null>(null);
  const [approvalDraft, setApprovalDraft] = useState("");
  const [selectedAttachment, setSelectedAttachment] = useState<TimelineAttachment | null>(
    null,
  );
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [busyScenarioId, setBusyScenarioId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [runStatusMessage, setRunStatusMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<MainTab>("timeline");
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all");
  const streamRef = useRef<EventSource | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);
  const timelineEndRef = useRef<HTMLDivElement | null>(null);
  const lastVisibleTimelineIdRef = useRef<string | null>(null);
  const autoScrollTimeoutRef = useRef<number | null>(null);
  const isAutoScrollingRef = useRef(false);
  const [isFollowingTimeline, setIsFollowingTimeline] = useState(true);
  const [canScrollTimeline, setCanScrollTimeline] = useState(false);

  const filteredTimelineEntries =
    timelineFilter === "all"
      ? timelineEntries
      : timelineEntries.filter((entry) => entry.kind === timelineFilter);
  const deferredTimelineEntries = useDeferredValue(filteredTimelineEntries);
  const latestTimelineId = deferredTimelineEntries.at(-1)?.id ?? null;
  const executionReport = getExecutionReport(selectedRun);
  const pendingApproval = getPendingApproval(selectedRun);
  const selectedTimelineEntry =
    timelineEntries.find((entry) => entry.id === selectedTimelineId) ?? null;
  const traceUrl = selectedRun?.trace_id
    ? `https://platform.openai.com/traces/trace?trace_id=${selectedRun.trace_id}`
    : null;
  const activeRunCount = runs.filter(
    (run) => run.status !== "completed" && run.status !== "failed",
  ).length;

  async function refreshRuns() {
    const nextRuns = await fetchRuns();
    setRuns(nextRuns);
    if (!selectedRunId && nextRuns.length > 0) {
      setSelectedRunId(nextRuns[0].run_id);
    }
  }

  async function refreshSelectedRun(runId: string) {
    const [snapshot, nextTimeline] = await Promise.all([
      fetchRun(runId),
      fetchRunTimeline(runId),
    ]);
    setSelectedRun(snapshot);
    setTimelineEntries(nextTimeline);
    return snapshot;
  }

  function markTimelineAutoScrolling() {
    if (autoScrollTimeoutRef.current !== null) {
      window.clearTimeout(autoScrollTimeoutRef.current);
    }

    isAutoScrollingRef.current = true;
    autoScrollTimeoutRef.current = window.setTimeout(() => {
      isAutoScrollingRef.current = false;
      autoScrollTimeoutRef.current = null;
    }, 450);
  }

  function scrollTimelineToLatest(behavior: ScrollBehavior) {
    const element = timelineViewportRef.current;
    if (!element) {
      return;
    }

    markTimelineAutoScrolling();
    element.scrollTo({
      top: element.scrollHeight,
      behavior,
    });

    window.requestAnimationFrame(() => {
      syncTimelineViewportState(element);
    });
  }

  function syncTimelineViewportState(element: HTMLDivElement) {
    const nextCanScroll = element.scrollHeight > element.clientHeight + 1;
    setCanScrollTimeline(nextCanScroll);
  }

  function disableTimelineFollow() {
    const element = timelineViewportRef.current;
    if (!element) {
      return;
    }

    syncTimelineViewportState(element);
    if (element.scrollHeight <= element.clientHeight + 1) {
      return;
    }

    setIsFollowingTimeline(false);
  }

  async function bootstrapDashboard() {
    try {
      setErrorMessage(null);
      const [scenarioData, runData] = await Promise.all([
        fetchScenarios(),
        fetchRuns(),
      ]);
      setScenarios(scenarioData);
      setRuns(runData);
      if (runData.length > 0) {
        setSelectedRunId(runData[0].run_id);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to load the control plane.";
      setErrorMessage(message);
    } finally {
      setIsBootstrapping(false);
    }
  }

  useEffect(() => {
    void bootstrapDashboard();

    return () => {
      streamRef.current?.close();
      if (autoScrollTimeoutRef.current !== null) {
        window.clearTimeout(autoScrollTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      setTimelineEntries([]);
      setSelectedTimelineId(null);
      streamRef.current?.close();
      return;
    }

    let disposed = false;
    const runId = selectedRunId;

    async function attachToRun() {
      try {
        setErrorMessage(null);
        const snapshot = await refreshSelectedRun(runId);
        if (disposed) {
          return;
        }

        streamRef.current?.close();
        if (snapshot.status === "completed" || snapshot.status === "failed") {
          return;
        }

        const stream = new EventSource(`${API_BASE_URL}/runs/${runId}/events`);
        stream.onmessage = () => {
          startTransition(() => {
            void refreshSelectedRun(runId);
            void refreshRuns();
          });
        };
        stream.onerror = () => {
          stream.close();
        };
        streamRef.current = stream;
      } catch (error) {
        if (disposed) {
          return;
        }
        const message =
          error instanceof Error ? error.message : "Unable to load the selected run.";
        setErrorMessage(message);
      }
    }

    void attachToRun();

    return () => {
      disposed = true;
      streamRef.current?.close();
    };
  }, [selectedRunId]);

  useEffect(() => {
    setIsFollowingTimeline(true);
    setCanScrollTimeline(false);
    lastVisibleTimelineIdRef.current = null;
    isAutoScrollingRef.current = false;

    if (autoScrollTimeoutRef.current !== null) {
      window.clearTimeout(autoScrollTimeoutRef.current);
      autoScrollTimeoutRef.current = null;
    }
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedTimelineId) {
      return;
    }

    const stillExists = filteredTimelineEntries.some(
      (entry) => entry.id === selectedTimelineId,
    );
    if (!stillExists) {
      setSelectedTimelineId(null);
    }
  }, [filteredTimelineEntries, selectedTimelineId]);

  useEffect(() => {
    if (activeTab !== "timeline") {
      return;
    }

    const previousLatestId = lastVisibleTimelineIdRef.current;
    lastVisibleTimelineIdRef.current = latestTimelineId;

    if (!latestTimelineId) {
      return;
    }

    if (!isFollowingTimeline && previousLatestId !== null) {
      return;
    }

    const behavior =
      previousLatestId && previousLatestId !== latestTimelineId ? "smooth" : "auto";
    scrollTimelineToLatest(behavior);
  }, [activeTab, isFollowingTimeline, latestTimelineId]);

  useEffect(() => {
    if (activeTab !== "timeline") {
      return;
    }

    const element = timelineViewportRef.current;
    if (!element) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      syncTimelineViewportState(element);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [activeTab, deferredTimelineEntries, selectedRunId]);

  function handleTimelineScroll(event: UIEvent<HTMLDivElement>) {
    syncTimelineViewportState(event.currentTarget);

    if (isAutoScrollingRef.current) {
      return;
    }

    disableTimelineFollow();
  }

  async function handleStartScenario(scenarioId: string) {
    try {
      setBusyScenarioId(scenarioId);
      setErrorMessage(null);
      setRunStatusMessage(`Starting ${scenarioId}...`);
      const snapshot = await startScenarioRun(scenarioId, true);
      setSelectedRunId(snapshot.run_id);
      setSelectedRun(snapshot);
      await refreshSelectedRun(snapshot.run_id);
      await refreshRuns();
      setRunStatusMessage(`Run ${snapshot.run_id.slice(0, 8)} queued.`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to start the scenario.";
      setErrorMessage(message);
      setRunStatusMessage(null);
    } finally {
      setBusyScenarioId(null);
    }
  }

  async function handleApproval(decision: "approve" | "reject") {
    if (!selectedRun || !pendingApproval) {
      return;
    }

    try {
      setErrorMessage(null);
      const responseText = approvalDraft.trim();
      await submitApproval(selectedRun.run_id, pendingApproval.approval_id, {
        decision,
        response_text: responseText || undefined,
      });
      setApprovalDraft("");
      await refreshSelectedRun(selectedRun.run_id);
      await refreshRuns();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to resolve the approval.";
      setErrorMessage(message);
    }
  }

  return (
    <main className={styles.shell}>
      <section className={styles.topBar}>
        <div>
          <p className={styles.overline}>First Command</p>
          <h1>Workflow Control Plane</h1>
          <p className={styles.heroCopy}>
            A timeline-first view of each run with live steps, approvals, and
            trace-backed detail when you need it.
          </p>
        </div>
        <div className={styles.topMetrics}>
          <div className={styles.metricTile}>
            <span>API</span>
            <strong>{API_BASE_URL}</strong>
          </div>
          <div className={styles.metricTile}>
            <span>Active Runs</span>
            <strong>{activeRunCount}</strong>
          </div>
        </div>
      </section>

      {errorMessage ? <div className={styles.errorBanner}>{errorMessage}</div> : null}
      {runStatusMessage ? (
        <div className={styles.statusBanner}>{runStatusMessage}</div>
      ) : null}

      <section className={styles.layout}>
        <aside className={styles.sidebar}>
          <section className={`${styles.panel} ${styles.sidebarPanel}`}>
            <div className={styles.sectionHeader}>
              <h2>Scenarios</h2>
              <span>{scenarios.length}</span>
            </div>
            <div className={styles.scenarioList}>
              {isBootstrapping ? <p className={styles.empty}>Loading scenarios...</p> : null}
              {scenarios.map((scenario) => (
                <article key={scenario.id} className={styles.scenarioCard}>
                  <div className={styles.scenarioHeader}>
                    <div>
                      <p className={styles.overline}>Scenario</p>
                      <h3>{scenario.id}</h3>
                    </div>
                    <span className={styles.kindChip}>{scenario.payload_count}</span>
                  </div>
                  <p className={styles.scenarioDescription}>{scenario.description}</p>
                  <div className={styles.tagRow}>
                    {[...new Set(scenario.payload_types)].map((payloadType) => (
                      <span key={`${scenario.id}-${payloadType}`} className={styles.kindChip}>
                        {payloadType}
                      </span>
                    ))}
                  </div>
                  <button
                    className={styles.primaryButton}
                    onClick={() => {
                      void handleStartScenario(scenario.id);
                    }}
                    disabled={busyScenarioId !== null}
                    type="button"
                  >
                    {busyScenarioId === scenario.id ? "Starting..." : "Launch Scenario"}
                  </button>
                </article>
              ))}
            </div>
          </section>

          <section className={`${styles.panel} ${styles.sidebarPanel}`}>
            <div className={styles.sectionHeader}>
              <h2>Recent Runs</h2>
              <span>{runs.length}</span>
            </div>
            <div className={styles.runList}>
              {runs.length === 0 ? <p className={styles.empty}>No runs yet.</p> : null}
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  className={`${styles.runCard} ${
                    selectedRunId === run.run_id ? styles.runCardActive : ""
                  }`}
                  onClick={() => {
                    setSelectedRunId(run.run_id);
                    setRunStatusMessage(null);
                    setSelectedTimelineId(null);
                  }}
                  type="button"
                >
                  <div>
                    <p className={styles.overline}>{run.scenario_id ?? run.run_kind}</p>
                    <strong>{formatTimestamp(run.started_at)}</strong>
                  </div>
                  <span className={`${styles.statusPill} ${styles[`status_${run.status}`]}`}>
                    {run.status}
                  </span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className={styles.mainColumn}>
          {!selectedRun ? (
            <section className={styles.panel}>
              <div className={styles.emptyState}>
                <h2>Select or start a run</h2>
                <p>
                  Launch a scenario or choose a previous run to inspect the live
                  workflow timeline.
                </p>
              </div>
            </section>
          ) : (
            <section className={`${styles.panel} ${styles.workspacePanel}`}>
              <div className={styles.workspaceChrome}>
                <div className={styles.workspaceHeader}>
                  <div>
                    <p className={styles.overline}>Run Workspace</p>
                    <h2>{selectedRun.scenario_name ?? "Ad hoc payload run"}</h2>
                    <p className={styles.runMeta}>
                      Run ID <code>{selectedRun.run_id}</code>
                    </p>
                  </div>
                  <div className={styles.overviewRight}>
                    <span
                      className={`${styles.statusPill} ${styles[`status_${selectedRun.status}`]}`}
                    >
                      {selectedRun.status}
                    </span>
                    {traceUrl ? (
                      <a
                        className={styles.traceLink}
                        href={traceUrl}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open Trace
                      </a>
                    ) : null}
                  </div>
                </div>

                <div className={styles.tabBar}>
                  {MAIN_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      className={`${styles.tabButton} ${
                        activeTab === tab.id ? styles.tabButtonActive : ""
                      }`}
                      onClick={() => {
                        setActiveTab(tab.id);
                      }}
                      type="button"
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className={styles.workspaceBody}>
                {activeTab === "timeline" ? (
                  <div className={styles.timelineContent}>
                    <div className={styles.timelineHeader}>
                      <div>
                        <h2>Event Timeline</h2>
                        <p>
                          The latest event stays in view until you scroll away from
                          the feed.
                        </p>
                      </div>
                      <div className={styles.filterRow}>
                        {TIMELINE_FILTERS.map((filter) => (
                          <button
                            key={filter.id}
                            className={`${styles.filterChip} ${
                              timelineFilter === filter.id ? styles.filterChipActive : ""
                            }`}
                            onClick={() => {
                              setTimelineFilter(filter.id);
                            }}
                            type="button"
                          >
                            {filter.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className={styles.timelineViewportFrame}>
                      <div
                        className={styles.timelineViewport}
                        onTouchMove={() => {
                          disableTimelineFollow();
                        }}
                        onWheel={() => {
                          disableTimelineFollow();
                        }}
                        onScroll={handleTimelineScroll}
                        ref={timelineViewportRef}
                      >
                        <div
                          className={`${styles.timelineStream} ${
                            deferredTimelineEntries.length === 0
                              ? styles.timelineStreamEmpty
                              : ""
                          }`.trim()}
                        >
                          {deferredTimelineEntries.length === 0 ? (
                            <p className={styles.empty}>No timeline events yet.</p>
                          ) : null}
                          {deferredTimelineEntries.map((entry, index) => (
                            <TimelineItem
                              key={entry.id}
                              entry={entry}
                              index={index}
                              total={deferredTimelineEntries.length}
                              isActive={selectedTimelineEntry?.id === entry.id}
                              onSelect={setSelectedTimelineId}
                              showPayloadDivider={
                                entry.kind === "payload" && entry.payload_index !== 1
                              }
                              onPreviewAttachment={setSelectedAttachment}
                            />
                          ))}
                          <div
                            aria-hidden="true"
                            className={styles.timelineEndcap}
                            ref={timelineEndRef}
                          />
                        </div>
                      </div>

                      {canScrollTimeline && !isFollowingTimeline && latestTimelineId ? (
                        <div className={styles.timelineFloatingAction}>
                          <button
                            aria-label="Jump to latest"
                            className={styles.jumpButton}
                            onClick={() => {
                              setIsFollowingTimeline(true);
                              scrollTimelineToLatest("smooth");
                            }}
                            type="button"
                          >
                            ↓
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {activeTab === "usage" ? (
                  <div className={styles.contentPane}>
                    <div className={styles.metricsRow}>
                      <div className={styles.metricCard}>
                        <span>Duration</span>
                        <strong>{formatDurationSeconds(executionReport?.duration_seconds)}</strong>
                      </div>
                      <div className={styles.metricCard}>
                        <span>Agents</span>
                        <strong>{formatNumber(executionReport?.agent_count)}</strong>
                      </div>
                      <div className={styles.metricCard}>
                        <span>Requests</span>
                        <strong>{formatNumber(executionReport?.totals?.requests)}</strong>
                      </div>
                      <div className={styles.metricCard}>
                        <span>Tokens</span>
                        <strong>{formatNumber(executionReport?.totals?.total_tokens)}</strong>
                      </div>
                      <div className={styles.metricCard}>
                        <span>Total Cost</span>
                        <strong>{formatCurrency(executionReport?.total_cost)}</strong>
                      </div>
                    </div>

                    <div className={styles.summaryGrid}>
                      <section className={styles.summaryCard}>
                        <h3>Run Details</h3>
                        <div className={styles.summaryList}>
                          <div className={styles.summaryCompact}>
                            <span>Started</span>
                            <span>{formatTimestamp(selectedRun.started_at)}</span>
                          </div>
                          <div className={styles.summaryCompact}>
                            <span>Scenario</span>
                            <span>{selectedRun.scenario_id ?? "n/a"}</span>
                          </div>
                          <div className={styles.summaryCompact}>
                            <span>Run Kind</span>
                            <span>{selectedRun.run_kind}</span>
                          </div>
                          <div className={styles.summaryCompact}>
                            <span>Payloads</span>
                            <span>{formatNumber(selectedRun.input_payloads.length)}</span>
                          </div>
                        </div>
                      </section>

                      <section className={styles.summaryCard}>
                        <h3>Workflow State</h3>
                        <div className={styles.summaryList}>
                          <div className={styles.summaryCompact}>
                            <span>Status</span>
                            <span>{selectedRun.status}</span>
                          </div>
                          <div className={styles.summaryCompact}>
                            <span>Trace</span>
                            <span>{selectedRun.trace_id ? "Available" : "Not linked"}</span>
                          </div>
                          <div className={styles.summaryCompact}>
                            <span>Approval</span>
                            <span>
                              {pendingApproval
                                ? "Waiting on human review"
                                : "None pending"}
                            </span>
                          </div>
                        </div>
                      </section>

                      {pendingApproval ? (
                        <section className={styles.summaryCard}>
                          <h3>Pending Review</h3>
                          <p className={styles.drawerSummary}>{pendingApproval.prompt}</p>
                        </section>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {activeTab === "detailedSummary" ? (
                  <div className={styles.contentPane}>
                    <div className={styles.summaryGrid}>
                      {executionReport ? (
                        <>
                          <section className={styles.summaryCard}>
                            <h3>Agents</h3>
                            <div className={styles.summaryList}>
                              {executionReport.agents.map((agent) => (
                                <div
                                  key={`${agent.name}-${agent.model ?? "unknown"}`}
                                  className={styles.summaryRow}
                                >
                                  <div>
                                    <strong>{agent.name}</strong>
                                    <p>{agent.model ?? "unknown model"}</p>
                                  </div>
                                  <div className={styles.summaryStats}>
                                    <span>{formatNumber(agent.total_tokens)} tokens</span>
                                    <span>{formatNumber(agent.requests)} requests</span>
                                    <span>{formatCurrency(agent.cost)}</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </section>

                          <section className={styles.summaryCard}>
                            <h3>Tools</h3>
                            <div className={styles.summaryList}>
                              {executionReport.tools.map((tool) => (
                                <div key={tool.name} className={styles.summaryCompact}>
                                  <span>{tool.name}</span>
                                  <span>
                                    {tool.calls} calls
                                    {tool.cost > 0 ? ` · ${formatCurrency(tool.cost)}` : ""}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </section>

                          <section className={styles.summaryCard}>
                            <h3>Tokens</h3>
                            <div className={styles.summaryList}>
                              <div className={styles.summaryCompact}>
                                <span>Input</span>
                                <span>{formatNumber(executionReport.totals.input_tokens)}</span>
                              </div>
                              <div className={styles.summaryCompact}>
                                <span>Output</span>
                                <span>{formatNumber(executionReport.totals.output_tokens)}</span>
                              </div>
                              <div className={styles.summaryCompact}>
                                <span>Cached</span>
                                <span>{formatNumber(executionReport.totals.cached_tokens)}</span>
                              </div>
                              <div className={styles.summaryCompact}>
                                <span>Reasoning</span>
                                <span>
                                  {formatNumber(executionReport.totals.reasoning_tokens)}
                                </span>
                              </div>
                            </div>
                          </section>

                          <section className={styles.summaryCard}>
                            <h3>Cost</h3>
                            <div className={styles.summaryList}>
                              <div className={styles.summaryCompact}>
                                <span>Agent Cost</span>
                                <span>{formatCurrency(executionReport.total_agent_cost)}</span>
                              </div>
                              <div className={styles.summaryCompact}>
                                <span>Tool Cost</span>
                                <span>{formatCurrency(executionReport.total_tool_cost)}</span>
                              </div>
                              <div className={styles.summaryCompact}>
                                <span>Total Cost</span>
                                <span>{formatCurrency(executionReport.total_cost)}</span>
                              </div>
                            </div>
                          </section>
                        </>
                      ) : (
                        <p className={styles.empty}>Execution data is not available yet.</p>
                      )}
                    </div>
                  </div>
                ) : null}

                {activeTab === "payloads" ? (
                  <div className={styles.contentPane}>
                    <div className={styles.payloadList}>
                      {selectedRun.input_payloads.map((payload, index) => (
                        <PayloadCard
                          key={`${selectedRun.run_id}-payload-${index}`}
                          payload={payload}
                          index={index}
                        />
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </section>
          )}
        </section>
      </section>

      {selectedTimelineEntry ? (
        <>
          <button
            aria-label="Close details"
            className={styles.drawerScrim}
            onClick={() => {
              setSelectedTimelineId(null);
            }}
            type="button"
          />
          <aside className={styles.drawer}>
            <div className={styles.drawerHeader}>
              <div>
                <p className={styles.overline}>{formatKindLabel(selectedTimelineEntry.kind)}</p>
                {selectedTimelineEntry.kind === "tool" && selectedTimelineEntry.actor ? (
                  <span className={styles.toolActorPill}>{selectedTimelineEntry.actor}</span>
                ) : null}
                <h2>{selectedTimelineEntry.title}</h2>
              </div>
              <button
                className={styles.drawerClose}
                onClick={() => {
                  setSelectedTimelineId(null);
                }}
                type="button"
              >
                Close
              </button>
            </div>

            <div className={styles.drawerMeta}>
              <span>{selectedTimelineEntry.emoji ?? "•"}</span>
              <span>{formatTimelineTime(selectedTimelineEntry.timestamp)}</span>
              {selectedTimelineEntry.actor ? <span>{selectedTimelineEntry.actor}</span> : null}
              {selectedTimelineEntry.payload_label ? (
                <span>{selectedTimelineEntry.payload_label}</span>
              ) : null}
              {selectedTimelineEntry.status ? <span>{selectedTimelineEntry.status}</span> : null}
            </div>

            <div className={styles.drawerBody}>
              <p className={styles.drawerSummary}>{selectedTimelineEntry.summary}</p>
              {selectedTimelineEntry.is_pending_details ? (
                <div className={styles.loadingBody} aria-live="polite">
                  <span className={styles.loadingSpinner} aria-hidden="true" />
                  <span>Loading full tool output...</span>
                </div>
              ) : null}
              {selectedTimelineEntry.body && !selectedTimelineEntry.is_pending_details ? (
                <div className={styles.drawerLeadBlock}>{selectedTimelineEntry.body}</div>
              ) : null}
              {selectedTimelineEntry.attachments.length > 0 ? (
                <div className={styles.attachmentRow}>
                  {selectedTimelineEntry.attachments.map((attachment) => (
                    <button
                      key={`${selectedTimelineEntry.id}-${attachment.path}`}
                      className={styles.attachmentChip}
                      onClick={() => {
                        setSelectedAttachment(attachment);
                      }}
                      type="button"
                    >
                      <span aria-hidden="true">📄</span>
                      <span>{attachment.label}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              {selectedTimelineEntry.detail_items.map((item, index) => (
                <DetailSection
                  key={`${selectedTimelineEntry.id}-${item.label}-${index}`}
                  item={item}
                  defaultOpen={index < 2}
                />
              ))}
              {selectedTimelineEntry.raw ? (
                <DetailSection
                  item={{
                    label: "Raw Data",
                    format: "json",
                    value: selectedTimelineEntry.raw,
                  }}
                />
              ) : null}
            </div>
          </aside>
        </>
      ) : null}

      {pendingApproval && selectedRun ? (
        <aside
          aria-labelledby="approval-modal-title"
          className={styles.approvalModal}
          role="dialog"
        >
          <div className={styles.approvalModalHeader}>
            <p className={styles.overline}>Approval Required</p>
            <h2 id="approval-modal-title">Human Review Needed</h2>
          </div>
          <p className={styles.approvalModalPrompt}>{pendingApproval.prompt}</p>
          <textarea
            autoFocus
            className={styles.approvalInput}
            onChange={(event) => {
              setApprovalDraft(event.target.value);
            }}
            placeholder="Optional custom response text"
            value={approvalDraft}
          />
          <div className={styles.approvalButtons}>
            <button
              className={styles.primaryButton}
              onClick={() => {
                void handleApproval("approve");
              }}
              type="button"
            >
              Approve
            </button>
            <button
              className={styles.secondaryButton}
              onClick={() => {
                void handleApproval("reject");
              }}
              type="button"
            >
              Reject
            </button>
          </div>
        </aside>
      ) : null}

      {selectedAttachment ? (
        <>
          <button
            aria-label="Close file preview"
            className={styles.previewScrim}
            onClick={() => {
              setSelectedAttachment(null);
            }}
            type="button"
          />
          <aside className={styles.previewModal}>
            <div className={styles.previewHeader}>
              <div>
                <p className={styles.overline}>Attachment Preview</p>
                <h2>{selectedAttachment.label}</h2>
              </div>
              <button
                className={styles.drawerClose}
                onClick={() => {
                  setSelectedAttachment(null);
                }}
                type="button"
              >
                Close
              </button>
            </div>
            <div className={styles.previewActions}>
              <a
                className={styles.traceLink}
                href={buildPreviewUrl(selectedAttachment.path)}
                rel="noreferrer"
                target="_blank"
              >
                Open File
              </a>
            </div>
            <div className={styles.previewFrame}>
              <iframe
                src={buildPreviewUrl(selectedAttachment.path)}
                title={selectedAttachment.label}
              />
            </div>
          </aside>
        </>
      ) : null}
    </main>
  );
}
