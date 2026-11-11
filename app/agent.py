"""The Strands agent: model + system prompt + tools + guard hooks."""

from __future__ import annotations

from typing import Callable

import httpx
import httpx2
from strands import Agent
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from strands.hooks import BeforeInvocationEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import CacheConfig
from strands.models.anthropic import AnthropicModel
from strands.tools.mcp import MCPClient

from app import config
from app.prompts import SYSTEM_PROMPT
from app.tools import ALL_TOOLS

# Tools that change the outside world and therefore need a human "yes".
APPROVAL_REQUIRED = {"create_ticket"}

ApproveFn = Callable[[str, dict], bool]


class SupportGuard(HookProvider):
    """Code-level guardrails (not prompt-level):

    1. Human-in-the-loop: tools in APPROVAL_REQUIRED run only if approve_fn returns True.
       approve_fn=None (web server): the agent stops with a Strands interrupt instead, and the caller
       resumes it with {"interruptResponse": {"interruptId": ..., "response": True/False}}.
    2. Step limit: at most MAX_TOOL_CALLS tool calls per user message, so the agent cannot loop forever.
    3. Records every requested tool call (used by the evals to check tool selection).
    """

    def __init__(self, approve_fn: ApproveFn | None, max_tool_calls: int = config.MAX_TOOL_CALLS):
        self.approve_fn = approve_fn
        self.max_tool_calls = max_tool_calls
        self.calls_this_turn = 0
        self.requested: list[dict] = []  # [{"name": ..., "input": {...}}] for the current turn

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self._reset)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)

    def _reset(self, event: BeforeInvocationEvent) -> None:
        self.calls_this_turn = 0
        self.requested = []

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        tool_input = event.tool_use.get("input", {})
        self.requested.append({"name": name, "input": tool_input})
        self.calls_this_turn += 1

        if self.calls_this_turn > self.max_tool_calls:
            event.cancel_tool = (
                f"Tool call limit ({self.max_tool_calls}) reached for this message. "
                "Stop calling tools and answer with the information you already have."
            )
            return

        if name not in APPROVAL_REQUIRED:
            return
        if self.approve_fn is None:
            approved = event.interrupt("approval", reason={"tool": name, "input": tool_input}) is True
        else:
            approved = self.approve_fn(name, tool_input)
        if not approved:
            event.cancel_tool = (
                f"The human operator REJECTED the {name} call. Do not retry it. "
                "Tell the customer and suggest the next best option."
            )


class BearerAuth(httpx2.Auth):
    """Adds the customer's session token to every MCP request. The backend reads the customer ID from it."""

    def __init__(self, token_fn: Callable[[], str | None]):
        self.token_fn = token_fn  # a function, so a fresh token (re-login) reaches an already-running agent

    def auth_flow(self, request):
        if token := self.token_fn():
            request.headers["Authorization"] = f"Bearer {token}"
        yield request


def login(customer_id: str, password: str = "demo") -> str:
    """Get a backend session token (CLI and evals; the web UI logs in itself). Seeded customers use "demo"."""
    resp = httpx.post(f"{config.BACKEND_URL}/auth/login", json={"customer_id": customer_id, "password": password})
    resp.raise_for_status()
    return resp.json()["token"]


def build_model(model_id: str | None = None) -> AnthropicModel:
    return AnthropicModel(
        model_id=model_id or config.MODEL_ID,
        max_tokens=config.MAX_TOKENS,
        params={"temperature": config.TEMPERATURE},
        # Prompt caching: system prompt + tool definitions are the same on every call,
        # and every step of the agent loop re-sends the whole conversation.
        cache_config=CacheConfig(strategy="anthropic", tools_ttl=True),
    )


def build_agent(
    approve_fn: ApproveFn | None,
    token_fn: Callable[[], str | None],
    model_id: str | None = None,
    stream_to_stdout: bool = True,
) -> tuple[Agent, SupportGuard]:
    """token_fn returns the customer's backend session token (None = not logged in)."""
    guard = SupportGuard(approve_fn)
    mcp = MCPClient(lambda: streamable_http_client(
        config.MCP_URL, http_client=create_mcp_http_client(auth=BearerAuth(token_fn))
    ))
    agent = Agent(
        model=build_model(model_id),
        system_prompt=SYSTEM_PROMPT,
        # Customer, outage and ticket tools live in the backend and are loaded over MCP.
        tools=[*ALL_TOOLS, mcp],
        hooks=[guard],
        # None = silent (evals); default handler streams tokens to stdout (CLI).
        **({} if stream_to_stdout else {"callback_handler": None}),
    )
    return agent, guard
