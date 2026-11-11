"""NovaTel backend: REST API for the web UI + MCP server for the agent.

Run: uvicorn backend.main:app --port 8001
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel

from backend import auth, db

# ---------------------------------------------------------------- MCP (for the agent)
# Docstrings are the tool descriptions the model sees.
mcp = MCPServer("novatel")

NOT_AUTHENTICATED = "The customer is not logged in. Ask them to log in; you cannot look up or change any account."


def token_customer_id(ctx: Context) -> str | None:
    """Customer ID from the signed session token the agent forwards, never from tool arguments the model writes."""
    header = (ctx.headers or {}).get("authorization", "")
    return auth.verify_token(header.removeprefix("Bearer ")) if header.startswith("Bearer ") else None


@mcp.tool()
def get_customer(ctx: Context) -> str:
    """Get the logged-in customer's account: name, region, plans, contract, account status, overdue balance, Travel Pass.

    Use it when the answer depends on the customer's own plan, region or account status.
    It always returns the logged-in customer's own account; no other account can be looked up.
    """
    customer_id = token_customer_id(ctx)
    customer = db.get_customer(customer_id) if customer_id else None
    if customer is None:
        return NOT_AUTHENTICATED
    customer["customer_id"] = customer.pop("id")
    return json.dumps(customer, ensure_ascii=False)


@mcp.tool()
def check_outages(region: str) -> str:
    """Check active network outages in a region (e.g. Brasov, Bucharest, Cluj, Timisoara).

    Always call this before troubleshooting or opening a ticket for "no internet" / "no signal" / "slow data" problems.

    Args:
        region: City / region name, e.g. "Bucharest". Get it from get_customer if unknown.
    """
    outages = db.outages_in(region)
    return json.dumps(
        {"region": outages[0]["region"] if outages else region,
         "active_outages": [{k: v for k, v in o.items() if k != "region"} for o in outages]},
        ensure_ascii=False,
    )


@mcp.tool()
def create_ticket(category: str, summary: str, ctx: Context, priority: str = "normal") -> str:
    """Open a support ticket for the logged-in customer. REQUIRES HUMAN APPROVAL: the operator confirms every call.

    Only open a ticket when the knowledge base says a ticket is needed (e.g. troubleshooting did not help
    and there is no known outage, a billing dispute, a faulty router). Do NOT open tickets for known outages.

    Args:
        category: One of "technical", "billing", "sim", "other".
        summary: One or two sentences: the problem and what the customer already tried.
        priority: "normal" or "high". Use "high" only if the customer has no service at all.
    """
    customer_id = token_customer_id(ctx)
    if customer_id is None or db.get_customer(customer_id) is None:
        return NOT_AUTHENTICATED
    if category not in {"technical", "billing", "sim", "other"}:
        return 'Invalid category. Use one of: "technical", "billing", "sim", "other".'
    if priority not in {"normal", "high"}:
        return 'Invalid priority. Use "normal" or "high".'
    return json.dumps({"status": "created", **db.create_ticket(customer_id, category, priority, summary)}, ensure_ascii=False)


mcp_app = mcp.streamable_http_app(streamable_http_path="/")


# ---------------------------------------------------------------- REST (for the web UI)
@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="NovaTel backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/mcp", mcp_app)

bearer = HTTPBearer()


class Login(BaseModel):
    customer_id: str
    password: str


def current_customer_id(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    customer_id = auth.verify_token(creds.credentials)
    if customer_id is None:
        raise HTTPException(401, "Invalid or expired token")
    return customer_id


@app.post("/auth/login")
def login(body: Login) -> dict:
    customer = db.get_customer(body.customer_id, with_password=True)
    if customer is None or not auth.check_password(body.password, customer["password_hash"]):
        raise HTTPException(401, "Wrong customer ID or password")
    return {"token": auth.issue_token(customer["id"])}


@app.get("/me")
def me(customer_id: str = Depends(current_customer_id)) -> dict:
    customer = db.get_customer(customer_id)
    if customer is None:
        raise HTTPException(401, "Customer no longer exists")
    return customer


@app.get("/outages")
def outages(region: str, _: str = Depends(current_customer_id)) -> list[dict]:
    return db.outages_in(region)
