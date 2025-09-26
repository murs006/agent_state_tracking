"""
Minimal experiment runner for baseline or stateful agents across tasks.

Usage (from repo root):
    python -m src.experiment --task ticket_booking --agent baseline  --trials 10 --model "Qwen/Qwen3-8B"
    python -m src.experiment --task ticket_booking --agent stateful  --trials 10 --model "Qwen/Qwen3-8B"

Outputs (per task):
    src/tasks/<task>/logs/
        <timestamp>_<agent>_<model>.jsonl                # per-trial metrics only
        <timestamp>_<agent>_<model>_run<i>.output.log     # per-trial console output
"""

from __future__ import annotations
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple
from importlib import import_module

THIS_DIR = Path(__file__).resolve().parent

def _count_tool_calls(messages) -> Tuple[int, Dict[str, int]]:
    by: Dict[str, int] = {}
    seen = set()
    for m in messages:
        if getattr(m, "type", "") not in ("ai", "assistant") and m.__class__.__name__ != "AIMessage":
            continue
        for c in (getattr(m, "tool_calls", None) or []):
            name = ((c.get("function") or {}).get("name")) or c.get("name")
            if not name: 
                continue
            cid = c.get("id") or c.get("tool_call_id")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            by[name] = by.get(name, 0) + 1
    return sum(by.values()), by


def _pull_usage(messages) -> Dict[str, int]:
    """Aggregate token usage from LangChain/OpenAI message metadata.

    Supports multiple locations depending on wrapper/provider:
    - m.usage_metadata: {input_tokens, output_tokens, total_tokens}
    - m.response_metadata.token_usage or .usage: {prompt_tokens|input_tokens, completion_tokens|output_tokens}
    - m.additional_kwargs.usage or .token_usage: same as above
    """
    prompt_t = 0
    completion_t = 0

    def _to_int(v: Any) -> int:
        try:
            return int(v)
        except Exception:
            return 0

    for m in messages:
        # 1) Standardized LangChain usage metadata
        um = getattr(m, "usage_metadata", None)
        if isinstance(um, dict) and um:
            prompt_t += _to_int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
            completion_t += _to_int(um.get("output_tokens") or um.get("completion_tokens") or 0)
            continue

        # 2) Response metadata often holds provider-specific token usage
        rm = getattr(m, "response_metadata", None)
        if isinstance(rm, dict) and rm:
            tu = rm.get("token_usage") or rm.get("usage")
            if isinstance(tu, dict) and tu:
                prompt_t += _to_int(tu.get("prompt_tokens") or tu.get("input_tokens") or 0)
                completion_t += _to_int(tu.get("completion_tokens") or tu.get("output_tokens") or 0)
                continue

        # 3) Fallback: additional_kwargs sometimes mirrors usage
        ak = getattr(m, "additional_kwargs", {}) or {}
        usage = ak.get("usage") or ak.get("token_usage")
        if isinstance(usage, dict) and usage:
            prompt_t += _to_int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_t += _to_int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    return {
        "prompt_tokens": prompt_t,
        "completion_tokens": completion_t,
        "total_tokens": prompt_t + completion_t,
    }


# Trial runner
def run_single_trial(TASK, recursion_limit: int = 40, agent: str = "baseline") -> Dict[str, Any]:
    TASK.reset_state()
    start = time.time()
    try:
        # Load the task's prompt module for user prompt
        prompts_mod = import_module(f"src.tasks.{TASK.name}.agent.prompts")
        USER_PROMPT = getattr(prompts_mod, "USER_PROMPT")
        
        if agent == "stateful":
            stateful_mod = import_module(f"src.tasks.{TASK.name}.agent.stateful_agent")
            result = stateful_mod.run_stateful_trial(
                USER_PROMPT, recursion_limit=recursion_limit, live=False
            )
        else:
            result = TASK.run_baseline(USER_PROMPT, recursion_limit=recursion_limit)
        finished = True
        error = ""
    except Exception as e:
        finished = False
        error = str(e)
        result = {"messages": []}
    elapsed = round(time.time() - start, 3)

    messages = result.get("messages", [])
    # Task-agnostic success detection
    success = TASK.detect_success()
    tool_total, tool_by_type = _count_tool_calls(messages)
    usage = _pull_usage(messages)

    return {
        "messages": messages,
        "metrics": {
            "finished": finished,
            "error": error,
            "success": success,
            "tool_calls_total": tool_total,
            "tool_calls_by_type": tool_by_type,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "elapsed_sec": elapsed,
            "message_count": len(messages),
        },
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=10, help="How many runs.")
    parser.add_argument("--agent", type=str, default="baseline", choices=["baseline", "stateful"],
                        help="Which agent to run.")
    parser.add_argument("--model", type=str, default="Qwen/Qwen3-8B",
                        help="Model name to annotate logs with (does not change the agent unless your agent reads this).")
    parser.add_argument("--recursion-limit", type=int, default=40,
                        help="LangGraph recursion limit for the baseline agent.")
    parser.add_argument("--task", type=str, default="ticket_booking",
                        help="Task package under src/tasks to load (e.g., ticket_booking, file_ops, web_scraping).")
    args = parser.parse_args()

    # Load selected task
    task_mod = import_module(f"src.tasks.{args.task}")
    TASK = getattr(task_mod, "TASK")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
    base = f"{ts}_{args.agent}_{model_tag}"

    # Per-task logs folder to keep runs separate
    task_logs_dir = (THIS_DIR / "tasks" / TASK.name / "logs")
    task_logs_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path   = task_logs_dir / f"{base}.jsonl"

    # Prepare writers
    with open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
        successes = 0
        finished_cnt = 0
        for i in range(1, args.trials + 1):
            trial = run_single_trial(TASK, recursion_limit=args.recursion_limit, agent=args.agent)
            metrics = trial["metrics"]
            messages = trial["messages"]

            row = {
                "run_id": i,
                "finished": 1 if metrics.get("finished") else 0,
                "error": metrics.get("error", ""),
                "success": 1 if metrics["success"] else 0,
                "tool_calls_total": metrics["tool_calls_total"],
                "tool_calls_by_type": json.dumps(metrics["tool_calls_by_type"], sort_keys=True),
                "prompt_tokens": metrics["prompt_tokens"],
                "completion_tokens": metrics["completion_tokens"],
                "total_tokens": metrics["total_tokens"],
                "elapsed_sec": metrics["elapsed_sec"],
                "message_count": metrics["message_count"],
            }
            # Write this trial's console output to its own file
            per_trial_log = task_logs_dir / f"{base}_run{i}.output.log"
            with open(per_trial_log, "w", encoding="utf-8") as f_trial:
                _prev_stdout = sys.stdout
                sys.stdout = f_trial
                try:
                    for m in messages:
                        try:
                            m.pretty_print()
                        except Exception:
                            print(getattr(m, "type", ""), getattr(m, "content", ""))
                finally:
                    sys.stdout = _prev_stdout

            f_jsonl.write(json.dumps({"run_id": i, **row}, ensure_ascii=False) + "\n")
            f_jsonl.flush()

            if metrics["success"]:
                successes += 1
            if metrics.get("finished"):
                finished_cnt += 1

        print(f"Finished {finished_cnt}/{args.trials} | Success {successes}/{args.trials}")
    print(f"Wrote:\n  {jsonl_path}")

if __name__ == "__main__":
    main()