import asyncio

from agents import function_tool

from workflow_context import get_workflow_execution_context


def _read_from_terminal(prompt: str) -> str:
    print("\n=== HUMAN INPUT REQUIRED ===")
    print("The agent is pausing for a person to provide a value.")
    print("Please type your answer and press Enter.\n")
    value = input(f"{prompt}\n> ")
    return value.strip()


@function_tool
async def ask_human_input_tool(prompt: str) -> str:
    """Ask a human operator for a short text value or approval response.

    Use when:
        - A required value (e.g., "x") is missing or ambiguous and must be
            provided or confirmed by a person.
        - Policy or safety rules require explicit human confirmation before
            proceeding.

    Behavior:
        - When a browser-backed workflow run is active, emits a pending approval
            request and waits for the UI to resolve it.
        - Otherwise falls back to terminal input for local CLI usage.

    Args:
        prompt: The exact question or instruction to show to the human
            (e.g., "Please provide x:"). Keep it concise and specific.

    Returns:
        The human's reply as plain text.
    """
    context = get_workflow_execution_context()
    approval_handler = None if context is None else context.approval_handler
    if approval_handler is not None:
        return await approval_handler.request(prompt)

    try:
        return await asyncio.to_thread(_read_from_terminal, prompt)
    except (EOFError, KeyboardInterrupt) as e:
        raise RuntimeError("Human input was cancelled or unavailable.") from e
