"""Suggested blocks for a freshly uploaded file.

Plain heuristics over the column profile: no AI, no randomness, so the same file always gets the same
suggestions and you can explain exactly why each one appears. Every suggestion is an ordinary block spec,
so it goes through the same validation and the same engine as anything the user adds by hand.
"""
import re
import uuid
from datetime import date

# Earlier in this list = more likely to be "the" number people care about.
MEASURE_HINTS = ("amount", "revenue", "sales", "total", "profit", "cost", "spend", "income", "price", "value")
ID_LIKE = re.compile(r"(^|_)(id|uuid|index|idx|no|num|number)$", re.IGNORECASE)
MAX_SUGGESTIONS = 7


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _pick_measure(columns):
    """The number column most likely to be the thing to add up: a hinted name first, then the one with
    the fewest unusable values. Id-like columns (order_id, row_no...) are never measures."""
    nums = [c for c in columns if c["type"] == "number" and not ID_LIKE.search(c["name"])]
    if not nums:
        return None

    def rank(c):
        name = c["name"].lower()
        hint = next((i for i, h in enumerate(MEASURE_HINTS) if h in name), len(MEASURE_HINTS))
        return (hint, c["missing"] + c["invalid"])

    return min(nums, key=rank)["name"]


def _good_categories(columns, row_count):
    """Categories small enough to chart (2-12 groups) and mostly filled in, best first."""
    cats = [c for c in columns
            if c["type"] == "category" and 2 <= c["distinct"] <= 12 and c["missing"] <= row_count * 0.5]
    return sorted(cats, key=lambda c: (c["missing"], c["distinct"]))


def _date_bucket(col):
    """Group by day for short files (about two months or less), otherwise by month."""
    try:
        span = (date.fromisoformat(col["max"]) - date.fromisoformat(col["min"])).days
    except (KeyError, ValueError):
        return "month"
    return "day" if span <= 62 else "month"


def suggest(columns: list, row_count: int) -> list:
    """Returns [{title, why, block}]. `block` is a ready-to-save block spec."""
    out = []

    def add(title, why, block):
        out.append({"title": title, "why": why, "block": {"id": _id(), "title": None, **block}})

    measure = _pick_measure(columns)
    cats = _good_categories(columns, row_count)
    dates = [c for c in columns if c["type"] == "date" and c.get("min")]
    agg, col = ("sum", measure) if measure else ("count", None)
    what = f'"{measure}"' if measure else "rows"

    if measure:
        add(f"Total {measure}", f'"{measure}" looks like the main number in your file.',
            {"type": "metric", "agg": "sum", "column": measure, "group_by": None})
        add(f"Average {measure}", "The typical value, next to the total.",
            {"type": "metric", "agg": "avg", "column": measure, "group_by": None})
    add("Number of rows", "How many records the report is based on.",
        {"type": "metric", "agg": "count", "column": None, "group_by": None})

    for c in cats[:2]:
        add(f"{'Total ' + measure if measure else 'Rows'} by {c['name']}",
            f'"{c["name"]}" has {c["distinct"]} groups, a good size for a bar chart.',
            {"type": "chart", "kind": "bar", "agg": agg, "column": col, "group_by": c["name"], "bucket": "month"})

    if dates:
        d = dates[0]
        bucket = _date_bucket(d)
        add(f"{'Total ' + measure if measure else 'Rows'} over time",
            f'"{d["name"]}" is a date, so you can see how {what} changes over time.',
            {"type": "chart", "kind": "line", "agg": agg, "column": col, "group_by": d["name"], "bucket": bucket})

    if measure:
        add(f"Top 10 rows by {measure}", "The biggest individual records, with their line numbers in your file.",
            {"type": "table", "sort_by": measure, "order": "desc", "limit": 10, "columns": None})

    return out[:MAX_SUGGESTIONS]