import asyncio
import json
import logging
from pathlib import Path
from dataclasses import asdict, is_dataclass
from agents import (
    RunHooks,
    RunContextWrapper,
    Agent,
    Tool,
    gen_trace_id,
    get_current_trace,
)
from typing import Any, Final, Literal, Iterable, Annotated, Mapping
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict, computed_field
from dataclasses import dataclass
from agents.tracing import set_trace_processors, TracingProcessor
from agents.tracing.processors import default_processor
from agents.tracing import Trace, Span


TRACING_URL_TEMPLATE = "https://platform.openai.com/traces/trace?trace_id={trace_id}"
TRACING_FOLDER = Path("traces_logs")

EventType = Literal[
    "agent_start", "agent_end", "tool_start", "tool_end", "handoff", "unknown"
]

AGENT_AS_TOOLS_NAMING_PATTERNS: Final[list[str]] = [
    "translate",
    "agent",
    "analyzer",
    "processor",
]


class EventLog(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Annotated[EventType, Field("unknown")]
    timestamp: Annotated[datetime, Field(default_factory=datetime.now)]


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    input: Annotated[int, Field(default=0, ge=0)]
    output: Annotated[int, Field(default=0, ge=0)]
    cached: Annotated[int, Field(default=0, ge=0)]
    reasoning: Annotated[int, Field(default=0, ge=0)]
    requests: Annotated[int, Field(default=0, ge=0)]


class AgentTelemetry(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Annotated[str, Field(...)]
    model: Annotated[str | None, Field(default=None)]
    token_usage: Annotated[TokenUsage, Field(default_factory=TokenUsage)]
    tool_usage: Annotated[dict[str, int], Field(default_factory=dict)]
    start_time: Annotated[datetime | None, Field(default=None)]
    end_time: Annotated[datetime | None, Field(default=None)]

    @computed_field(return_type=float | None)
    def duration_seconds(self) -> float | None:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class TelemetryTotals(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_tokens: Annotated[int, Field(default=0, ge=0)]
    output_tokens: Annotated[int, Field(default=0, ge=0)]
    cached_tokens: Annotated[int, Field(default=0, ge=0)]
    reasoning_tokens: Annotated[int, Field(default=0, ge=0)]
    total_tokens: Annotated[int, Field(default=0, ge=0)]
    requests: Annotated[int, Field(default=0, ge=0)]


class TelemetrySummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    started_at: Annotated[datetime, Field()]
    duration_seconds: Annotated[float, Field(ge=0)]
    totals: Annotated[TelemetryTotals, Field()]
    agents: Annotated[list[AgentTelemetry], Field(default_factory=list)]
    tool_usage: Annotated[dict[str, int], Field(default_factory=dict)]
    events: Annotated[list[EventLog], Field(default_factory=list)]
    agent_tools: Annotated[list[str], Field(default_factory=list)]


class SpanAccumulatorTraceProcessor(TracingProcessor):
    def __init__(self, output_dir: str | Path = TRACING_FOLDER):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.traces: dict[str, dict[str, Any]] = {}
        self.spans: dict[str, list[dict[str, Any]]] = {}

    def on_trace_start(self, trace: Trace):
        self.traces[trace.trace_id] = trace.export()
        self.spans[trace.trace_id] = []

    def on_trace_end(self, trace: Trace):
        if trace.trace_id in self.traces:
            self.traces[trace.trace_id].update(trace.export() or {})

    def on_span_start(self, span: Span):
        pass

    def on_span_end(self, span: Span):
        if span.trace_id not in self.spans:
            return
        exported_span = span.export()

        if hasattr(span.span_data, "input"):
            input = span.span_data.input
            exported_span["input"] = (
                str(input[-1]) if isinstance(input, list) else str(input)
            )

        if hasattr(span.span_data, "response"):
            response = span.span_data.response
            exported_span["response"] = (
                response.model_dump()
                if hasattr(response, "model_dump")
                else str(response)
            )

        self.spans[span.trace_id].append(exported_span)

    def shutdown(self):
        pass

    def force_flush(self):
        pass

    def trace_dump(self, trace_id: str) -> dict[str, Any]:
        if trace_id not in self.traces:
            return dict()

        trace_data = self.traces[trace_id]
        trace_data["spans"] = self.spans.get(trace_id, [])
        return trace_data

    def write_bundle(self, trace_id: str) -> Path | None:
        """Persist trace + spans to disk. Returns path if written."""
        bundle = self.trace_dump(trace_id)
        if not bundle:
            return None
        path = self.output_dir / f"{trace_id}.json"
        path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        return path


class TelemetryRunHook(RunHooks):
    """Telemetry hooks for tracking agent execution, tool usage, and costs."""

    def __init__(
        self,
        verbose: bool = False,
        logger: logging.Logger | None = None,
        trace_processor: SpanAccumulatorTraceProcessor | None = None,
        event_queue: asyncio.Queue | None = None,
    ) -> None:
        self.verbose = verbose
        self.logger = logger
        self.start_time = datetime.now()
        self._state_lock = asyncio.Lock()
        self.events: list[EventLog] = []
        self.agents: dict[str, AgentTelemetry] = {}
        self.detected_agent_tools: set[str] = set()
        self.trace_processor = trace_processor
        self.event_queue = event_queue

        super().__init__()

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens used across all agents."""
        return sum(telemetry.token_usage.input for telemetry in self.agents.values())

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens used across all agents."""
        return sum(telemetry.token_usage.output for telemetry in self.agents.values())

    @property
    def total_requests(self) -> int:
        """Total number of requests made across all agents."""
        return sum(telemetry.token_usage.requests for telemetry in self.agents.values())

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all agents."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cached_tokens(self) -> int:
        """Total cached tokens served across all agents."""
        return sum(telemetry.token_usage.cached for telemetry in self.agents.values())

    @property
    def tool_usage(self) -> dict[str, int]:
        """Aggregate tool usage counts across all agents."""
        aggregated: dict[str, int] = {}
        for telemetry in self.agents.values():
            for tool_name, count in telemetry.tool_usage.items():
                aggregated[tool_name] = aggregated.get(tool_name, 0) + count
        return aggregated.copy()

    @property
    def duration(self) -> float:
        """Total execution time in seconds."""
        return (datetime.now() - self.start_time).total_seconds()

    async def _log_event(self, event_type: EventType, **kwargs) -> None:
        """Log an event with timestamp."""
        event = EventLog(type=event_type, **kwargs)
        async with self._state_lock:
            self.events.append(event)

        if self.event_queue:
            await self.event_queue.put(event.model_dump(mode="json"))

        self._emit_verbose_event(event)

    def _emit_verbose_event(self, event: EventLog) -> None:
        """Emit verbose logging for events when enabled."""
        if not self.verbose:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        message = f"[{timestamp}] {self._format_event_for_verbose(event.model_dump(mode='json'))}"

        if self.logger is not None:
            self.logger.info(message)
        else:
            print(message)

    def _format_event_for_verbose(self, event_data: dict[str, Any]) -> str:
        """Render an event dictionary as a readable string for verbose output."""
        event_type = event_data.get("type", "unknown")
        details = [
            f"{key}={event_data[key]}"
            for key in sorted(event_data.keys())
            if key not in {"type"}
        ]
        return f"{event_type} | " + ", ".join(details) if details else event_type

    def _get_agent_telemetry(self, agent_name: str) -> AgentTelemetry:
        """Ensure telemetry container exists for an agent."""
        telemetry = self.agents.get(agent_name)
        if telemetry is None:
            telemetry = AgentTelemetry(name=agent_name)
            self.agents[agent_name] = telemetry
        return telemetry

    async def on_agent_start(self, context: RunContextWrapper, agent: Agent) -> None:
        """Called when an agent starts execution."""
        detected_agent_tools: set[str] = set()
        if hasattr(agent, "tools") and agent.tools:
            detected_agent_tools = self._detect_agent_tools(agent)

        started_at = datetime.now()
        async with self._state_lock:
            telemetry = self._get_agent_telemetry(agent.name)
            if telemetry.start_time is None:
                telemetry.start_time = started_at
            telemetry.model = agent.model
            if detected_agent_tools:
                self.detected_agent_tools.update(detected_agent_tools)

        await self._log_event("agent_start", agent_name=agent.name)

    async def on_agent_end(
        self, context: RunContextWrapper, agent: Agent, output: Any
    ) -> None:
        """Called when an agent completes execution."""
        ended_at = datetime.now()

        async with self._state_lock:
            telemetry = self._get_agent_telemetry(agent.name)
            if telemetry.start_time is None:
                telemetry.start_time = ended_at
            telemetry.end_time = ended_at
            telemetry.model = agent.model or telemetry.model

            if context.usage:
                token_usage = telemetry.token_usage
                token_usage.input += context.usage.input_tokens
                token_usage.output += context.usage.output_tokens
                token_usage.cached += context.usage.input_tokens_details.cached_tokens
                token_usage.reasoning = (
                    context.usage.output_tokens_details.reasoning_tokens
                )
                token_usage.requests += context.usage.requests

        self._write_trace_snapshot()

        await self._log_event(
            "agent_end",
            agent_name=agent.name,
            model=agent.model,
            input_tokens=context.usage.input_tokens,
            output_tokens=context.usage.output_tokens,
            cached_tokens=context.usage.input_tokens_details.cached_tokens,
            reasoning_tokens=context.usage.output_tokens_details.reasoning_tokens,
            requests=context.usage.requests,
        )

    async def on_tool_start(
        self, context: RunContextWrapper, agent: Agent, tool: Tool
    ) -> None:
        """Called when a tool starts execution."""
        tool_name = tool.name
        async with self._state_lock:
            telemetry = self._get_agent_telemetry(agent.name)
            telemetry.tool_usage[tool_name] = telemetry.tool_usage.get(tool_name, 0) + 1
        await self._log_event("tool_start", agent_name=agent.name, tool_name=tool_name)

    async def on_tool_end(
        self, context: RunContextWrapper, agent: Agent, tool: Tool, result: Any
    ) -> None:
        """Called when a tool completes execution."""
        self._write_trace_snapshot()
        await self._log_event(
            "tool_end",
            agent_name=agent.name,
            tool_name=tool.name,
            tool_output=_serialize_event_payload(result),
        )

    async def on_handoff(
        self, context: RunContextWrapper, from_agent: Agent, to_agent: Agent
    ) -> None:
        """Called when control is handed off between agents."""
        await self._log_event(
            "handoff", from_agent=from_agent.name, to_agent=to_agent.name
        )

    def _detect_agent_tools(self, orchestrator: Agent) -> set[str]:
        """Detect if this agent uses other agents as tools for reporting purposes."""
        agent_tool_names = []
        for tool in orchestrator.tools:
            if any(
                keyword in tool.name.lower()
                for keyword in AGENT_AS_TOOLS_NAMING_PATTERNS
            ):
                agent_tool_names.append(tool.name)

        return set(agent_tool_names)

    def _write_trace_snapshot(self) -> None:
        """Persist current trace + spans via the configured trace processor."""
        if not self.trace_processor:
            return

        current_trace = get_current_trace()
        if current_trace is None:
            return

        trace_id = current_trace.trace_id
        path = self.trace_processor.write_bundle(trace_id)

    def export_summary(self) -> TelemetrySummary:
        """Produce a summary snapshot of collected telemetry."""
        totals = TelemetryTotals(
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            cached_tokens=self.total_cached_tokens,
            total_tokens=self.total_tokens,
            requests=self.total_requests,
        )

        return TelemetrySummary(
            started_at=self.start_time,
            duration_seconds=self.duration,
            totals=totals,
            agents=list(self.agents.values()),
            tool_usage=self.tool_usage,
            events=self.events.copy(),
            agent_tools=sorted(self.detected_agent_tools),
        )



def setup_run_hooks(
    verbose: bool = False,
    logger: logging.Logger | None = None,
    save_traces: bool = True,
    event_queue: asyncio.Queue | None = None,
) -> TelemetryRunHook:
    """Setup orchestration tracing and return hooks, trace_id, and trace_url.

    Args:
        verbose: Whether to use verbose hooks that print events in real-time
        logger: Optional logger
        save_traces: Whether to save traces to disk
        event_queue: Optional queue to stream events to

    Returns:
        RunHooks: hooks to be used.
    """

    # Create local trace accumulator and keep the default backend processor.
    trace_processor = None
    if save_traces:
        # Ensure trace folder exists up front
        TRACING_FOLDER.mkdir(parents=True, exist_ok=True)
        trace_processor = SpanAccumulatorTraceProcessor(output_dir=TRACING_FOLDER)
        set_trace_processors([default_processor(), trace_processor])

    # Create hooks for tracking
    run_hooks = TelemetryRunHook(verbose, logger, trace_processor=trace_processor, event_queue=event_queue)

    return run_hooks


def _serialize_event_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if hasattr(value, "model_dump"):
        return _serialize_event_payload(value.model_dump(mode="json"))

    if is_dataclass(value):
        return _serialize_event_payload(asdict(value))

    if isinstance(value, Mapping):
        return {
            str(key): _serialize_event_payload(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_serialize_event_payload(item) for item in value]

    return str(value)

def setup_tracing() -> tuple[str, str]:
    """Setup orchestration tracing and trace_id, and trace_url.

    Returns:
        tuple: (trace_id, trace_url)
    """
    # Generate trace ID for monitoring
    trace_id = gen_trace_id()
    trace_url = TRACING_URL_TEMPLATE.format(trace_id=trace_id)
    print(f"🔗 Trace URL: {trace_url}\n")

    return trace_id, trace_url


DetailLevel = Literal["high", "low"]
VALID_DETAIL_LEVELS: Final[frozenset[str]] = frozenset({"high", "low"})

# ---- constants (from OpenAI docs) ----
PATCH_SIZE: Final[int] = 32
MAX_PATCHES: Final[int] = 1536

TILE_SIZE: Final[int] = 512
MAX_FIT: Final[int] = 2048
SHORT_HIGH: Final[int] = 768  # shortest-side target for 4o/4.1/o-series
SHORT_IMG1: Final[int] = 512  # shortest-side target for gpt-image-1

MODEL_COSTS: Final[dict[str, dict[str, float]]] = {
    # Prices are per 1M tokens
    "gpt-5.4": {
        "input": 2.50 / 1_000_000,
        "cached_input": 0.25 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
    "gpt-5.4-pro": {
        "input": 30.00 / 1_000_000,
        "output": 180.00 / 1_000_000,
    },
    "gpt-5.3-chat-latest": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5.3-chat": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5.3-codex": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5.2": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5.2-pro": {
        "input": 15.00 / 1_000_000,
        "output": 120.00 / 1_000_000,
    },
    "gpt-5.2-chat": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5.2-codex": {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.00 / 1_000_000,
    },
    "gpt-5": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5-mini": {
        "input": 0.25 / 1_000_000,
        "cached_input": 0.025 / 1_000_000,
        "output": 2.00 / 1_000_000,
    },
    "gpt-5-nano": {
        "input": 0.05 / 1_000_000,
        "cached_input": 0.005 / 1_000_000,
        "output": 0.40 / 1_000_000,
    },
    "gpt-5-codex": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5-chat-latest": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5-search-api": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5-pro": {
        "input": 15.00 / 1_000_000,
        "output": 120.00 / 1_000_000,
    },
    "gpt-5.1": {  # alias safety for older names
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5.1-chat": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5.1-chat-latest": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5.1-codex": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5.1-codex-max": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5.1-codex-mini": {
        "input": 0.25 / 1_000_000,
        "cached_input": 0.025 / 1_000_000,
        "output": 2.00 / 1_000_000,
    },
    "gpt-4.1": {
        "input": 2.00 / 1_000_000,
        "cached_input": 0.50 / 1_000_000,
        "output": 8.00 / 1_000_000,
    },
    "gpt-4.1-mini": {
        "input": 0.40 / 1_000_000,
        "cached_input": 0.10 / 1_000_000,
        "output": 1.60 / 1_000_000,
    },
    "gpt-4.1-nano": {
        "input": 0.10 / 1_000_000,
        "cached_input": 0.025 / 1_000_000,
        "output": 0.40 / 1_000_000,
    },
    "gpt-4o": {
        "input": 2.50 / 1_000_000,
        "cached_input": 1.25 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-4o-2024-05-13": {
        "input": 5.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
    "gpt-4o-mini": {
        "input": 0.15 / 1_000_000,
        "cached_input": 0.075 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },
    "gpt-4o-mini-search-preview": {
        "input": 0.15 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },
    "gpt-4o-search-preview": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-4o-realtime-preview": {
        "input": 5.00 / 1_000_000,
        "cached_input": 2.50 / 1_000_000,
        "output": 20.00 / 1_000_000,
    },
    "gpt-4o-mini-realtime-preview": {
        "input": 0.60 / 1_000_000,
        "cached_input": 0.30 / 1_000_000,
        "output": 2.40 / 1_000_000,
    },
    "gpt-realtime": {
        "input": 4.00 / 1_000_000,
        "cached_input": 0.40 / 1_000_000,
        "output": 16.00 / 1_000_000,
    },
    "gpt-realtime-mini": {
        "input": 0.60 / 1_000_000,
        "cached_input": 0.06 / 1_000_000,
        "output": 2.40 / 1_000_000,
    },
    "gpt-audio": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-audio-mini": {
        "input": 0.60 / 1_000_000,
        "output": 2.40 / 1_000_000,
    },
    "gpt-4o-audio-preview": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-4o-mini-audio-preview": {
        "input": 0.15 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },
    "o1": {
        "input": 15.00 / 1_000_000,
        "cached_input": 7.50 / 1_000_000,
        "output": 60.00 / 1_000_000,
    },
    "o1-mini": {
        "input": 1.10 / 1_000_000,
        "cached_input": 0.55 / 1_000_000,
        "output": 4.40 / 1_000_000,
    },
    "o1-pro": {
        "input": 150.00 / 1_000_000,
        "output": 600.00 / 1_000_000,
    },
    "o3": {
        "input": 2.00 / 1_000_000,
        "cached_input": 0.50 / 1_000_000,
        "output": 8.00 / 1_000_000,
    },
    "o3-pro": {
        "input": 20.00 / 1_000_000,
        "output": 80.00 / 1_000_000,
    },
    "o3-deep-research": {
        "input": 10.00 / 1_000_000,
        "cached_input": 2.50 / 1_000_000,
        "output": 40.00 / 1_000_000,
    },
    "o3-mini": {
        "input": 1.10 / 1_000_000,
        "cached_input": 0.55 / 1_000_000,
        "output": 4.40 / 1_000_000,
    },
    "o4-mini": {
        "input": 1.10 / 1_000_000,
        "cached_input": 0.275 / 1_000_000,
        "output": 4.40 / 1_000_000,
    },
    "o4-mini-deep-research": {
        "input": 2.00 / 1_000_000,
        "cached_input": 0.50 / 1_000_000,
        "output": 8.00 / 1_000_000,
    },
    "gpt-4o-mini-search": {  # alias for safety
        "input": 0.15 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },
    "gpt-4o-search": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "computer-use-preview": {
        "input": 3.00 / 1_000_000,
        "output": 12.00 / 1_000_000,
    },
    "gpt-image-1": {
        "input": 5.00 / 1_000_000,
        "cached_input": 1.25 / 1_000_000,
        "output": 0.0,  # image models charge on input only
    },
    "gpt-image-1-mini": {
        "input": 2.00 / 1_000_000,
        "cached_input": 0.20 / 1_000_000,
        "output": 0.0,
    },
    "codex-mini-latest": {
        "input": 1.50 / 1_000_000,
        "cached_input": 0.375 / 1_000_000,
        "output": 6.00 / 1_000_000,
    },
}

