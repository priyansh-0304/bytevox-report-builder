"""The calculation engine. The ONLY place numbers are computed.

Owner preview, shared view, charts and metrics all call compute_report(), so the same number
cannot differ between screens. The frontend never calculates anything.

Every result carries an `explain` object built from the SAME spec that drove the calculation:
  description - plain English
  query       - the equivalent SQL, for reading only. Values are quoted for display; the server
                itself computes in Python and never sends SQL built from user input to a database.
  rows        - how many rows were used / excluded, and why. Always adds up to `total`.
"""
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

MAX_METRIC_GROUPS = 25
MAX_BAR_GROUPS = 25
MAX_LINE_POINTS = 400


@dataclass(frozen=True)
class Agg:
    sql: str
    phrase: str          # used in the plain-English description
    label: str           # used in auto-generated titles
    fn: Callable


# Adding a new aggregation (e.g. median) = one line here + one word in schemas.AggName.
AGGS = {
    "sum": Agg("SUM", "the sum of", "Sum", math.fsum),   # fsum avoids float drift when adding many values
    "avg": Agg("AVG", "the average of", "Average", lambda xs: math.fsum(xs) / len(xs)),
    "count": Agg("COUNT", "the number of", "Count", len),
    "min": Agg("MIN", "the smallest value of", "Minimum", min),
    "max": Agg("MAX", "the largest value of", "Maximum", max),
}


class Table:
    """An in-memory view of one dataset: column info + typed rows [(line_number, [values])]."""

    def __init__(self, columns: list, rows: list):
        self.columns = columns
        self.rows = rows
        self._index = {c["name"]: i for i, c in enumerate(columns)}

    def index(self, name: str) -> int:
        if name not in self._index:
            raise ValueError(f'Column "{name}" does not exist in this dataset.')
        return self._index[name]

    def ctype(self, name: str) -> str:
        return self.columns[self.index(name)]["type"]

    def profile(self, name: str) -> dict:
        return self.columns[self.index(name)]


# ---------------------------------------------------------------- validation

def _require_type(table: Table, name: str, allowed: tuple, what: str):
    t = table.ctype(name)
    if t not in allowed:
        raise ValueError(f'{what} needs a {" or ".join(allowed)} column, but "{name}" is a {t} column.')


def check_filters(table: Table, filters: dict):
    d, c = filters.get("date"), filters.get("category")
    if d:
        _require_type(table, d["column"], ("date",), "The date filter")
    if c:
        _require_type(table, c["column"], ("category",), "The category filter")


def check_block(table: Table, b: dict):
    t = b["type"]
    if t == "note":
        return
    if t in ("metric", "chart"):
        if b["agg"] != "count" and not b.get("column"):
            raise ValueError("Pick a column to calculate.")
        if b.get("column"):
            table.index(b["column"])
            if b["agg"] != "count":
                _require_type(table, b["column"], ("number",), f'"{AGGS[b["agg"]].label}"')
    if t == "metric" and b.get("group_by"):
        _require_type(table, b["group_by"], ("category",), "Splitting a metric")
    if t == "chart":
        want = "date" if b["kind"] == "line" else "category"
        _require_type(table, b["group_by"], (want,), f'A {b["kind"]} chart')
    if t == "table":
        table.index(b["sort_by"])
        for name in b.get("columns") or []:
            table.index(name)


# ---------------------------------------------------------------- filtering

def apply_filters(table: Table, filters: dict) -> list:
    """Rows with a missing value in a filtered column are excluded: we cannot prove they match."""
    tests = []
    d, c = filters.get("date"), filters.get("category")
    if d:
        i, start, end = table.index(d["column"]), d.get("start"), d.get("end")
        tests.append(lambda v, i=i, s=start, e=end: v[i] is not None
                     and (s is None or v[i] >= s) and (e is None or v[i] <= e))  # ISO dates sort as text
    if c:
        i, allowed = table.index(c["column"]), set(c["values"])
        tests.append(lambda v, i=i, a=allowed: v[i] in a)  # None is never in the set
    return [r for r in table.rows if all(t(r[1]) for t in tests)]


def _group_key(value, bucket):
    if value is None:
        return None
    if bucket == "month":
        return value[:7]   # '2024-03-15' -> '2024-03'
    if bucket == "year":
        return value[:4]
    return value


def _aggregate(rows, col_i, grp_i, bucket):
    """Order of exclusion (so counts add up): filter -> missing group -> missing value."""
    groups, no_group, no_value = defaultdict(list), 0, 0
    for _, vals in rows:
        key = None
        if grp_i is not None:
            key = _group_key(vals[grp_i], bucket)
            if key is None:
                no_group += 1
                continue
        v = 1 if col_i is None else vals[col_i]   # COUNT(*) counts every row
        if v is None:
            no_value += 1
            continue
        groups[key].append(v)
    used = sum(len(xs) for xs in groups.values())
    return groups, used, no_group, no_value


