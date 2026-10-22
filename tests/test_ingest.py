"""Messy-file handling: types are guessed sensibly and nothing disappears silently."""
import pytest

from app.ingest import IngestError, ingest_csv, parse_date, parse_number
from tests.conftest import CSV, upload


def cols(profile):
    return {c["name"]: c for c in profile["columns"]}


def test_types_are_guessed():
    profile, rows = ingest_csv(CSV.encode())
    c = cols(profile)
    assert c["order_id"]["type"] == "number"
    assert c["order_date"]["type"] == "date"
    assert c["region"]["type"] == "category"
    assert c["amount"]["type"] == "number"
    assert c["note"]["type"] == "text"          # 11 different values: too many to be a category
    assert profile["row_count"] == 11 and profile["rejected_count"] == 0


def test_missing_and_invalid_are_counted_separately_with_line_numbers():
    profile, _ = ingest_csv(CSV.encode())
    amount = cols(profile)["amount"]
    assert amount["missing"] == 1 and amount["invalid"] == 1          # blank vs "abc"
    assert amount["invalid_samples"] == [{"line": 6, "value": "abc", "reason": "not a valid number"}]
    assert cols(profile)["order_date"]["missing"] == 1


def test_bad_rows_are_rejected_with_reason_not_dropped():
    data = "a,b,c\n1,2,3\n4,5\n\n6,7,8,9\n10,11,12\n"
    profile, rows = ingest_csv(data.encode())
    assert [r[0] for r in rows] == [2, 6]
    reasons = {r["line"]: r["reason"] for r in profile["rejected"]}
    assert reasons[3] == "Expected 3 fields but found 2"
    assert reasons[4] == "Blank row (no values)"
    assert reasons[5] == "Expected 3 fields but found 4"
    assert profile["rows_read"] == profile["row_count"] + profile["rejected_count"]


def test_unclosed_quote_reports_the_swallowed_lines():
    data = 'a,b\n1,2\n"oops,3\n4,5\n6,"x"\n7,8\n'
    profile, _ = ingest_csv(data.encode())
    bad = [r for r in profile["rejected"] if r["reason"].startswith("Malformed")]
    assert bad and "Lines 3-" in bad[0]["reason"]


def test_ambiguous_dates_are_flagged_not_guessed_silently():
    profile, _ = ingest_csv(b"d\n03/04/2024\n05/06/2024\n07/08/2024\n")
    assert any("DD/MM or MM/DD" in w for w in profile["warnings"])


def test_day_first_is_detected_from_evidence():
    assert parse_date("25/03/2024", dayfirst=True).isoformat() == "2024-03-25"
    profile, rows = ingest_csv(b"d\n25/03/2024\n01/02/2024\n")      # 25 can only be a day
    assert [r[1][0] for r in rows] == ["2024-03-25", "2024-02-01"] and not profile["warnings"]


@pytest.mark.parametrize("text,expected", [
    ("1234.5", 1234.5), ("1,234.50", 1234.5), ("12,34,567", 1234567.0), ("$99", 99.0), ("₹1,200", 1200.0),
    ("-5", -5.0), ("1e3", 1000.0), ("abc", None), ("12abc", None), ("inf", None), ("1,2", None), ("", None),
])
def test_number_parsing(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["31/02/2024", "2024-13-45", "tomorrow", "0001-01-01", ""])
def test_invalid_dates(text):
    assert parse_date(text) is None


def test_semicolon_delimiter_and_duplicate_headers():
    profile, rows = ingest_csv(b"a;a;\n1;2;3\n")
    assert [c["name"] for c in profile["columns"]] == ["a", "a_2", "column_3"]
    assert len(profile["warnings"]) == 2 and rows[0][1] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("raw,status,fragment", [
    (b"", 422, "empty"),
    (b"a,b\n", 422, "No readable data rows"),
    (b"\xff\xfea\x00,\x00b\x00", 422, "UTF-16"),
    (b"PK\x03\x04\x00\x00binary", 415, "binary"),
    ("a,b\n1,caf\xe9\n".encode("latin-1"), 422, "not valid UTF-8"),
])
def test_bad_files_raise_clear_errors(raw, status, fragment):
    with pytest.raises(IngestError) as e:
        ingest_csv(raw)
    assert e.value.status == status and fragment in e.value.message


def test_row_limit():
    with pytest.raises(IngestError) as e:
        ingest_csv(b"a\n" + b"1\n" * 11, max_rows=10)
    assert e.value.status == 413


# ---- through the HTTP API: what the user actually sees for each bad file

def test_api_bad_file_cases(alice):
    r = upload(alice, "a,b\n1,2\n", filename="notes.txt")
    assert r.status_code == 415 and "csv" in r.json()["detail"].lower()

    r = upload(alice, "a,b\n1,caf\xe9\n".encode("latin-1"))
    assert r.status_code == 422 and "UTF-8" in r.json()["detail"]

    r = upload(alice, b"x" * 60_000)                      # limit in tests is 50,000 bytes
    assert r.status_code == 413 and "too large" in r.json()["detail"]

    r = upload(alice, b"")
    assert r.status_code == 422


def test_api_upload_profile_roundtrip(alice):
    r = upload(alice)
    assert r.status_code == 201
    d = alice.get(f"/api/datasets/{r.json()['id']}").json()
    assert d["profile"]["row_count"] == 11 and len(d["preview"]["rows"]) == 10   # preview shows 10