# ---- agent & tool usage pricing ----

LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL: Final[str] = "gpt-5"

TOOL_CALL_COSTS: Final[dict[str, float]] = {
    "openai_web_search": 0.025,  # $25 per 1000 calls = $0.025 per call (custom)
    "openai_file_search": 0.0025,  # $2.50 per 1000 calls = $0.0025 per call
    "openai_code_interpreter": 0.03,  # $0.03 per call
    "openai_image_analysis": 0.0,  # No per-call cost, billed as tokens
}


@dataclass(frozen=True)
class CostSummary:
    """Aggregated pricing information for a telemetry summary."""

    agent_costs: dict[str, float]
    tool_costs: dict[str, float]
    total_agent_cost: float
    total_tool_cost: float

    @property
    def total_cost(self) -> float:
        """Return the combined agent and tool costs."""
        return self.total_agent_cost + self.total_tool_cost


class ExecutionReportAgent(BaseModel):
    """Agent-level execution details for UI and API consumers."""

    name: Annotated[str, Field(...)]
    model: Annotated[str | None, Field(default=None)]
    total_tokens: Annotated[int, Field(default=0, ge=0)]
    requests: Annotated[int, Field(default=0, ge=0)]
    input_tokens: Annotated[int, Field(default=0, ge=0)]
    output_tokens: Annotated[int, Field(default=0, ge=0)]
    cached_tokens: Annotated[int, Field(default=0, ge=0)]
    reasoning_tokens: Annotated[int, Field(default=0, ge=0)]
    cost: Annotated[float, Field(default=0.0, ge=0)]