def _value(agg_name: str, xs: list):
    if not xs and agg_name != "count":
        return None   # an empty SUM/AVG/MIN/MAX is "no data", not zero
    v = AGGS[agg_name].fn(xs)
    return round(v, 6) if isinstance(v, float) else v


# ---------------------------------------------------------------- explain helpers

def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def describe_filters(filters: dict) -> str:
    parts = []
    d, c = filters.get("date"), filters.get("category")
    if d:
        s, e = d.get("start"), d.get("end")
        rng = f"{s} to {e}" if s and e else f"on or after {s}" if s else f"on or before {e}"
        parts.append(f'"{d["column"]}" is {rng}')
    if c:
        parts.append(f'"{c["column"]}" is one of {", ".join(c["values"])}')
    return " and ".join(parts)


def _where(filters: dict, extra: list) -> str:
    clauses = []
    d, c = filters.get("date"), filters.get("category")
    if d:
        col, s, e = _q(d["column"]), d.get("start"), d.get("end")
        if s and e:
            clauses.append(f"{col} BETWEEN {_lit(s)} AND {_lit(e)}")
        elif s:
            clauses.append(f"{col} >= {_lit(s)}")
        else:
            clauses.append(f"{col} <= {_lit(e)}")
    if c:
        clauses.append(f'{_q(c["column"])} IN ({", ".join(_lit(v) for v in c["values"])})')
    clauses += extra
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _rows_info(table, kept, used, no_group=0, no_value=0):
    total = len(table.rows)
    return {"total": total, "excluded_by_filter": total - len(kept),
            "excluded_no_group": no_group, "excluded_no_value": no_value, "used": used}


def _data_quality_note(table, column):
    p = table.profile(column)
    if p["missing"] or p["invalid"]:
        return (f'Across the whole file, "{column}" has {p["missing"]} blank and {p["invalid"]} '
                f'unreadable values. Both are left out of this calculation (see the dataset profile).')
    return None


def _calc_text(block):
    agg, col = block["agg"], block.get("column")
    if agg == "count" and not col:
        return "Counts every row"
    if agg == "count":
        return f'Counts the rows that have a value in "{col}"'
    return f'Calculates {AGGS[agg].phrase} "{col}"'


def _calc_sql(block):
    agg, col = block["agg"], block.get("column")
    return f"{AGGS[agg].sql}({_q(col) if col else '*'})"


def _auto_title(block):
    agg, col = block["agg"], block.get("column")
    base = "Row count" if agg == "count" and not col else f'{AGGS[agg].label} of {col}'
    return base


# ---------------------------------------------------------------- blocks

def _explain(description, query, rows, notes):
    return {"description": description, "query": query, "rows": rows,
            "notes": [n for n in notes if n],
            "computed_with": "Computed on the server in Python; the query above is the equivalent SQL, shown so you can check it."}


def compute_metric(table, kept, filters, b):
    col, grp = b.get("column"), b.get("group_by")
    groups, used, no_group, no_value = _aggregate(
        kept, table.index(col) if col else None, table.index(grp) if grp else None, None)
    all_values = [x for xs in groups.values() for x in xs]
    groups_out, notes = None, []
    if grp:
        items = [(k, _value(b["agg"], xs), len(xs)) for k, xs in groups.items()]
        items.sort(key=lambda t: (-t[1], str(t[0])))
        if len(items) > MAX_METRIC_GROUPS:
            notes.append(f"Showing the top {MAX_METRIC_GROUPS} of {len(items)} groups.")
        groups_out = [{"key": k, "value": v, "rows": n} for k, v, n in items[:MAX_METRIC_GROUPS]]

    extra = ([f"{_q(grp)} IS NOT NULL"] if grp else []) + ([f"{_q(col)} IS NOT NULL"] if col else [])
    select = (f"{_q(grp)}, " if grp else "") + f"{_calc_sql(b)} AS value"
    query = f"SELECT {select} FROM dataset{_where(filters, extra)}"
    if grp:
        query += f" GROUP BY {_q(grp)} ORDER BY value DESC LIMIT {MAX_METRIC_GROUPS}"
    fdesc = describe_filters(filters)
    description = _calc_text(b) + (f', split by "{grp}"' if grp else "") + "." \
        + (f" Only rows where {fdesc} were considered." if fdesc else "") \
        + (' The big number is across all groups combined.' if grp else "")
    notes.append(_data_quality_note(table, col) if col else None)
    return {
        "value": _value(b["agg"], all_values), "groups": groups_out,
        "explain": _explain(description, query, _rows_info(table, kept, used, no_group, no_value), notes),
        "auto_title": _auto_title(b) + (f" by {grp}" if grp else ""),
    }


