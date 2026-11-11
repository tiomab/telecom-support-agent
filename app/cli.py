"""Terminal chat with the support agent: python -m app.cli [--customer C1001] [--password demo] [--model MODEL_ID]

You play two roles: the customer (typing messages) and the human operator
(approving or rejecting tickets the agent wants to open).
"""

from __future__ import annotations

import argparse
import json

from app.agent import build_agent, login
from app.prompts import customer_context


def operator_approval(tool_name: str, tool_input: dict) -> bool:
    print("\n\n" + "=" * 60)
    print(f"[OPERATOR] The agent wants to call {tool_name}:")
    print(json.dumps(tool_input, indent=2, ensure_ascii=False))
    answer = input("[OPERATOR] Approve? [y/N] ").strip().lower()
    print("=" * 60)
    return answer in {"y", "yes", "д", "да"}


def print_usage(result) -> None:
    u = result.metrics.accumulated_usage
    tools = ", ".join(
        f"{name}×{m.call_count}" for name, m in result.metrics.tool_metrics.items()
    ) or "none"
    print(
        f"\n  · tokens in={u.get('inputTokens', 0)} out={u.get('outputTokens', 0)} "
        f"cache_read={u.get('cacheReadInputTokens', 0)} cache_write={u.get('cacheWriteInputTokens', 0)}"
        f" · tools: {tools}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", default="C1001", help="Authenticated customer ID (or 'none')")
    parser.add_argument("--password", default="demo", help="Customer password (seeded customers use 'demo')")
    parser.add_argument("--model", default=None, help="Override MODEL_ID")
    args = parser.parse_args()

    customer_id = None if args.customer.lower() == "none" else args.customer
    token = login(customer_id, args.password) if customer_id else None
    agent, _ = build_agent(operator_approval, token_fn=lambda: token, model_id=args.model)

    print(f"NovaTel support agent. Customer: {customer_id or 'not authenticated'}. Ctrl+C to quit.\n")
    first = True
    try:
        while True:
            message = input("\nYou: ").strip()
            if not message:
                continue
            if first:
                message = customer_context(customer_id) + message
                first = False
            print("\nAgent: ", end="", flush=True)
            result = agent(message)
            print_usage(result)
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")


if __name__ == "__main__":
    main()
