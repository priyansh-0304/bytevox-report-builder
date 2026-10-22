"""Turns a stored report into the JSON the screens need. Used by BOTH the owner view and the
shared view, so they run the same engine code path."""
import json

from . import engine, repo


def _column_info(c: dict) -> dict:
    info = {"name": c["name"], "type": c["type"]}
    for key in ("categories", "min", "max"):
        if key in c:
            info[key] = c[key]
    return info


def owner_view(conn, report) -> dict:
    # The owner's id comes from the report row, and load_table re-checks that the dataset is theirs.
    table = repo.load_table(conn, report["user_id"], report["dataset_id"])
    dataset = repo.get_dataset(conn, report["user_id"], report["dataset_id"])
    blocks = json.loads(report["blocks_json"])
    filters = json.loads(report["filters_json"])
    computed = engine.compute_report(table, blocks, filters)
    return {
        "id": report["id"], "title": report["title"], "updated_at": report["updated_at"],
        "dataset": {"id": dataset["id"], "name": dataset["name"],
                    "columns": [_column_info(c) for c in table.columns]},
        "filters": filters, "blocks": blocks,
        "summary": computed["summary"], "results": computed["blocks"],
    }


def shared_view(conn, report) -> dict:
    """What an anonymous viewer gets: the computed results only. No dataset id, no column
    profile, no owner, no raw rows beyond what the owner's table blocks display."""
    table = repo.load_table(conn, report["user_id"], report["dataset_id"])
    computed = engine.compute_report(table, json.loads(report["blocks_json"]), json.loads(report["filters_json"]))
    return {"title": report["title"], "expires_at": report["link_expires_at"],
            "summary": computed["summary"], "results": computed["blocks"]}
