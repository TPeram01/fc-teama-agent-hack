# Repository Guidelines

## Project Structure & Module Organization
- `main.py` is the primary CLI entrypoint. It loads `.env`, restores top-level runtime JSON state from `*_original.json`, dispatches payloads to `run_manager`, and supports `--payload`, `--scenario`, `--list-scenarios`, and `--save-runtime-data`.
- `api.py` exposes FastAPI endpoints (`GET /`, `POST /agents/run`) around the same manager workflow used by the CLI. Because it imports `main.py`, starting the API also restores top-level runtime JSON state.
- `custom_agents/manager.py` is the top-level orchestrator. It routes events to the current specialist agents in `custom_agents/lead_reviewer.py`, `custom_agents/response_ingestion.py`, and `custom_agents/infotrack.py`.
- `tools/` contains the callable agent tools for the mocked Salesforce, email, Laserfiche, Zocks, OCR/document-processing, calculator, and HITL flows. Re-export shared tool entrypoints from `tools/__init__.py`.
- `guardrails/` contains agent and tool guardrails, including confidence, moderation, prompt-injection, on-topic, PII, and document-classification protections.
- `utils.py` owns telemetry hooks, trace persistence, execution summaries, and model/tool cost helpers.
- `evals/` and `evals.py` build evaluation datasets from `traces_logs/` and launch registered OpenAI eval jobs.
- `data/` stores the active mocked runtime systems used by the workflow: scenarios, inbound emails, Salesforce records, Laserfiche state, cached document-processing results, and sample PDF inputs.
- `scripts/reset_runtime_data.py` restores the top-level runtime JSON files in `data/` from their preserved `*_original.json` counterparts.
- `scripts/pdf_to_image_only_pdf.py` converts PDFs into image-only PDFs for OCR-focused document-processing scenarios.

## Environment & Configuration
- Python `3.14` is required (see `.python-version`).
- Dependencies are managed with `uv`; they are declared in `pyproject.toml` and pinned in `uv.lock`.
- `.env` is loaded in `main.py` and by guardrail/eval modules. Set `OPENAI_API_KEY` before running the CLI, API, or eval flows.
- `data/scenarios.json` is active and is the source of truth for runnable CLI scenarios and supported payload types.
- Top-level runtime JSON files in `data/` are intentionally mutable during runs and are reset from `*_original.json` baselines at workflow startup.
- Runtime trace bundles are written under `traces_logs/` when `setup_run_hooks(save_traces=True)` is enabled.
- Keep secrets, local trace dumps, and generated eval datasets out of git unless they are intentionally versioned.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and type hints everywhere.
- Use modern typing: `list`, `dict`, `tuple`, and unions like `Type | None` (avoid `List`, `Dict`, `Optional`).
- Pydantic fields should use `Annotated[Type, Field(...)]` (example: `name: Annotated[str, Field(min_length=1)]`).
- Agent outputs and tool inputs should be Pydantic-friendly and strongly typed.
- For guardrail verdicts/classifications, define explicit Pydantic models with clear field descriptions.
- Never use `*` in imports. Always explicitly import the required symbols.
- Tool functions must include clear, complete Google-style docstrings for agent readability. Include a summary line followed by `Args` and `Returns` sections with types; do not include `Raises`. Non-tool public functions may have a brief one-sentence docstring. Private functions should not have docstrings.
- Prefer functional style where it fits, and keep functions short, simple, and easy to read.
- Embrace simplicity over complexity; avoid clever abstractions unless they reduce code size and improve clarity.
- Do not overuse `try/except`; only add explicit error handling when required.
- Use fail-fast guard clauses: put negative checks at the top of functions with early `return` or `raise`.
- In loops, prefer `if <reverse logic>: continue` near the top before the main logic.
- Keep guardrail and policy constants at module scope with uppercase names (for example, thresholds and compiled regex patterns).

## Testing Guidelines
- The repo currently includes a `unittest`-style test module in `tests.py`.
- Run the current test suite with `uv run python -m unittest tests.py`.
- No coverage thresholds are configured yet.
- If you add tests, prefer `pytest` under `tests/` with names like `test_*.py`, but do not break the existing `tests.py` workflow unless you are intentionally migrating it.

## Commit & Pull Request Guidelines
- Use short imperative commit subjects with a prefix when helpful, for example `docs: refresh repo guide` or `feat: wire manager tools`.
- PRs should include the behavior change, commands run, required env/data setup, and sample payloads or `/docs` screenshots when API behavior changes.
- Call out placeholder or scaffold-only areas explicitly so reviewers know what is intentionally incomplete.

## Agent-Specific Notes
- The current workflow supports three event shapes through the manager agent:
  - Salesforce `new_lead` notifications
  - inbound client-response emails
  - Salesforce `meeting_close` notifications
- `lead_reviewer` handles qualification, duplicate/existing-client screening, status updates, advisor search, assignment, and HITL approval only when remote fallback approval is required.
- `response_ingestion` handles inbound email reading, attachment OCR/classification, Salesforce updates, meeting scheduling on explicit confirmation, follow-up emails, and Laserfiche vs Salesforce document routing.
- `infotrack` handles missing-information outreach, advisor-calendar-based scheduling options, and post-meeting follow-up using Zocks summaries/action items.
- Treat `data/scenarios.json`, `data/emails.json`, `data/salesforce_*.json`, and `data/laserfiche.json` as the mocked system state for local workflow behavior.
- Preserve the strong typing discipline already present in agent outputs and tool return models; when extending the workflow, update both the Pydantic models and the README/AGENTS docs together.