class ExecutionReportTool(BaseModel):
    """Tool usage details for UI and API consumers."""

    name: Annotated[str, Field(...)]
    calls: Annotated[int, Field(default=0, ge=0)]
    cost: Annotated[float, Field(default=0.0, ge=0)]


class ExecutionReport(BaseModel):
    """Structured execution report derived from telemetry."""

    started_at: Annotated[datetime, Field()]
    duration_seconds: Annotated[float, Field(default=0.0, ge=0)]
    agent_count: Annotated[int, Field(default=0, ge=0)]
    agents: Annotated[list[ExecutionReportAgent], Field(default_factory=list)]
    tools: Annotated[list[ExecutionReportTool], Field(default_factory=list)]
    totals: Annotated[TelemetryTotals, Field()]
    total_agent_cost: Annotated[float, Field(default=0.0, ge=0)]
    total_tool_cost: Annotated[float, Field(default=0.0, ge=0)]
    total_cost: Annotated[float, Field(default=0.0, ge=0)]


def _normalize_model_name(model_name: str | None) -> str:
    """Return a supported model name, defaulting when necessary."""
    if not model_name:
        return DEFAULT_MODEL

    normalized = model_name.strip().lower()
    if normalized not in MODEL_COSTS:
        LOGGER.warning(
            "Unknown model '%s', defaulting to %s pricing",
            model_name,
            DEFAULT_MODEL,
        )
        return DEFAULT_MODEL
    return normalized


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model_name: str | None,
    cached_input_tokens: int = 0,
) -> float:
    """Calculate token pricing for a given model."""
    normalized_model = _normalize_model_name(model_name)
    model_costs = MODEL_COSTS[normalized_model]
    cost_per_input = model_costs["input"]
    cost_per_cached_input = model_costs.get("cached_input", cost_per_input)
    cost_per_output = model_costs["output"]

    uncached_input = max(input_tokens - cached_input_tokens, 0)
    return (
        (uncached_input * cost_per_input)
        + (cached_input_tokens * cost_per_cached_input)
        + (output_tokens * cost_per_output)
    )


