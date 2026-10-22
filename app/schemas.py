"""Request validation. Shapes are checked here (pydantic); meaning (does this column exist, is it
numeric?) is checked in engine.check_block, because that needs the dataset."""
import re
import uuid
from datetime import date
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")   # unknown fields are an error, not silently ignored


class Credentials(Strict):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


AggName = Literal["sum", "avg", "count", "min", "max"]
Title = Optional[str]


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class MetricBlock(Strict):
    type: Literal["metric"]
    id: str = Field(default_factory=_new_id, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    title: Optional[str] = Field(default=None, max_length=100)
    agg: AggName
    column: Optional[str] = Field(default=None, max_length=100)
    group_by: Optional[str] = Field(default=None, max_length=100)


class ChartBlock(Strict):
    type: Literal["chart"]
    id: str = Field(default_factory=_new_id, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    title: Optional[str] = Field(default=None, max_length=100)
    kind: Literal["bar", "line"]
    agg: AggName
    column: Optional[str] = Field(default=None, max_length=100)
    group_by: str = Field(max_length=100)
    bucket: Literal["day", "month", "year"] = "month"


class TableBlock(Strict):
    type: Literal["table"]
    id: str = Field(default_factory=_new_id, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    title: Optional[str] = Field(default=None, max_length=100)
    sort_by: str = Field(max_length=100)
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=10, ge=1, le=50)
    columns: Optional[list[str]] = Field(default=None, max_length=100)


class NoteBlock(Strict):
    type: Literal["note"]
    id: str = Field(default_factory=_new_id, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    text: str = Field(max_length=2000)


Block = Annotated[Union[MetricBlock, ChartBlock, TableBlock, NoteBlock], Field(discriminator="type")]


class DateFilter(Strict):
    column: str = Field(max_length=100)
    start: Optional[date] = None
    end: Optional[date] = None

    @model_validator(mode="after")
    def _range(self):
        if self.start is None and self.end is None:
            raise ValueError("Give a start date, an end date, or both.")
        if self.start and self.end and self.start > self.end:
            raise ValueError("The start date must not be after the end date.")
        return self


class CategoryFilter(Strict):
    column: str = Field(max_length=100)
    values: list[str] = Field(min_length=1, max_length=50)


class Filters(Strict):
    date: Optional[DateFilter] = None
    category: Optional[CategoryFilter] = None


class ReportCreate(Strict):
    dataset_id: int
    title: str = Field(default="Untitled report", min_length=1, max_length=100)
    use_suggestions: bool = False


class ReportUpdate(Strict):
    title: str = Field(min_length=1, max_length=100)
    blocks: list[Block] = Field(max_length=30)
    filters: Filters = Field(default_factory=Filters)


class ShareCreate(Strict):
    expires_in_hours: int = Field(ge=1, le=24 * 90)   # an expiry is required; the maximum is 90 days
