# EXAMPLES

Quick reference examples for key implementation concepts.

## Pydantic Structured Outputs

```python

from typing import Annotated
from pydantic import BaseModel, Field

class Customer(BaseModel):
    """Data model that represents customer."""
    employee_number: Annotated[str, Field(
        description="Unique employee/customer number assigned internally."
        examples=["EMP-00123", "CUST-456"],
    )]

    full_name: Annotated[str, Field(
        description="Full legal name of the customer.",
        min_length=1,
        examples=["Alice Johnson"]
    )]

    email: Annotated[str, Field(
        description="Primary contact email address.",
        examples=["alice.johnson@example.com"]
    )]

    phone: Annotated[str, Field(
        description="Customer contact phone number.",
        examples=["+1-555-123-4567"],
        default="Not provided"
    )]

```

## Agents

### Agents with Tools and Guardrails

```python
from agents import Agent, Runner

# For Pydantic Object
from typing import Annotated
from pydantic import BaseModel, Field

# User-defined functions
from tools import example_tool
from agent_guardrails import example_input_guardrail, example_output_guardrail

class SpecialistOutput(BaseModel):
    """Example specialist output."""
    ... # Fill out pydantic fields

specialist_agent = Agent(
    name="Specialist",
    instructions=(
        "Instructions for the agent."
        "Fill out customer data.
    ),
    model="gpt-5",
    output_type=SpecialistOutput, # Pydantic Structured Output Object
    tools=[
        example_tool # pass in any tool functions
    ],
    input_guardrails=[ # List any input agent-level guardrail functions
        example_input_guardrail,
    ], 
    output_guardrails=[ # List any output agent-level guardrail functions
        example_output_guardrail,
    ] 
)
```

### Calling Agents as Tools

```python
manager = Agent(
    name="Helper",
    instructions=(
        "You are a concise, factual manager. "
        "If you aren't sure, say you are uncertain. "
        "Prefer 2–4 short sentences."
    ),
    model="gpt-5", # Model selection
    tools=[
        specialist_agent.as_tool(
            tool_name="specialist_agent",
            tool_description="Specialist agent tool-prompt for the helper to understand specialist usage.",
            hooks=hooks, # Optionally, pass in any hooks.
        )
    ],
    output_type=LeadReviewerOutput,
    input_guardrails=[],
    output_guardrails=[]
)
```
### Running Agents (with Tracing)

```python

from agents import Agent, Runner, trace, gen_trace_id

async def main():
    agent = Agent(
        name="Joke generator",
        instructions="Tell funny jokes.",
        model="gpt-5-mini",
    )
    trace_id = gen_trace_id()

    with trace("Joke Worfklow", trace_id=trace_id):
      print(f"🔍 View Trace: [OpenAI Platform](https://platform.openai.com/traces/trace?trace_id={trace_id})\n")
      first_result = await Runner.run(agent, "Tell a joke")
      second_result = await Runner.run(agent, f"Rate this joke: {first_result.final_output}")
      print(f"Joke: {first_result.final_output}")
      print(f"Rating: {second_result.final_output}")

await main()

```

## Tools

### Tool Definition

```python

@function_tool(
    tool_input_guardrails=[email_moderation_guardrail], # Optional input tool-level guardrails 
    tool_output_guardrails=[email_output_guardrail], # Optional output tool-level guardrails
)
def send_email_tool(to: list[str], from: str, subject: str, text: str) -> None:
    """Send an outbound email."""
    # Function implementation

```

## Guardrails

### Agent-Level Guardrails

```python

from agents import (
    Agent, Runner, RunContextWrapper, GuardrailFunctionOutput,
    input_guardrail, output_guardrail,
    InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered,
)
from pydantic import BaseModel
from openai import OpenAI

client = OpenAI() # Initialize Openai

class Msg(BaseModel): # Pydantic Class
    response: str

@input_guardrail
async def moderate_input(ctx: RunContextWrapper[None], agent: Agent, input: str | list) -> GuardrailFunctionOutput:
    r = client.moderations.create(model="omni-moderation-latest", input=input if isinstance(input, str) else str(input))

    # GuardrailFunctionOutput will "trip" if our OpenAI moderations model returns a result (r) with a raised flag
    return GuardrailFunctionOutput(output_info={"flagged": r.results[0].flagged}, 
                                   tripwire_triggered=r.results[0].flagged) # Engages guardrail if tripwire_triggered == True

@output_guardrail
async def moderate_output(ctx: RunContextWrapper, agent: Agent, output: Msg) -> GuardrailFunctionOutput:
    r = client.moderations.create(model="omni-moderation-latest", input=output.response)

    return GuardrailFunctionOutput(output_info={"flagged": r.results[0].flagged},
                                   tripwire_triggered=r.results[0].flagged)

```

### Tool-Level Guardrails

```python

# Import for moderation model
from openai import OpenAI

# Guardrail imports
from agents import ToolGuardrailFunctionOutput, tool_input_guardrail, tool_output_guardrail
from agents.tracing import guardrail_span

client = OpenAI()

@tool_input_guardrail
async def inbound_email_moderation_guardrail(data: Any) -> ToolGuardrailFunctionOutput:
    """Moderation guardrail for inbound email drafts."""

    # Guardrail logic. In this example use OpenAI moderation model
    mod = client.moderations.create(
        model="omni-moderation-latest",
        input=str(data),
    )
    result = mod.results[0]
    tripped = bool(result.flagged)

    # Engage tool-level guardrail where triggered == True
    with guardrail_span("inbound_email_moderation_guardrail", triggered=tripped):

        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Email blocked by moderation.
            ),
            output_info=(
                "moderation_flagged": tripped,
                "categories": vars(results.categories)
            )
        )

@tool_output_guardrail
async def outbound_email_moderation_guardrail(data: Any) -> ToolGuardrailFunctionOutput:
    """Moderation guardrail for outbound email drafts."""

    # Guardrail logic. In this example use OpenAI moderation model
    mod = client.moderations.create(
        model="omni-moderation-latest",
        input=str(data),
    )
    result = mod.results[0]
    tripped = bool(result.flagged)

    # Engage tool-level guardrail where triggered == True
    with guardrail_span("outbound_email_moderation_guardrail", triggered=tripped):

        if not tripped:
            return ToolGuardrailFunctionOutput.allow()

        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                "Email blocked by moderation.
            ),
            output_info=(
                "moderation_flagged": tripped,
                "categories": vars(results.categories)
            )
        )

```