def calculate_tool_costs(tool_usage: Mapping[str, int]) -> dict[str, float]:
    """Return per-tool pricing based on recorded usage counts."""
    costs: dict[str, float] = {}
    for tool_name, count in tool_usage.items():
        per_call_cost = TOOL_CALL_COSTS.get(tool_name, 0.0)
        costs[tool_name] = count * per_call_cost
    return costs


def calculate_agent_costs(summary: TelemetrySummary) -> dict[str, float]:
    """Return per-agent costs using telemetry token usage."""
    agent_costs: dict[str, float] = {}
    for telemetry in summary.agents:
        usage = telemetry.token_usage
        agent_costs[telemetry.name] = calculate_cost(
            usage.input,
            usage.output,
            telemetry.model,
            usage.cached,
        )
    return agent_costs


def summarize_costs(summary: TelemetrySummary) -> CostSummary:
    """Produce a full cost breakdown for the given telemetry summary."""
    agent_costs = calculate_agent_costs(summary)
    tool_costs = calculate_tool_costs(summary.tool_usage)

    total_agent_cost = sum(agent_costs.values())
    total_tool_cost = sum(tool_costs.values())

    return CostSummary(
        agent_costs=agent_costs,
        tool_costs=tool_costs,
        total_agent_cost=total_agent_cost,
        total_tool_cost=total_tool_cost,
    )


