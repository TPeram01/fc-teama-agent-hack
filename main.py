from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from workflow.runner import (
    get_scenario_definition,
    list_scenarios_for_cli,
    restore_runtime_state,
    run_scenario_by_id,
    run_single_payload,
    save_runtime_state,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the First Command workflow."
    )
    parser.add_argument(
        "--payload",
        default=None,
        help="Path to the JSON payload (overrides --scenario).",
    )
    parser.add_argument(
        "--scenario",
        default="e2e_test",
        help="Scenario ID from data/scenarios.json to run.",
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
        saved_paths = save_runtime_state()
        if not saved_paths:
            print("No runtime JSON files found to save.")
            return

        print(f"Saved {len(saved_paths)} runtime JSON file(s):")
        for saved_path in saved_paths:
            print(saved_path)
        return

    if args.list_scenarios:
        for line in list_scenarios_for_cli():
            print(line)
        return

    if args.payload:
        payload_path = Path(args.payload)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        restore_runtime_state()
        asyncio.run(
            run_single_payload(
                payload=payload,
                scenario_name="Payload",
            )
        )
        return

    try:
        scenario = get_scenario_definition(args.scenario)
    except KeyError:
        available = ", ".join(
            line.removesuffix(":")
            for line in list_scenarios_for_cli()
            if line.endswith(":")
        )
        print(
            f"Error: Scenario '{args.scenario}' not found. Available: {available}"
        )
        return

    print(f"[Run] Loading scenario: {scenario.id} ({scenario.description})")
    restore_runtime_state()
    asyncio.run(
        run_scenario_by_id(
            scenario_id=scenario.id,
        )
    )


if __name__ == "__main__":
    main()
