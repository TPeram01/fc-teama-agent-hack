from pathlib import Path
from typing import Annotated, Literal

from agents import function_tool
from pydantic import Field

ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATHS = {
    "employee_acknowledgement": (
        ROOT_DIR / "data" / "Example Acknowledgment Email_EEs.md"
    ),
    "manager_acknowledgement": (
        ROOT_DIR / "data" / "Example Acknowledgment Email_Manager.md"
    ),
}


# TODO: add function tool decorator
def email_template_loader_tool(
    template_name: Annotated[
        Literal["employee_acknowledgement", "manager_acknowledgement"],
        Field(description="Supported acknowledgement template identifier."),
    ],
) -> str:
    """Load a supported email template as markdown text.

    Args:
        template_name: Literal identifier for the template to load.

    Returns:
        Markdown content for the requested template.
    """
    return TEMPLATE_PATHS[template_name].read_text(encoding="utf-8").strip()