def build_execution_report(summary: TelemetrySummary) -> ExecutionReport:
    """Return a structured execution report for API and UI rendering."""

    cost_summary = summarize_costs(summary)
    agents = [
        ExecutionReportAgent(
            name=telemetry.name,
            model=telemetry.model,
            total_tokens=telemetry.token_usage.input + telemetry.token_usage.output,
            requests=telemetry.token_usage.requests,
            input_tokens=telemetry.token_usage.input,
            output_tokens=telemetry.token_usage.output,
            cached_tokens=telemetry.token_usage.cached,
            reasoning_tokens=telemetry.token_usage.reasoning,
            cost=cost_summary.agent_costs.get(telemetry.name, 0.0),
        )
        for telemetry in summary.agents
    ]
    tools = [
        ExecutionReportTool(
            name=tool_name,
            calls=count,
            cost=cost_summary.tool_costs.get(tool_name, 0.0),
        )
        for tool_name, count in sorted(summary.tool_usage.items())
    ]

    return ExecutionReport(
        started_at=summary.started_at,
        duration_seconds=summary.duration_seconds,
        agent_count=len(summary.agents),
        agents=agents,
        tools=tools,
        totals=summary.totals,
        total_agent_cost=cost_summary.total_agent_cost,
        total_tool_cost=cost_summary.total_tool_cost,
        total_cost=cost_summary.total_cost,
    )


