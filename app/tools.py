"""Tools the agent can call.

Design rules (they matter more than the model):
- clear names and docstrings: the docstring IS the tool description the model sees;
- narrow parameters;
- bounded output size;
- actionable errors that tell the model what to do next.
"""

from __future__ import annotations

from strands import tool

from app import rag

MAX_CHUNK_CHARS = 1200  # bound tool output so the context does not blow up


@tool
def search_kb(query: str) -> str:
    """Search the NovaTel knowledge base (plans, roaming, billing, router, SIM, contracts, outages policy).

    Use this for ANY question about prices, rules, procedures or troubleshooting steps.
    Write the query in English as a short, specific phrase, e.g. "Travel Pass Turkey price".
    You may call it several times with different queries if the first results are not relevant.

    Args:
        query: Short search phrase in English.
    """
    hits = rag.search(query)
    if not hits:
        return "No results. Try a different, more general query."
    out = []
    for h in hits:
        out.append(
            f"[source: {h['source']} | {h['section']} | score {h['score']}]\n"
            f"{h['text'][:MAX_CHUNK_CHARS]}"
        )
    return "\n\n---\n\n".join(out)



# get_customer, check_outages and create_ticket come from the backend MCP server (see app/agent.py).
ALL_TOOLS = [search_kb]
