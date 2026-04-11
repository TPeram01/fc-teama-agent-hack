from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Form1500ClientProfileSchema(BaseModel):
    """Simplified Form 1500 client profile schema."""

    model_config = ConfigDict(extra="forbid")

    first_name: Annotated[
        str,
        Field(min_length=1, description="Client legal first name."),
    ]
    last_name: Annotated[
        str,
        Field(min_length=1, description="Client legal last name."),
    ]
    date_of_birth: Annotated[
        date,
        Field(description="Client date of birth."),
    ]
    marital_status: Annotated[
        str | None,
        Field(default=None, description="Current marital status relevant to planning."),
    ]
    email: Annotated[
        str,
        Field(min_length=1, description="Primary email address."),
    ]
    mobile_phone: Annotated[
        str | None,
        Field(default=None, description="Primary phone number."),
    ]
    city: Annotated[
        str | None,
        Field(default=None, description="Residential city."),
    ]
    state: Annotated[
        str | None,
        Field(default=None, description="Residential state."),
    ]
    service_affiliation: Annotated[
        str | None,
        Field(
            default=None,
            description="Military, veteran, civilian, or surviving spouse affiliation.",
        ),
    ]
    branch_of_service: Annotated[
        str | None,
        Field(
            default=None,
            description="Army, Navy, Air Force, Marine Corps, Space Force, Coast Guard, or other.",
        ),
    ]
    military_status: Annotated[
        str | None,
        Field(
            default=None,
            description="Active duty, reserve, guard, retired, separated, or veteran.",
        ),
    ]
    rank_or_pay_grade: Annotated[
        str | None,
        Field(default=None, description="Current or most recent rank or pay grade."),
    ]
    projected_retirement_date: Annotated[
        date | None,
        Field(default=None, description="Expected retirement or separation date."),
    ]
    spouse_name: Annotated[
        str | None,
        Field(default=None, description="Spouse or partner full name."),
    ]
    dependents_count: Annotated[
        int | None,
        Field(default=None, ge=0, description="Number of dependents relevant to planning."),
    ]
    primary_goal: Annotated[
        str | None,
        Field(default=None, description="Main financial planning objective."),
    ]
    annual_household_income: Annotated[
        float | None,
        Field(default=None, ge=0, description="Estimated total annual household income."),
    ]
    monthly_expenses: Annotated[
        float | None,
        Field(default=None, ge=0, description="Estimated monthly household expenses."),
    ]
    liquid_cash: Annotated[
        float | None,
        Field(
            default=None,
            ge=0,
            description="Cash held in checking, savings, or similar accounts.",
        ),
    ]
    retirement_account_balance: Annotated[
        float | None,
        Field(
            default=None,
            ge=0,
            description="Combined retirement account balances, including TSP, IRA, and employer plans.",
        ),
    ]
    total_debt_balance: Annotated[
        float | None,
        Field(
            default=None,
            ge=0,
            description="Estimated total outstanding debt across mortgages, loans, and cards.",
        ),
    ]
    risk_tolerance: Annotated[
        str | None,
        Field(
            default=None,
            description="Conservative, moderate, aggressive, or similar profile.",
        ),
    ]
    life_insurance_coverage: Annotated[
        float | None,
        Field(default=None, ge=0, description="Total life insurance death benefit coverage."),
    ]
    estate_documents_in_place: Annotated[
        bool | None,
        Field(
            default=None,
            description="Whether core estate documents such as a will or powers of attorney are in place.",
        ),
    ]
    planning_notes: Annotated[
        str | None,
        Field(
            default=None,
            description="Freeform notes for anything material not captured elsewhere.",
        ),
    ]
