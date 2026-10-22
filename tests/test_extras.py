"""Suggested charts, deleting a dataset, and the share-link rate limit."""
import pathlib

import pytest

from app.engine import Table, compute_report
from app.ingest import ingest_csv
from app.suggest import suggest
from tests.conftest import upload

SAMPLE = pathlib.Path(__file__).parent.parent / "sample_data" / "messy_sales.csv"


# ---------------------------------------------------------------- suggestions

def test_suggestions_for_the_sample_file_are_sensible_and_valid():
    profile, rows = ingest_csv(SAMPLE.read_bytes())
    s = suggest(profile["columns"], profile["row_count"])
    titles = [x["title"] for x in s]
    assert "Total amount" in titles                        # "amount" outranks unit_price as the measure
    assert not any("order_id" in t for t in titles)        # id-like columns are never measures
    assert any(x["block"]["type"] == "chart" and x["block"]["kind"] == "line" for x in s)
    assert len(s) <= 7
    # every suggestion must pass the same strict check the editor uses
    out = compute_report(Table(profile["columns"], rows), [x["block"] for x in s], {}, strict=True)
    assert all("error" not in b for b in out["blocks"])


def test_suggestions_are_deterministic_apart_from_block_ids():
    profile, _ = ingest_csv(SAMPLE.read_bytes())
    strip = lambda s: [{**x, "block": {k: v for k, v in x["block"].items() if k != "id"}} for x in s]
    assert strip(suggest(profile["columns"], profile["row_count"])) == strip(suggest(profile["columns"], profile["row_count"]))


def test_file_without_numbers_falls_back_to_counting_rows():
    profile, _ = ingest_csv(b"region,day\nN,2024-01-01\nS,2024-01-02\nN,2024-01-03\nS,2024-01-04\nN,2024-01-05\nS,2024-01-06\n")
    s = suggest(profile["columns"], profile["row_count"])
    assert [x["title"] for x in s][0] == "Number of rows"
    assert all(x["block"]["agg"] == "count" for x in s if x["block"]["type"] != "table")


def test_dataset_api_returns_suggestions_and_report_can_start_from_them(alice, alice_dataset):
    d = alice.get(f"/api/datasets/{alice_dataset}").json()
    assert d["suggestions"] and d["report_count"] == 0
    r = alice.post("/api/reports", json={"dataset_id": alice_dataset, "title": "Auto", "use_suggestions": True})
    assert r.status_code == 201
    body = r.json()
    assert len(body["blocks"]) == len(d["suggestions"])
    assert all("error" not in x for x in body["results"])
    assert alice.get(f"/api/datasets/{alice_dataset}").json()["report_count"] == 1


# ---------------------------------------------------------------- delete dataset

def test_other_user_cannot_delete_my_dataset(alice, bob, alice_dataset):
    assert bob.delete(f"/api/datasets/{alice_dataset}").status_code == 404
    assert alice.get(f"/api/datasets/{alice_dataset}").status_code == 200   # still there


def test_deleting_a_dataset_removes_reports_and_kills_share_links(alice, anon, alice_dataset, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    path = "/api/shared/" + share["path"].removeprefix("/s/")
    assert anon.get(path).status_code == 200
    assert alice.delete(f"/api/datasets/{alice_dataset}").status_code == 204
    assert alice.get(f"/api/datasets/{alice_dataset}").status_code == 404
    assert alice.get(f"/api/reports/{alice_report}").status_code == 404
    assert anon.get(path).status_code == 404
    assert alice.delete(f"/api/datasets/{alice_dataset}").status_code == 404   # second delete: nothing left


def test_delete_requires_sign_in(anon):
    assert anon.delete("/api/datasets/1").status_code == 401


# ---------------------------------------------------------------- rate limit

def test_repeated_bad_links_get_rate_limited(anon):
    codes = [anon.get(f"/api/shared/guess-{i}").status_code for i in range(25)]
    assert codes[:20] == [404] * 20           # first 20 failures are ordinary 404s
    assert set(codes[20:]) == {429}           # then the address is blocked for a while


def test_rate_limit_message_is_clear(anon):
    for i in range(21):
        anon.get(f"/api/shared/guess-{i}")
    r = anon.get("/api/shared/another")
    assert r.status_code == 429 and "Too many requests" in r.json()["detail"]


def test_normal_viewing_is_not_limited(alice, anon, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    path = "/api/shared/" + share["path"].removeprefix("/s/")
    assert all(anon.get(path).status_code == 200 for _ in range(30))