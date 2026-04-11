from typing import Annotated, Literal, cast

from pydantic import BaseModel, Field

from agents import function_tool

Operation = Literal["add", "subtract", "multiply", "divide"]


class CalculationResult(BaseModel):
    """Standardized response for calculator operations."""

    operation: Annotated[Operation, Field(..., description="Arithmetic operation performed (lowercase).")]
    operand1: Annotated[float, Field(..., description="First number used in the calculation.")]
    operand2: Annotated[float, Field(..., description="Second number used in the calculation.")]
    result: Annotated[float, Field(..., description="Computed numeric result of the operation.")]

# TODO: add function tool decorator
async def calculate_tool(
    operation: Annotated[Operation, Field(..., description="Operation to perform: add, subtract, multiply, or divide.")],
    operand1: Annotated[float, Field(..., description="First numeric input for the calculation.")],
    operand2: Annotated[float, Field(..., description="Second numeric input for the calculation.")],
) -> CalculationResult:
    """Perform basic arithmetic for invoice and payment calculations.

    Use this to keep numeric reasoning consistent when summing, subtracting,
    multiplying, or dividing values (e.g., amounts paid, discounts, and short
    pays). Raises ValueError for unsupported operations or division by zero.

    Args:
        operation: The arithmetic operation to apply.
        operand1: First number involved in the calculation.
        operand2: Second number involved in the calculation.

    Returns:
        CalculationResult containing the normalized operation, operands, and result.
    """
    normalized_operation = operation.strip().lower()
    allowed_operations = ("add", "subtract", "multiply", "divide")
    if normalized_operation not in allowed_operations:
        allowed = ", ".join(allowed_operations)
        raise ValueError(f"Unsupported operation '{operation}'. Choose from: {allowed}.")

    operation_to_use = cast(Operation, normalized_operation)

    if operation_to_use == "add":
        result = operand1 + operand2
    elif operation_to_use == "subtract":
        result = operand1 - operand2
    elif operation_to_use == "multiply":
        result = operand1 * operand2
    else:
        if operand2 == 0:
            raise ValueError("Cannot divide by zero.")
        result = operand1 / operand2

    return CalculationResult(
        operation=operation_to_use,
        operand1=operand1,
        operand2=operand2,
        result=result,
    )