SEPARATOR: Final[str] = "=" * 60


def format_event(event: EventLog) -> str:
    """Return a readable representation for a telemetry event."""
    payload = event.model_dump()
    event_type = payload.get("type", "unknown")

    if event_type == "agent_start":
        return f"[Agent start] `{payload.get('agent_name', 'unknown')}`"
    if event_type == "agent_end":
        tokens_info = ""
        if payload.get("input_tokens") or payload.get("output_tokens"):
            tokens_info = (
                f" (in: {payload.get('input_tokens', 0):,}, "
                f"out: {payload.get('output_tokens', 0):,})"
            )
        return f"[Agent end] `{payload.get('agent_name', 'unknown')}`{tokens_info}"
    if event_type == "tool_start":
        return (
            f"[Tool start] `{payload.get('tool_name', 'unknown')}` "
            f"by `{payload.get('agent_name', 'unknown')}`"
        )
    if event_type == "tool_end":
        return (
            f"[Tool end] `{payload.get('tool_name', 'unknown')}` "
            f"by `{payload.get('agent_name', 'unknown')}`"
        )
    if event_type == "handoff":
        return (
            f"[Handoff] from `{payload.get('from_agent', 'unknown')}` "
            f"to `{payload.get('to_agent', 'unknown')}`"
        )
    return f"[Unknown event] {payload}"


