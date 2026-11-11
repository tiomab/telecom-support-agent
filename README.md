# NovaTel Support Agent

A learning project: a customer-support agent for a fictional telecom operator (NovaTel).
It answers from a knowledge base (RAG), looks up the customer's account and network outages
through tools, and opens support tickets only after a human operator approves them.

**Stack:** Python · [Strands Agents](https://strandsagents.com) · Claude (Anthropic API) · Chroma (local vector DB)

## Architecture

Three services:

```
web (Next.js :3000) ──login, /me──► backend (FastAPI :8001) ── SQLite: customers, outages, tickets
        │                                ▲   └─ /mcp/  MCP server: get_customer, check_outages, create_ticket
        └──/chat (Bearer token)──► agent (FastAPI :8000) ──MCP──┘
                                         └─ local tool: search_kb (Chroma)
```

| Part | Code | What it does |
|---|---|---|
| backend | `backend/` | SQLite (`backend/novatel.db`) seeded from `backend/seed/*.json` on first start; login (PBKDF2 password + HMAC token); MCP server for the agent |
| agent | `app/` | Strands agent (ReAct loop, Claude Haiku); `app/server.py` = HTTP API, `app/cli.py` = terminal chat |
| web | `web/` | Login, customer profile card, chat; ticket approval buttons |

The agent never trusts a customer ID from the browser: it sends the token to the backend's `/me` and
takes the ID from the answer. The same token goes in the `Authorization` header of every MCP call, and
`get_customer` / `create_ticket` take the customer ID from it: they have no ID argument, so the model
cannot ask for another customer's account.

```
SupportGuard hooks (code, not prompt):
  • human approval before create_ticket (HITL): y/N prompt in the CLI, Approve/Reject buttons in the web UI
    (Strands interrupt → POST /chat/approve resumes the agent)
  • max 8 tool calls per message (loop protection)
  • records requested tool calls (for evals)
```

Why an **agent** and not a fixed workflow: the path depends on the question. A price question needs only
`search_kb`; "no internet" needs `get_customer` → `check_outages` → troubleshooting → maybe `create_ticket`;
a suspended account needs `get_customer` + billing rules. Coding every path as a workflow does not scale.

Key decisions:
- **Agentic RAG** — search is a tool; the agent can rephrase and search again.
- **Static system prompt** — the customer ID goes into the user message, so the system prompt + tool
  definitions stay identical and are served from the prompt cache.
- **Guardrails in code** — approval and step limits are enforced in a hook, not just asked for in the prompt.
- **Bounded, actionable tool outputs** — chunks are truncated; errors tell the model what to do next.
- **Low temperature (0.2)** — support answers should be consistent.

## Setup

```bash
cd telecom-support-agent
uv venv && source .venv/bin/activate      # or: python3 -m venv .venv
uv pip install -e '.[dev]'                # or: pip install -e '.[dev]'
(cd web && npm install)

export ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com
python -m app.ingest                      # builds .chroma/ (first run downloads a small embedding model)
```

## Run

Start the backend first: the agent loads `get_customer` / `check_outages` from it over MCP.

```bash
uvicorn backend.main:app --port 8001      # 1. backend (creates backend/novatel.db)
uvicorn app.server:app --port 8000        # 2. agent API
cd web && npm run dev                     # 3. UI on http://localhost:3000
```

Or chat in the terminal (backend still required): `python -m app.cli --customer C1003`.

Test customers (password `demo` for all): `C1001` Brasov (all fine), `C1002` Cluj (Nova Start, no internet plan),
`C1003` Bucharest (suspended, overdue balance, active fibre outage), `C1004` Timisoara (5G outage).
Delete `backend/novatel.db` to re-seed from `backend/seed/`.

Env vars: `AUTH_SECRET` (token signing key; without it tokens die on backend restart), `BACKEND_URL` / `MCP_URL`
(agent → backend), `CORS_ORIGINS`, `NEXT_PUBLIC_BACKEND_URL` / `NEXT_PUBLIC_AGENT_URL` (web).

Backend tests: `pytest backend/`.

## Evals

The backend must be running (customer, outage and ticket tools come over MCP). Cases with `approve: true`
create real tickets, so run the backend on a throwaway DB:
`DB_PATH=/tmp/novatel-evals.db uvicorn backend.main:app --port 8001`.

```bash
python -m evals.run_evals                 # 17 cases, deterministic checks
python -m evals.run_evals --repeat 3      # LLMs are non-deterministic: measure pass rate over runs
python -m evals.run_evals --judge         # + LLM-as-judge groundedness check
python -m evals.run_evals --only outage-bucharest,cancel-contract
python -m evals.run_evals --model claude-sonnet-5-5   # compare models
```

Each case checks: expected tools were requested, forbidden tools were not, no other customer's ID leaked into
tool inputs (prompt injection), and the answer contains the key fact. Results: `evals/results/*.json`.

| Run | Model | Pass rate | Tool selection | p50 latency | Notes |
|---|---|---|---|---|---|
| baseline | | | | | |

## Ideas for next steps
- Hybrid search (BM25 + vectors) and a reranker; measure retrieval recall@k separately.
- Streaming answers (SSE) in `app/server.py` + Dockerfiles / docker-compose.
- Persist chat history (Strands session manager) instead of process memory.
- Switch the model provider to Bedrock (`BedrockModel`) — one line in `app/agent.py`.
