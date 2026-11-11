"""pytest backend/ — auth and data API."""

import json
import os
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth  # noqa: E402
from backend import db  # noqa: E402
from backend.main import app, create_ticket, get_customer  # noqa: E402


def ctx(token: str | None) -> SimpleNamespace:
    """Stand-in for the MCP Context: the tools only read ctx.headers."""
    return SimpleNamespace(headers={"authorization": f"Bearer {token}"} if token else {})


def test_login_me_and_auth_errors():
    with TestClient(app) as client:
        assert client.post("/auth/login", json={"customer_id": "C1003", "password": "nope"}).status_code == 401
        assert client.post("/auth/login", json={"customer_id": "C9999", "password": "demo"}).status_code == 401

        token = client.post("/auth/login", json={"customer_id": "c1003", "password": "demo"}).json()["token"]
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["id"] == "C1003" and me["account_status"] == "suspended"
        assert "password_hash" not in me

        real = auth.issue_token("C1001")
        forged = real[:-1] + ("1" if real[-1] == "0" else "0")  # tampered signature
        for bad in (forged, "garbage", "a.b"):
            assert client.get("/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401

        outages = client.get("/outages", params={"region": "bucharest"}, headers={"Authorization": f"Bearer {token}"})
        assert [o["id"] for o in outages.json()] == ["OUT-2311"]


def test_create_ticket_validates_and_stores():
    db.init_db()  # no TestClient: the MCP session manager can only start once per process
    me = ctx(auth.issue_token("C1001"))
    assert "Invalid category" in create_ticket("router", "dead", me)
    assert "Invalid priority" in create_ticket("technical", "dead", me, priority="urgent")
    for bad in (ctx(None), ctx("garbage"), ctx(auth.issue_token("C9999"))):
        assert "not logged in" in create_ticket("technical", "dead", bad)
    created = json.loads(create_ticket("technical", "Router dead after reboot", me))
    assert created["status"] == "created" and created["customer_id"] == "C1001"
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (created["ticket_id"],)).fetchone()
    assert row["summary"] == "Router dead after reboot"


def test_get_customer_reads_id_from_token():
    db.init_db()
    assert json.loads(get_customer(ctx(auth.issue_token("C1003"))))["customer_id"] == "C1003"
    assert "not logged in" in get_customer(ctx(None))
    assert "not logged in" in get_customer(ctx("garbage"))