def build_event_log(summary: TelemetrySummary, limit: int | None = None) -> str:
    """Return a multi-line representation of the event log."""
    events: Iterable[EventLog] = summary.events[-limit:] if limit else summary.events
    lines: list[str] = ["EVENT LOG", "-" * 60]

    for event in events:
        timestamp = event.timestamp.strftime("%H:%M:%S")
        lines.append(f"[{timestamp}] {format_event(event)}")

    if limit and len(summary.events) > limit:
        lines.append(f"... showing last {limit} of {len(summary.events)} events")

    return "\n".join(lines)


def build_execution_summary(summary: TelemetrySummary) -> str:
    """Return a formatted execution summary using telemetry and cost data."""
    cost_summary = summarize_costs(summary)

    def _agent_lines() -> list[str]:
        return [
            (
                f"   - {telemetry.name} ({telemetry.model or 'unknown'}): "
                f"{telemetry.token_usage.input + telemetry.token_usage.output:,} tokens "
                f"({telemetry.token_usage.requests} requests)"
            )
            for telemetry in summary.agents
        ]

    def _tool_lines() -> list[str]:
        return [
            f"   - {tool_name}: {count} calls"
            + (
                f" | ${cost_summary.tool_costs[tool_name]:.4f}"
                if cost_summary.tool_costs.get(tool_name)
                else ""
            )
            for tool_name, count in sorted(summary.tool_usage.items())
        ]

    def _agent_cost_lines() -> list[str]:
        return [
            f"   - {telemetry.name} ({telemetry.model or 'gpt-4.1'}): "
            f"${cost_summary.agent_costs.get(telemetry.name, 0.0):.4f}"
            for telemetry in summary.agents
        ]

    lines: list[str] = [
        "",
        SEPARATOR,
        "EXECUTION SUMMARY",
        SEPARATOR,
        "",
        f"Duration: {summary.duration_seconds:.2f} seconds",
        f"Started: {summary.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Agents: {len(summary.agents)}",
    ]
    lines.extend(_agent_lines())

    if summary.tool_usage:
        lines.extend(["", "Tools Used:"])
        lines.extend(_tool_lines())

    totals = summary.totals
    lines.extend(
        [
            "",
            "Token Usage:",
            f"   - Input: {totals.input_tokens:,}",
            f"   - Output: {totals.output_tokens:,}",
            f"   - Cached: {totals.cached_tokens:,}",
            f"   - Total: {totals.total_tokens:,}",
            f"   - Requests: {totals.requests}",
            "",
            "Cost Analysis:",
        ]
    )
    lines.extend(_agent_cost_lines())

    if any(cost_summary.tool_costs.values()):
        lines.extend(
            f"   - {tool_name}: ${tool_cost:.4f}"
            for tool_name, tool_cost in sorted(cost_summary.tool_costs.items())
            if tool_cost > 0
        )

    lines.append(f"   - Total Tool Cost: ${cost_summary.total_tool_cost:.4f}")
    lines.append(f"   - Total Cost: ${cost_summary.total_cost:.4f}")

    if summary.agent_tools:
        agent_tools = ", ".join(sorted(summary.agent_tools))
        lines.extend(
            [
                "",
                "Note: agent-as-tool usage detected "
                f"({agent_tools}). Costs are recorded under "
                "their respective agents.",
            ]
        )

    lines.extend(["", SEPARATOR, ""])
    return "\n".join(lines)


