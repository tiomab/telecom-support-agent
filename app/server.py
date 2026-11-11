"""HTTP API for the support agent: uvicorn app.server:app --port 8000

The web UI sends the backend's session token; the agent asks the backend who it belongs to
and forwards the same token on every MCP call, so the backend tools read the customer ID
from auth, never from the chat or from tool arguments.
"""

from __future__ import annotations

import os

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from strands import Agent

from app import config
from app.agent import build_agent
from app.prompts import customer_context

app = FastAPI(title="NovaTel support agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer()

# shortcut: chat history lives in process memory and is lost on restart; use a Strands session manager for prod.
agents: dict[str, Agent] = {}
tokens: dict[str, str] = {}  # latest token per customer: a re-login keeps the chat and its MCP calls valid


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    interrupt_id: str
    approved: bool


def current_customer_id(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    resp = httpx.get(f"{config.BACKEND_URL}/me", headers={"Authorization": f"Bearer {creds.credentials}"})
    if resp.status_code == 401:
        raise HTTPException(401, "Invalid or expired token")
    resp.raise_for_status()
    customer_id = resp.json()["id"]
    tokens[customer_id] = creds.credentials
    return customer_id


def reply(result) -> dict:
    if result.stop_reason == "interrupt":
        pending = result.interrupts[0]  # only create_ticket interrupts, one tool call at a time
        return {"type": "approval", "interrupt_id": pending.id, **pending.reason}
    return {"type": "answer", "text": str(result).strip()}


@app.post("/chat")
def chat(body: ChatIn, customer_id: str = Depends(current_customer_id)) -> dict:
    message = body.message
    if customer_id not in agents:
        agents[customer_id], _ = build_agent(
            approve_fn=None, token_fn=lambda: tokens.get(customer_id), stream_to_stdout=False
        )
        message = customer_context(customer_id) + message
    return reply(agents[customer_id](message))


@app.post("/chat/approve")
def approve(body: ApproveIn, customer_id: str = Depends(current_customer_id)) -> dict:
    agent = agents.get(customer_id)
    if agent is None:
        raise HTTPException(409, "No conversation is waiting for approval")
    response = {"interruptResponse": {"interruptId": body.interrupt_id, "response": body.approved}}
    return reply(agent([response]))


@app.delete("/chat")
def reset(customer_id: str = Depends(current_customer_id)) -> dict:
    agents.pop(customer_id, None)
    return {"status": "reset"}
