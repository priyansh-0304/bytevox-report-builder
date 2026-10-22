"""Ownership and sharing, enforced on the server. These tests act like an attacker: they call the
API directly and never go through the screens."""
from tests.conftest import db_exec, upload


# ---------------------------------------------------------------- signed-out

def test_everything_needs_sign_in(anon):
    for method, path in [("get", "/api/datasets"), ("get", "/api/datasets/1"), ("get", "/api/reports"),
                         ("get", "/api/reports/1"), ("delete", "/api/reports/1"), ("get", "/api/reports/1/shares")]:
        assert getattr(anon, method)(path).status_code == 401, path
    assert anon.post("/api/datasets", files={"file": ("a.csv", b"a\n1\n", "text/csv")}).status_code == 401


def test_login_and_logout(app, alice):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"}).status_code == 200
    assert c.get("/api/auth/me").json()["email"] == "alice@example.com"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_register_validation(anon):
    assert anon.post("/api/auth/register", json={"email": "nope", "password": "password123"}).status_code == 422
    assert anon.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422


# ---------------------------------------------------------------- another user's data

def test_other_user_cannot_read_or_change_my_dataset_or_report(alice, bob, alice_dataset, alice_report):
    assert bob.get(f"/api/datasets/{alice_dataset}").status_code == 404
    assert bob.get(f"/api/reports/{alice_report}").status_code == 404
    body = {"title": "hacked", "filters": {}, "blocks": []}
    assert bob.put(f"/api/reports/{alice_report}", json=body).status_code == 404
    assert bob.delete(f"/api/reports/{alice_report}").status_code == 404
    # ...and nothing changed
    assert alice.get(f"/api/reports/{alice_report}").json()["title"] == "Sales"


def test_other_user_cannot_build_on_my_dataset(bob, alice_dataset):
    r = bob.post("/api/reports", json={"dataset_id": alice_dataset, "title": "steal"})
    assert r.status_code == 404


def test_other_user_cannot_see_or_manage_my_share_links(alice, bob, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    assert bob.get(f"/api/reports/{alice_report}/shares").status_code == 404
    assert bob.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).status_code == 404
    assert bob.delete(f"/api/reports/{alice_report}/shares/{share['id']}").status_code == 404
    anon_view = bob.get("/api" + share["path"].replace("/s/", "/shared/"))
    assert anon_view.status_code == 200   # a link works for anyone who HAS it, that is the point of sharing


def test_lists_only_contain_my_own_items(alice, bob, alice_dataset, alice_report):
    assert bob.get("/api/datasets").json() == []
    assert bob.get("/api/reports").json() == []
    assert len(alice.get("/api/datasets").json()) == 1


def test_report_cannot_be_saved_with_invalid_columns(alice, alice_report):
    bad = {"title": "x", "filters": {}, "blocks": [{"type": "metric", "agg": "sum", "column": "region"}]}
    r = alice.put(f"/api/reports/{alice_report}", json=bad)
    assert r.status_code == 422 and "number" in r.json()["detail"]
    r = alice.put(f"/api/reports/{alice_report}", json={"title": "x", "blocks": [{"type": "evil"}], "filters": {}})
    assert r.status_code == 422


# ---------------------------------------------------------------- share links

def shared_path(path):
    return "/api/shared/" + path.removeprefix("/s/")


def test_share_link_works_without_sign_in_and_leaks_nothing(alice, anon, alice_report, alice_dataset):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 24}).json()
    r = anon.get(shared_path(share["path"]))
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Sales" and body["results"][0]["value"] == 1385.75
    text = r.text
    assert "alice@example.com" not in text
    assert "dataset" not in body and "invalid_samples" not in text   # no dataset id, no column profile
    assert r.headers["cache-control"] == "no-store"
    # An anonymous visitor still cannot reach the owner API
    assert anon.get(f"/api/reports/{alice_report}").status_code == 401
    assert anon.get(f"/api/datasets/{alice_dataset}").status_code == 401


def test_revoked_link_stops_working_immediately(alice, anon, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 24}).json()
    assert anon.get(shared_path(share["path"])).status_code == 200
    assert alice.delete(f"/api/reports/{alice_report}/shares/{share['id']}").status_code == 204
    assert anon.get(shared_path(share["path"])).status_code == 404
    listed = alice.get(f"/api/reports/{alice_report}/shares").json()
    assert listed[0]["status"] == "revoked"


def test_expired_link_stops_working(alice, anon, alice_report, settings):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    assert anon.get(shared_path(share["path"])).status_code == 200
    db_exec(settings, "UPDATE share_links SET expires_at = expires_at - 7200")   # move expiry into the past
    assert anon.get(shared_path(share["path"])).status_code == 404
    assert alice.get(f"/api/reports/{alice_report}/shares").json()[0]["status"] == "expired"


def test_invalid_expired_and_revoked_links_look_identical(alice, anon, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    alice.delete(f"/api/reports/{alice_report}/shares/{share['id']}")
    revoked = anon.get(shared_path(share["path"]))
    garbage = anon.get("/api/shared/not-a-real-token")
    assert revoked.status_code == garbage.status_code == 404
    assert revoked.json() == garbage.json()      # nothing to learn by probing


def test_share_requires_a_sane_expiry(alice, alice_report):
    for hours in (0, -5, 24 * 91):
        assert alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": hours}).status_code == 422
    assert alice.post(f"/api/reports/{alice_report}/shares", json={}).status_code == 422


def test_token_is_not_stored_in_the_database(alice, alice_report, settings):
    import sqlite3
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    token = share["path"].removeprefix("/s/")
    conn = sqlite3.connect(settings.db_path)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM share_links")]
    conn.close()
    assert token not in stored and len(stored[0]) == 64   # sha256 hex, not the token itself


def test_deleting_a_report_kills_its_links(alice, anon, alice_report):
    share = alice.post(f"/api/reports/{alice_report}/shares", json={"expires_in_hours": 1}).json()
    alice.delete(f"/api/reports/{alice_report}")
    assert anon.get(shared_path(share["path"])).status_code == 404


def test_cross_site_post_is_blocked(alice, alice_dataset):
    r = alice.post("/api/reports", json={"dataset_id": alice_dataset, "title": "x"},
                   headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
