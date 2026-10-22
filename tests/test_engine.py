"""Aggregation logic: right numbers, honest row accounting, one number everywhere."""
import pytest

from app.engine import Table, compute_report
from app.ingest import ingest_csv
from tests.conftest import CSV


@pytest.fixture()
def table():
    profile, rows = ingest_csv(CSV.encode())
    return Table(profile["columns"], rows)


def metric(table, agg, column=None, group_by=None, filters=None):
    block = {"id": "x", "type": "metric", "agg": agg, "column": column, "group_by": group_by}
    out = compute_report(table, [block], filters or {}, strict=True)
    return out["blocks"][0]


# amount column: 100.50, 200.00, 50.25, (blank), (abc), 10.00, 20.00, 1000.00, -30.00, 30.00, 5.00
AMOUNTS = [100.50, 200.00, 50.25, 10.00, 20.00, 1000.00, -30.00, 30.00, 5.00]


def test_sum_avg_min_max_match_hand_calculation(table):
    assert metric(table, "sum", "amount")["value"] == pytest.approx(sum(AMOUNTS))
    assert metric(table, "avg", "amount")["value"] == pytest.approx(sum(AMOUNTS) / len(AMOUNTS))
    assert metric(table, "min", "amount")["value"] == -30.00
    assert metric(table, "max", "amount")["value"] == 1000.00


def test_count_rows_vs_count_column(table):
    assert metric(table, "count")["value"] == 11                 # every row
    assert metric(table, "count", "amount")["value"] == 9        # only rows with a readable amount


def test_blank_and_unreadable_values_are_excluded_and_counted(table):
    rows = metric(table, "sum", "amount")["explain"]["rows"]
    assert rows == {"total": 11, "excluded_by_filter": 0, "excluded_no_group": 0, "excluded_no_value": 2, "used": 9}
    # the explanation names the cause, so "2 missing" is never a mystery
    assert any("1 blank and 1 unreadable" in n for n in metric(table, "sum", "amount")["explain"]["notes"])


def test_row_counts_always_add_up(table):
    filters = {"date": {"column": "order_date", "start": "2024-02-01", "end": "2024-03-16"},
               "category": {"column": "region", "values": ["South", "East", "West"]}}
    for agg in ("sum", "avg", "count", "min", "max"):
        r = metric(table, agg, "amount", group_by="region", filters=filters)["explain"]["rows"]
        assert r["used"] + r["excluded_by_filter"] + r["excluded_no_group"] + r["excluded_no_value"] == r["total"]


def test_group_by_values_and_ordering(table):
    out = metric(table, "sum", "amount", group_by="region")
    groups = {g["key"]: g["value"] for g in out["groups"]}
    assert groups == {"North": pytest.approx(330.5), "South": pytest.approx(55.25),
                      "East": pytest.approx(10.0), "West": pytest.approx(970.0)}
    values = [g["value"] for g in out["groups"]]
    assert values == sorted(values, reverse=True)                 # biggest first
    assert out["explain"]["rows"]["excluded_no_group"] == 1       # row 7 has no region


def test_date_filter_is_inclusive_and_drops_rows_without_a_date(table):
    f = {"date": {"column": "order_date", "start": "2024-01-05", "end": "2024-01-20"}}
    out = metric(table, "count", filters=f)
    assert out["value"] == 2                                      # both boundary days included
    assert out["explain"]["rows"]["excluded_by_filter"] == 9      # includes the blank-date row


def test_category_filter(table):
    f = {"category": {"column": "region", "values": ["West"]}}
    assert metric(table, "sum", "amount", filters=f)["value"] == pytest.approx(970.0)


def test_empty_result_is_none_not_zero_except_count(table):
    f = {"category": {"column": "region", "values": ["North"]}, "date": {"column": "order_date", "start": "2030-01-01"}}
    assert metric(table, "sum", "amount", filters=f)["value"] is None
    assert metric(table, "avg", "amount", filters=f)["value"] is None
    assert metric(table, "count", filters=f)["value"] == 0


def test_metric_and_chart_show_the_same_numbers(table):
    m = metric(table, "sum", "amount", group_by="region")
    chart = compute_report(table, [{"id": "c", "type": "chart", "kind": "bar", "agg": "sum",
                                    "column": "amount", "group_by": "region"}], {})["blocks"][0]
    assert {g["key"]: g["value"] for g in m["groups"]} == {p["x"]: p["y"] for p in chart["points"]}


def test_line_chart_buckets_by_month_in_order(table):
    chart = compute_report(table, [{"id": "c", "type": "chart", "kind": "line", "agg": "sum", "column": "amount",
                                    "group_by": "order_date", "bucket": "month"}], {})["blocks"][0]
    assert [p["x"] for p in chart["points"]] == ["2024-01", "2024-02", "2024-03"]
    assert chart["points"][0]["y"] == pytest.approx(300.5)


def test_table_block_ranks_and_reports_unrankable_rows(table):
    block = {"id": "t", "type": "table", "sort_by": "amount", "order": "desc", "limit": 3}
    out = compute_report(table, [block], {})["blocks"][0]
    assert [r["cells"][table.index("amount")] for r in out["rows"]] == [1000.0, 200.0, 100.5]
    assert out["explain"]["rows"]["excluded_no_value"] == 2
    assert out["rows"][0]["row"] == 9   # line number in the original file (header is line 1)


def test_wrong_column_type_is_rejected_on_save(table):
    with pytest.raises(ValueError, match="number"):
        metric(table, "sum", "region")
    with pytest.raises(ValueError, match="does not exist"):
        metric(table, "sum", "nope")


def test_query_text_escapes_quotes_so_it_cannot_be_misread(table):
    f = {"category": {"column": "region", "values": ["O'Brien"]}}
    q = metric(table, "count", filters=f)["explain"]["query"]
    assert "'O''Brien'" in q


def test_bad_block_does_not_break_the_rest_when_not_strict(table):
    blocks = [{"id": "a", "type": "metric", "agg": "sum", "column": "region", "group_by": None},
              {"id": "b", "type": "note", "text": "hello"}]
    out = compute_report(table, blocks, {})["blocks"]
    assert "error" in out[0] and out[1]["text"] == "hello"