def emit_execution_summary(
    summary: TelemetrySummary, logger: logging.Logger | None = None
) -> None:
    """Emit the execution summary using the provided logger or standard output."""
    message = build_execution_summary(summary)
    if logger:
        logger.info(message)
    else:
        print(message)


class ReceivedAttachment(BaseModel):
    """Schema describing an attachment received with the email."""

    path: Annotated[
        str,
        Field(
            ...,
            description=(
                "Relative path to the attachment within the attachments folder."
            ),
        ),
    ]
    extension: Annotated[
        str,
        Field(..., description="File extension of the attachment (e.g., pdf, xlsx)."),
    ]


class ReceivedEmail(BaseModel):
    """Schema describing an email that has been received."""

    sender: Annotated[str, Field(..., description="Email address that sent it.")]
    sent_to: Annotated[
        list[str],
        Field(default_factory=list, description="Addresses the email was sent to."),
    ]
    subject: Annotated[str, Field(..., description="Email subject line.")]
    body: Annotated[str, Field(..., description="Email body content.")]
    attachments: Annotated[
        list[ReceivedAttachment],
        Field(
            default_factory=list,
            description=(
                "Attachments with relative paths and extensions for each file."
            ),
        ),
    ]
    metadata: Annotated[
        dict[str, Any],
        Field(
            default_factory=dict,
            description="Other information, like email chain, background context.",
        ),
    ]
