"""
Minimal experiment runner for baseline or stateful agents.

Usage (from repo root):
    python -m src.experiment --agent baseline  --trials 10 --model "Qwen/Qwen3-8B"
    python -m src.experiment --agent stateful  --trials 10 --model "Qwen/Qwen3-8B"

Outputs:
    logs/
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

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
DATA_DIR = THIS_DIR / "data"
LOGS_DIR = REPO_ROOT / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)


from .agent.prompts import USER_PROMPT
from .agent.baseline_agent import run_baseline_trial
from .agent.stateful_agent import run_stateful_trial

FLIGHT_FILE = DATA_DIR / "flight_bookings.json"
HOTEL_FILE  = DATA_DIR / "hotel_bookings.json"

def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def _reset_bookings() -> None:
    _write_json(FLIGHT_FILE, {})
    _write_json(HOTEL_FILE, {})

def _detect_success() -> Tuple[bool, str, str]:
    """Success iff there is BOTH:
    - a flight with departure == 2025-10-03 and return == 2025-10-10, and
    - a hotel with check_in == 2025-10-03 and check_out == 2025-10-10.
    """
    TARGET_START = "2025-10-03"
    TARGET_END = "2025-10-10"

    flights = _read_json(FLIGHT_FILE) or {}
    hotels = _read_json(HOTEL_FILE) or {}

    matched_f_conf = ""
    matched_h_conf = ""

    # Find any flight matching the exact target date span
    for conf_id, payload in getattr(flights, "items", lambda: [])():
        try:
            dep = str(payload.get("departure", ""))
            ret = str(payload.get("return", ""))
        except Exception:
            continue
        if dep == TARGET_START and ret == TARGET_END:
            matched_f_conf = conf_id
            break

    # Find any hotel matching the exact target date span
    for conf_id, payload in getattr(hotels, "items", lambda: [])():
        try:
            check_in = str(payload.get("check_in", ""))
            check_out = str(payload.get("check_out", ""))
        except Exception:
            continue
        if check_in == TARGET_START and check_out == TARGET_END:
            matched_h_conf = conf_id
            break

    success = bool(matched_f_conf and matched_h_conf)
    return success, matched_f_conf, matched_h_conf

def _count_tool_calls(messages) -> Tuple[int, Dict[str, int]]:
    total = 0
    by_type: Dict[str, int] = {}
    for m in messages:
        # tool_calls in additional_kwargs
        ak = getattr(m, "additional_kwargs", {}) or {}
        tcalls = ak.get("tool_calls", [])
        if isinstance(tcalls, list) and tcalls:
            total += len(tcalls)
            for t in tcalls:
                func_name = ((t.get("function") or {}).get("name")) or "unknown"
                by_type[func_name] = by_type.get(func_name, 0) + 1

        # explicit tool message
        if getattr(m, "type", None) == "tool":
            name = getattr(m, "name", "tool")
            total += 1
            by_type[name] = by_type.get(name, 0) + 1
    return total, by_type

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
        # 1) Standardized LangChain usage metadata (preferred)
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
def run_single_trial(recursion_limit: int = 40, agent: str = "baseline") -> Dict[str, Any]:
    _reset_bookings()
    start = time.time()
    try:
        if agent == "stateful":
            result = run_stateful_trial(USER_PROMPT, recursion_limit=recursion_limit)
        else:
            result = run_baseline_trial(USER_PROMPT, recursion_limit=recursion_limit)
        finished = True
        error = ""
    except Exception as e:
        finished = False
        error = str(e)
        result = {"messages": []}
    elapsed = round(time.time() - start, 3)

    messages = result.get("messages", [])
    success, f_conf, h_conf = _detect_success()
    tool_total, tool_by_type = _count_tool_calls(messages)
    usage = _pull_usage(messages)

    return {
        "messages": messages,
        "metrics": {
            "finished": finished,
            "error": error,
            "success": success,
            "flight_conf": f_conf,
            "hotel_conf": h_conf,
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
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
    base = f"{ts}_{args.agent}_{model_tag}"

    jsonl_path   = LOGS_DIR / f"{base}.jsonl"

    # Prepare writers
    with open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
        successes = 0
        finished_cnt = 0
        for i in range(1, args.trials + 1):
            trial = run_single_trial(recursion_limit=args.recursion_limit, agent=args.agent)
            metrics = trial["metrics"]
            messages = trial["messages"]

            row = {
            "run_id": i,
            "finished": 1 if metrics.get("finished") else 0,
            "error": metrics.get("error", ""),
            "success": 1 if metrics["success"] else 0,
            "flight_conf": metrics["flight_conf"],
            "hotel_conf": metrics["hotel_conf"],
            "tool_calls_total": metrics["tool_calls_total"],
            "tool_calls_by_type": json.dumps(metrics["tool_calls_by_type"], sort_keys=True),
            "prompt_tokens": metrics["prompt_tokens"],
            "completion_tokens": metrics["completion_tokens"],
            "total_tokens": metrics["total_tokens"],
            "elapsed_sec": metrics["elapsed_sec"],
            "message_count": metrics["message_count"],
            }
            # Write this trial's console output to its own file
            per_trial_log = LOGS_DIR / f"{base}_run{i}.output.log"
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

            # JSONL: per-trial metrics only
            f_jsonl.write(json.dumps({"run_id": i, **row}, ensure_ascii=False) + "\n")
            f_jsonl.flush()

            if metrics["success"]:
                successes += 1
            if metrics.get("finished"):
                finished_cnt += 1

        # Final summary printed to stdout
        print(f"Finished {finished_cnt}/{args.trials} | Success {successes}/{args.trials}")
        print(f"Wrote:\n  {jsonl_path}")

if __name__ == "__main__":
    main()