def compute_chart(table, kept, filters, b):
    col, grp, bucket = b.get("column"), b["group_by"], b.get("bucket", "month")
    is_line = b["kind"] == "line"
    groups, used, no_group, no_value = _aggregate(
        kept, table.index(col) if col else None, table.index(grp), bucket if is_line else None)
    points = [{"x": k, "y": _value(b["agg"], xs), "rows": len(xs)} for k, xs in groups.items()]
    notes = []
    if is_line:
        points.sort(key=lambda p: p["x"])
        if len(points) > MAX_LINE_POINTS:
            notes.append(f"Showing the first {MAX_LINE_POINTS} of {len(points)} points. Use a coarser date grouping.")
            points = points[:MAX_LINE_POINTS]
    else:
        points.sort(key=lambda p: (-p["y"], str(p["x"])))
        if len(points) > MAX_BAR_GROUPS:
            notes.append(f"Showing the top {MAX_BAR_GROUPS} of {len(points)} groups.")
            points = points[:MAX_BAR_GROUPS]

    extra = [f"{_q(grp)} IS NOT NULL"] + ([f"{_q(col)} IS NOT NULL"] if col else [])
    if is_line:
        width = {"month": 7, "year": 4}.get(bucket)
        x_sql = f"SUBSTR({_q(grp)}, 1, {width})" if width else _q(grp)
        query = (f"SELECT {x_sql} AS x, {_calc_sql(b)} AS y FROM dataset{_where(filters, extra)} "
                 f"GROUP BY x ORDER BY x LIMIT {MAX_LINE_POINTS}")
        by = f'{bucket} of "{grp}"' if bucket != "day" else f'"{grp}"'
    else:
        query = (f"SELECT {_q(grp)} AS x, {_calc_sql(b)} AS y FROM dataset{_where(filters, extra)} "
                 f"GROUP BY x ORDER BY y DESC LIMIT {MAX_BAR_GROUPS}")
        by = f'"{grp}"'
    fdesc = describe_filters(filters)
    description = f"{_calc_text(b)}, grouped by {by}." + (f" Only rows where {fdesc} were considered." if fdesc else "")
    notes.append(_data_quality_note(table, col) if col else None)
    return {
        "kind": b["kind"], "points": points,
        "explain": _explain(description, query, _rows_info(table, kept, used, no_group, no_value), notes),
        "auto_title": f"{_auto_title(b)} by {grp}",
    }


def compute_table(table, kept, filters, b):
    sort_i, desc = table.index(b["sort_by"]), b["order"] == "desc"
    names = b.get("columns") or [c["name"] for c in table.columns]
    idx = [table.index(n) for n in names]
    ranked = [r for r in kept if r[1][sort_i] is not None]
    text_col = table.ctype(b["sort_by"]) in ("text", "category")
    # `ranked` is already in file order and Python's sort is stable (also with reverse=True),
    # so ties always come out in file order. The result is deterministic.
    ranked.sort(key=lambda r: r[1][sort_i].lower() if text_col else r[1][sort_i], reverse=desc)
    limit = b["limit"]
    rows_out = [{"row": line, "cells": [vals[i] for i in idx]} for line, vals in ranked[:limit]]
    no_value = len(kept) - len(ranked)

    notes = []
    if len(ranked) > limit:
        notes.append(f"Showing {limit} of {len(ranked)} rows that could be ranked. Row numbers are line numbers in your original file.")
    if no_value:
        notes.append(f'{no_value} rows have no readable value in "{b["sort_by"]}", so they cannot be ranked and are left out.')
    sort_q = _q(b["sort_by"])
    select_list = ", ".join(_q(n) for n in names)
    where = _where(filters, [f"{sort_q} IS NOT NULL"])
    query = f"SELECT {select_list} FROM dataset{where} ORDER BY {sort_q} {'DESC' if desc else 'ASC'} LIMIT {limit}"
    fdesc = describe_filters(filters)
    description = (f'Ranks rows by "{b["sort_by"]}" ({"highest" if desc else "lowest"} first) and shows the first {limit}.'
                   + (f" Only rows where {fdesc} were considered." if fdesc else ""))
    return {
        "columns": names, "rows": rows_out, "ranked": len(ranked),
        "explain": _explain(description, query, _rows_info(table, kept, len(ranked), 0, no_value), notes),
        "auto_title": f'{"Top" if desc else "Lowest"} {limit} rows by {b["sort_by"]}',
    }


_COMPUTE = {"metric": compute_metric, "chart": compute_chart, "table": compute_table}


def compute_report(table: Table, blocks: list, filters: dict, strict: bool = False) -> dict:
    """strict=True raises ValueError on the first invalid block/filter (used when saving).
    strict=False turns a bad block into an {'error': ...} result so one bad block can't break a page."""
    check_filters(table, filters)
    kept = apply_filters(table, filters)
    results = []
    for b in blocks:
        base = {"id": b["id"], "type": b["type"]}
        try:
            check_block(table, b)
            if b["type"] == "note":
                results.append({**base, "text": b["text"]})
                continue
            out = _COMPUTE[b["type"]](table, kept, filters, b)
            title = b.get("title") or out.pop("auto_title")
            out.pop("auto_title", None)
            results.append({**base, "title": title, **out})
        except ValueError as e:
            if strict:
                raise
            results.append({**base, "error": str(e)})
    return {"summary": {"rows_total": len(table.rows), "rows_after_filter": len(kept),
                        "filters_text": describe_filters(filters)},
            "blocks": results}
