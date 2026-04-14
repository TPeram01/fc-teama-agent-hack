from agents import function_tool


# TODO: add function tool decorator
@function_tool()
def ask_human_input_tool(prompt: str) -> str:
    """Ask a human operator for a short text value via the terminal.

    Use when:
        - A required value (e.g., "x") is missing or ambiguous and must be
            provided or confirmed by a person.
        - Policy or safety rules require explicit human confirmation before
            proceeding.

    Behavior:
        - Prints brief instructions for the human operator before asking.
        - Returns exactly what the human types (stripped of leading/trailing
            whitespace).

    Args:
        prompt: The exact question or instruction to show to the human
            (e.g., "Please provide x:"). Keep it concise and specific.

    Returns:
        The human's reply as plain text.
    """
    try:
        print("\n=== HUMAN INPUT REQUIRED ===")
        print("The agent is pausing for a person to provide a value.")
        print("Please type your answer and press Enter.\n")
        value = input(f"{prompt}\n> ")
        return value.strip()
    except (EOFError, KeyboardInterrupt) as e:
        raise RuntimeError("Human input was cancelled or unavailable.") from e
