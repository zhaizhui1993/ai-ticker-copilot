"""User-reviewed valuation evidence; prices and gates are calculated by code."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ValuationEvidence(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", str_strip_whitespace=True)

    method: Literal["dcf", "multiples", "scenario", "sotp"]
    conservative_value: float = Field(gt=0)
    currency: Literal["USD"] = "USD"
    as_of: date
    valid_until: date
    minimum_margin: float = Field(ge=0, lt=1)
    assumptions: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    reviewed: bool = False

    @field_validator("assumptions", "sources")
    @classmethod
    def nonempty_entries(cls, values):
        if any(not v.strip() for v in values):
            raise ValueError("估值假设和来源不得为空")
        return [v.strip() for v in values]

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_until < self.as_of:
            raise ValueError("估值有效期不能早于研究日期")
        return self


class ValuationAssessment(BaseModel):
    status: Literal["missing", "unreviewed", "future", "expired", "invalid_price",
                    "insufficient_margin", "passed"]
    allows_add: bool = False
    reason: str
    price: float | None = None
    price_date: date | None = None
    margin: float | None = None
    evidence: ValuationEvidence | None = None
