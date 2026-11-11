"""SQLite storage: customers, outages, tickets. Customers and outages are seeded from backend/seed/*.json on first start."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from backend import auth

HERE = Path(__file__).resolve().parent
SEED_DIR = HERE / "seed"
DB_PATH = Path(os.getenv("DB_PATH", HERE / "novatel.db"))
DEMO_PASSWORD = "demo"  # every seeded test customer gets this password

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    mobile_plan TEXT,
    home_internet TEXT,
    contract TEXT,
    account_status TEXT NOT NULL,
    overdue_balance_eur REAL NOT NULL DEFAULT 0,
    travel_pass_enabled INTEGER NOT NULL DEFAULT 0,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outages (
    id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    service TEXT NOT NULL,
    description TEXT NOT NULL,
    started TEXT NOT NULL,
    estimated_restoration TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    summary TEXT NOT NULL,
    created TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables; fill them from seed/customers.json and seed/outages.json if empty."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            customers = json.loads((SEED_DIR / "customers.json").read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (cid, c["name"], c["region"], c["mobile_plan"], c["home_internet"], c["contract"],
                     c["account_status"], c["overdue_balance_eur"], int(c["travel_pass_enabled"]),
                     auth.hash_password(DEMO_PASSWORD))
                    for cid, c in customers.items()
                ],
            )
        if conn.execute("SELECT COUNT(*) FROM outages").fetchone()[0] == 0:
            outages = json.loads((SEED_DIR / "outages.json").read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO outages VALUES (?,?,?,?,?,?)",
                [
                    (o["id"], region, o["service"], o["description"], o["started"], o["estimated_restoration"])
                    for region, items in outages.items()
                    for o in items
                ],
            )


def get_customer(customer_id: str, with_password: bool = False) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id.strip().upper(),)).fetchone()
    if row is None:
        return None
    customer = dict(row)
    customer["travel_pass_enabled"] = bool(customer["travel_pass_enabled"])
    if not with_password:
        del customer["password_hash"]
    return customer


def outages_in(region: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, region, service, description, started, estimated_restoration "
            "FROM outages WHERE lower(region) = lower(?)",
            (region.strip(),),
        ).fetchall()
    return [dict(r) for r in rows]


def create_ticket(customer_id: str, category: str, priority: str, summary: str) -> dict:
    ticket = {
        "ticket_id": f"T-{uuid.uuid4().hex[:6].upper()}",
        "customer_id": customer_id.strip().upper(),
        "category": category,
        "priority": priority,
        "summary": summary,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    with connect() as conn:
        conn.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?)", tuple(ticket.values()))
    return ticket
