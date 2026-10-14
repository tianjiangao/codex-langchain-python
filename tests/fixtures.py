"""Generic OFFLINE schemas and tools: not copies of financial business classes."""

import json
from enum import StrEnum
from typing import Annotated, Literal

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field, field_validator


class Choice(StrEnum):
    """Generic five-option offline choice enumeration."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class PlanSpec(BaseModel):
    recommendation: Choice = Field(description="Select an option from the fixture choice list.")
    rationale: str
    strategic_actions: str


def normalize_fixture_number(value):
    if not isinstance(value, str):
        return value
    if value.strip().endswith("%"):
        return None
    try:
        return float(value.replace(",", "").strip().lstrip("$€£¥"))
    except ValueError:
        return None


class NumericSpec(BaseModel):
    action: Literal["A", "C", "E"]
    reasoning: str
    amount: float | None = None
    threshold: float | None = None
    note: str | None = None

    @field_validator("amount", "threshold", mode="before")
    @classmethod
    def numbers(cls, value):
        return normalize_fixture_number(value)


class DecisionSpec(BaseModel):
    rating: Choice = Field(description="Choose an option for an offline generic workflow.")
    executive_summary: str
    investment_thesis: str
    target: float | None = None
    horizon: str | None = None

    @field_validator("target", mode="before")
    @classmethod
    def numbers(cls, value):
        return normalize_fixture_number(value)


class ScoreSpec(BaseModel):
    overall_band: Literal["Negative", "Neutral", "Positive"]
    overall_score: float = Field(ge=0, le=10)
    confidence: Literal["low", "medium", "high"]
    narrative: str


def render_value(value):
    return json.dumps(value.model_dump(mode="json"), sort_keys=True)


@tool
def fetch_data(start_date: str, end_date: str, state: Annotated[dict, InjectedState]) -> str:
    """Return an OFFLINE fixture; the injected state is invisible to the model."""
    return "OFFLINE_ONLY"


@tool
def compute_statistic(indicator: str, curr_date: str) -> str:
    """Return an OFFLINE statistic fixture."""
    return "OFFLINE_ONLY"


@tool
def verify_result(curr_date: str) -> str:
    """Return an OFFLINE verification fixture."""
    return "OFFLINE_ONLY"


TOOLS = (fetch_data, compute_statistic, verify_result)
