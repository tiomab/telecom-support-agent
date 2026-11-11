"""Eval harness: python -m evals.run_evals [--model MODEL_ID] [--repeat 3] [--only id1,id2] [--judge]

For each case: fresh agent → run question → check
  1. tool selection (expected tools requested, forbidden tools not requested, forbidden inputs absent),
  2. answer content (expect_any),
  3. optionally an LLM-as-judge for groundedness (--judge).
Prints a table and saves raw results to evals/results/<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import yaml


from pydantic import BaseModel  # noqa: E402
from strands import Agent  # noqa: E402

from app.agent import build_agent, build_model, login  # noqa: E402
from app.prompts import customer_context  # noqa: E402

HERE = Path(__file__).parent


class Verdict(BaseModel):
    grounded: bool  # every fact in the answer is supported by the tool results
    answers_question: bool
    reason: str


JUDGE_PROMPT = """You are grading a customer-support answer.
Tool results (the ONLY allowed source of facts):
<tool_results>
{tool_results}
</tool_results>

Customer question: {question}

Answer to grade:
<answer>
{answer}
</answer>

grounded = true only if every price, rule, deadline and step in the answer is supported by the tool results.
answers_question = true if the answer actually addresses the customer's question (saying "I don't know, contact a human"
counts as answering when the tool results do not contain the information)."""


def _text(content: list[dict]) -> str:
    return "\n".join(b["text"] for b in content if "text" in b)


def _tool_results(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        for block in m.get("content", []):
            tr = block.get("toolResult")
            if tr:
                parts.append(_text(tr.get("content", [])))
    return "\n---\n".join(parts) or "(no tool results)"


def judge(question: str, answer: str, tool_results: str, model_id: str | None) -> Verdict:
    j = Agent(model=build_model(model_id), callback_handler=None, structured_output_model=Verdict)
    res = j(JUDGE_PROMPT.format(question=question, answer=answer, tool_results=tool_results[:12000]))
    return res.structured_output


def run_case(case: dict, model_id: str | None, use_judge: bool) -> dict:
    approve = bool(case.get("approve", False))
    token = login(case["customer"]) if case.get("customer") else None
    agent, guard = build_agent(
        lambda name, inp: approve, token_fn=lambda: token, model_id=model_id, stream_to_stdout=False
    )

    t0 = time.perf_counter()
    error = None
    try:
        result = agent(customer_context(case.get("customer")) + case["question"])
        answer = _text(result.message["content"])
        usage = dict(result.metrics.accumulated_usage)
    except Exception as e:  # a crash is a failed case, not a crashed eval run
        answer, usage, error = "", {}, repr(e)
    latency = time.perf_counter() - t0

    requested = [c["name"] for c in guard.requested]
    inputs_blob = json.dumps([c["input"] for c in guard.requested], ensure_ascii=False)

    checks = {
        "expected_tools": all(t in requested for t in case.get("expect_tools", [])),
        "no_forbidden_tools": not any(t in requested for t in case.get("forbid_tools", [])),
        "no_forbidden_input": not any(s in inputs_blob for s in case.get("forbid_input", [])),
        "answer_content": (
            any(s.lower() in answer.lower() for s in case["expect_any"]) if case.get("expect_any") else True
        ),
    }
    if error:
        checks["no_error"] = False

    verdict = None
    if use_judge and not error:
        v = judge(case["question"], answer, _tool_results(agent.messages), model_id)
        verdict = v.model_dump()
        checks["judge_grounded"] = v.grounded
        checks["judge_answers"] = v.answers_question

    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "tools_requested": requested,
        "latency_s": round(latency, 2),
        "usage": usage,
        "answer": answer,
        "judge": verdict,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case (LLMs are non-deterministic)")
    parser.add_argument("--only", default=None, help="Comma-separated case ids")
    parser.add_argument("--judge", action="store_true", help="Add LLM-as-judge groundedness check")
    args = parser.parse_args()

    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    results = []
    for case in cases:
        for r in range(args.repeat):
            res = run_case(case, args.model, args.judge)
            res["run"] = r + 1
            results.append(res)
            failed = [k for k, v in res["checks"].items() if not v]
            mark = "PASS" if res["passed"] else "FAIL"
            print(f"{mark}  {res['id']:<34} {res['latency_s']:>6.1f}s  tools={res['tools_requested']}"
                  + (f"  failed={failed}" if failed else ""))

    n = len(results)
    passed = sum(r["passed"] for r in results)
    tool_ok = sum(r["checks"]["expected_tools"] and r["checks"]["no_forbidden_tools"] for r in results)
    tok_in = sum(r["usage"].get("inputTokens", 0) for r in results)
    tok_out = sum(r["usage"].get("outputTokens", 0) for r in results)
    cache_read = sum(r["usage"].get("cacheReadInputTokens", 0) for r in results)
    lat = sorted(r["latency_s"] for r in results)

    print("\n" + "=" * 70)
    print(f"Pass rate:            {passed}/{n} ({passed / n:.0%})")
    print(f"Tool selection OK:    {tool_ok}/{n} ({tool_ok / n:.0%})")
    print(f"Latency p50 / max:    {lat[n // 2]:.1f}s / {lat[-1]:.1f}s")
    print(f"Tokens in / out:      {tok_in} / {tok_out}   (cache read: {cache_read})")

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
