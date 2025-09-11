from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


FILENAME_PATTERN = re.compile(
    r"^(?P<ts>\d{8}-\d{6})_(?P<agent>baseline|stateful)_[^_]+_(?P<model>[^.]+)\.jsonl$"
)


@dataclass
class Aggregate:
    trials: int = 0
    successes: int = 0
    finished: int = 0

    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0

    def completion_rate(self) -> float:
        return self.finished / self.trials if self.trials else 0.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot experiment success & completion rates.")
    p.add_argument("--logs-dir", type=Path, default=Path("logs"), help="Directory containing JSONL log files.")
    p.add_argument("--output-dir", type=Path, default=Path("plots"), help="Directory to write plot images.")
    p.add_argument("--show", action="store_true", help="Display plots interactively (if backend allows).")
    return p.parse_args()


def discover_jsonl(logs_dir: Path) -> List[Path]:
    return sorted([p for p in logs_dir.glob("*.jsonl") if p.is_file()])


def extract_metadata(path: Path) -> Tuple[str, str]:
    """Return (agent_type, model) from filename or raise ValueError."""
    m = FILENAME_PATTERN.match(path.name)
    if not m:
        raise ValueError(f"Unrecognized filename pattern: {path.name}")
    return m.group("agent"), m.group("model")


def aggregate(files: List[Path]) -> Dict[Tuple[str, str], Aggregate]:
    data: Dict[Tuple[str, str], Aggregate] = defaultdict(Aggregate)
    for f in files:
        try:
            agent, model = extract_metadata(f)
        except ValueError:
            # Skip files that don't match the expected naming convention.
            continue
        key = (agent, model)
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                agg = data[key]
                agg.trials += 1
                if rec.get("success"):
                    agg.successes += 1
                if rec.get("finished"):
                    agg.finished += 1
    return data


def prepare_series(aggregates: Dict[Tuple[str, str], Aggregate]):
    """Prepare ordered series for plotting.

    Custom model ordering requested: 8B first, then 14B, then 32B, followed by any
    other sizes (if present) in ascending numeric order. We attempt to extract a
    size token like '8B'/'14B'/'32B' from the model string; fallback puts model
    names at the end in lexical order.
    """

    raw_models = sorted(set(model for (_, model) in aggregates.keys()))

    size_priority = ["8B", "14B", "32B"]
    size_order_map = {tok: i for i, tok in enumerate(size_priority)}

    def model_sort_key(m: str):
        # Find first matching size token.
        for tok in size_priority:
            if tok in m:
                return (0, size_order_map[tok], m)
        # Try to extract any number+B pattern for extended ordering.
        m_num = re.search(r"(\d+)[Bb]", m)
        if m_num:
            # Place after explicit priority list.
            return (1, int(m_num.group(1)), m)
        # Fallback lexical tail.
        return (2, float('inf'), m)

    models = sorted(raw_models, key=model_sort_key)

    agents = ["baseline", "stateful"]  # fixed ordering
    success = {agent: [] for agent in agents}
    completion = {agent: [] for agent in agents}
    trials = {agent: [] for agent in agents}
    for model in models:
        for agent in agents:
            agg = aggregates.get((agent, model), Aggregate())
            success[agent].append(agg.success_rate())
            completion[agent].append(agg.completion_rate())
            trials[agent].append(agg.trials)
    return models, agents, success, completion, trials


def plot_bar(models, agents, success, completion, trials, output_dir: Path, show: bool):
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as e:  # pragma: no cover - import guard
        print("matplotlib is required for plotting. Install with: pip install matplotlib")
        print(f"Import error: {e}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    x = range(len(models))
    width = 0.35

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    # Success rate subplot
    ax = axes[0]
    ax.bar([i - width/2 for i in x], success[agents[0]], width, label=agents[0])
    ax.bar([i + width/2 for i in x], success[agents[1]], width, label=agents[1])
    ax.set_title("Success Rate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Rate")
    ax.legend()

    # Completion rate subplot
    ax = axes[1]
    ax.bar([i - width/2 for i in x], completion[agents[0]], width, label=agents[0])
    ax.bar([i + width/2 for i in x], completion[agents[1]], width, label=agents[1])
    ax.set_title("Completion Rate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.legend()

    # Derive trial count summary: assume uniform if all same >0.
    flat_counts = [c for agent in agents for c in trials[agent] if c > 0]
    trial_note = ""
    if flat_counts:
        unique_counts = set(flat_counts)
        if len(unique_counts) == 1:
            trial_note = f" (n={next(iter(unique_counts))} trials per agent/model)"
        else:
            trial_note = " (trials vary)"
    fig.suptitle(f"Agent Success & Completion Rates{trial_note}")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    outfile = output_dir / "agent_comparison_rates.png"
    fig.savefig(outfile, dpi=150)
    print(f"Saved plot to {outfile}")
    if show:
        plt.show()
    plt.close(fig)


def main():
    args = parse_args()
    files = discover_jsonl(args.logs_dir)
    if not files:
        print(f"No JSONL files found in {args.logs_dir}")
        return
    aggregates = aggregate(files)
    if not aggregates:
        print("No valid records aggregated (check filename patterns and JSON lines).")
        return
    models, agents, success, completion, trials = prepare_series(aggregates)
    plot_bar(models, agents, success, completion, trials, args.output_dir, args.show)


if __name__ == "__main__":  # pragma: no cover
    main()
