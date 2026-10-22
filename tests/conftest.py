import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

CSV = (
    "order_id,order_date,region,units,amount,note\n"
    "1,2024-01-05,North,2,100.50,a\n"
    "2,2024-01-20,North,3,200.00,b\n"
    "3,2024-02-10,South,1,50.25,c\n"
    "4,2024-02-11,South,4,,d\n"          # blank amount
    "5,2024-03-01,East,5,abc,e\n"        # unreadable amount
    "6,,East,6,10.00,f\n"                # blank date
    "7,2024-03-15,,7,20.00,g\n"          # blank region
    "8,2024-03-16,West,2,1000.00,h\n"
    "9,2024-03-17,West,1,-30.00,i\n"
    "10,2024-03-18,North,2,30.00,j\n"
    "11,2024-03-19,South,3,5.00,k\n"
)


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "test.db"), max_upload_bytes=50_000, max_rows=1000)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def alice(app):
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": "alice@example.com", "password": "password123"}).status_code == 201
    return c


@pytest.fixture()
def bob(app):
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": "bob@example.com", "password": "password123"}).status_code == 201
    return c


@pytest.fixture()
def anon(app):
    return TestClient(app)


def upload(client, data=CSV, filename="sales.csv"):
    raw = data.encode() if isinstance(data, str) else data
    return client.post("/api/datasets", files={"file": (filename, raw, "text/csv")})


@pytest.fixture()
def alice_dataset(alice):
    r = upload(alice)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def alice_report(alice, alice_dataset):
    """A saved report with one metric, owned by alice."""
    r = alice.post("/api/reports", json={"dataset_id": alice_dataset, "title": "Sales"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    body = {"title": "Sales", "filters": {}, "blocks": [
        {"type": "metric", "id": "m1", "agg": "sum", "column": "amount"}]}
    assert alice.put(f"/api/reports/{rid}", json=body).status_code == 200
    return rid


def db_exec(settings, sql, params=()):
    """Direct DB access for tests that need to rewind time (expire a link)."""
    conn = sqlite3.connect(settings.db_path)
    conn.execute(sql, params)
    conn.commit()
    conn.close()
