import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agents import Runner, SQLiteSession, trace
from custom_agents import ManagerOutput, make_manager_agent
from tools import update_meeting_notes
from scripts.reset_runtime_data import restore_runtime_data, save_runtime_data
from utils import (
    TelemetryRunHook,
    emit_execution_summary,
    setup_run_hooks,
    setup_tracing,
)

AGENT_MAX_TURNS = 25
load_dotenv(override=True)

# Reset runtime data
_ = restore_runtime_data()

async def run_manager(
    payload: dict[str, Any],
    run_hooks: TelemetryRunHook | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    scenario_name: str | None = None,
) -> tuple[ManagerOutput, TelemetryRunHook, str, str]:
    run_hooks = run_hooks or setup_run_hooks(verbose=False)
    session_id = session_id or uuid.uuid4().hex
    if trace_id is None:
        trace_id, _ = setup_tracing()

    session = SQLiteSession(session_id=session_id)
    workflow_name = (
        f"Finance Workflow- {scenario_name}" if scenario_name else "Finance Workflow Workflow"
    )

    print("[Run] Payload: provided JSON")
    print(f"[Run] Workflow name: {workflow_name}")
    print(f"[Run] Session: {session.session_id}")
    print(f"[Run] Payload type: {payload["payload_type"]}")
    if payload["payload_type"] == "salesforce_notification":
        print(f"[Run] Notification: {payload["salesforce_trigger_type"]}")
    print("[Run] Dispatching to Manager agent...\n")

    if payload["payload_type"] == "salesforce_notification" and payload["salesforce_trigger_type"] == "meeting_close":
        print(f"🔄  Meeting complete. Pushing Zocks notes to Salesforce...\n")
        try:
            update_meeting_notes(payload["UID"], payload["meeting_notes"])
        except ValueError as e:
            print("🟧 WARNING: Could not find migrate meeting notes from Zocks.")
            print(e)

    manager_agent = make_manager_agent(hooks=run_hooks)

    with trace(workflow_name=workflow_name, trace_id=trace_id):
        result = await Runner().run(
            starting_agent=manager_agent,
            input=json.dumps(payload),
            hooks=run_hooks,
            session=session,
            max_turns=AGENT_MAX_TURNS,
        )

    output: ManagerOutput = result.final_output
    try:
        print("Manager summary:")
        print(f"  summary  : {output.summary or 'n/a'}")
        print(f"  status   : {output.status}")
        print(f"  email    : {output.email_type or 'n/a'}")
        print(f"  actions  : {', '.join(output.actions) if output.actions else 'n/a'}")
        print(f"  gaps     : {', '.join(output.gaps) if output.gaps else 'n/a'}")
        print(f"  escalate : {output.escalation_summary or 'n/a'}")
    except AttributeError as e:
        print("🟧 WARNING: Attempting to print missing items from manager output.")
        print(e)

    return output, run_hooks, trace_id, session_id


async def run_manager_inputs(
    inputs: list[dict[str, Any]], scenario: str | None = None
) -> None:
    run_hooks: TelemetryRunHook | None = None
    trace_id: str | None = None
    session_id: str | None = None
    scenario_name = scenario.replace("_", " ").title() if scenario else None

    for index, payload in enumerate(inputs, start=1):
        print(f"\n➡️  [Run] Input {index}/{len(inputs)} =========================================================>>\n")
        _output, run_hooks, trace_id, session_id = await run_manager(
            payload=payload,
            run_hooks=run_hooks,
            trace_id=trace_id,
            session_id=session_id,
            scenario_name=scenario_name,
        )
        print(f"\n✅  [Complete] Input {index}/{len(inputs)} ====================================================||\n")

    if run_hooks is None:
        return

    summary = run_hooks.export_summary()
    emit_execution_summary(summary)
    

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Invoice Approval Manager workflow."
    )
    parser.add_argument(
        "--payload",
        default=None,
        help="Path to the JSON payload (overrides --scenario).",
    )
    parser.add_argument(
        "--scenario",
        default="e2e_test",
        help="Scenario ID from scenarios.json to run.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List the scenario IDs from data/scenarios.json and exit.",
    )
    parser.add_argument(
        "--save-runtime-data",
        action="store_true",
        help="Save the current runtime JSON files as preserved originals and exit.",
    )
    args = parser.parse_args()

    if args.save_runtime_data:
        saved_paths = save_runtime_data()
        if not saved_paths:
            print("No runtime JSON files found to save.")
            return

        print(f"Saved {len(saved_paths)} runtime JSON file(s):")
        for saved_path in saved_paths:
            print(saved_path)
        return

    if args.payload:
        payload_path = Path(args.payload)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        _output, run_hooks, _trace_id, _session_id = asyncio.run(
            run_manager(payload, scenario_name="Payload")
        )
        summary = run_hooks.export_summary()
        emit_execution_summary(summary)
        return

    # Load scenarios from data/scenarios.json.
    try:
        with open("data/scenarios.json", "r", encoding="utf-8") as f:
            scenarios_data = json.load(f)
            scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}
    except FileNotFoundError:
        print("Error: data/scenarios.json not found.")
        return

    if args.list_scenarios:
        for scenario in scenarios.values():
            print(f"{scenario['id']}:")
            print(f"  {scenario['description']}")
            print()
        return

    if args.scenario not in scenarios:
        print(
            f"Error: Scenario '{args.scenario}' not found. Available: {', '.join(scenarios.keys())}"
        )
        return

    scenario = scenarios[args.scenario]
    print(f"[Run] Loading scenario: {scenario['id']} ({scenario['description']})")

    payloads = scenario.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        print(f"Error: Scenario '{scenario['id']}' has no payloads to run.")
        return

    asyncio.run(run_manager_inputs(payloads, scenario["id"]))


if __name__ == "__main__":
    main()
