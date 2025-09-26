from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


# Filename convention written by src/experiment.py
# Example: 20250908-194535_baseline_Qwen_Qwen3-8B.jsonl
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
    p = argparse.ArgumentParser(description="Plot success/completion per task from logs under src/tasks/<task>/logs/.")
    p.add_argument("--tasks-dir", type=Path, default=Path("src/tasks"), help="Root 'tasks' directory to scan.")
    p.add_argument("--output-dir", type=Path, default=Path("plots"), help="Directory to write plot images.")
    p.add_argument("--show", action="store_true", help="Display plots interactively.")
    return p.parse_args()


def discover_tasks(tasks_dir: Path) -> List[Tuple[str, Path]]:
    """Return list of (task_name, logs_dir) for tasks that have a logs directory."""
    results: List[Tuple[str, Path]] = []
    if not tasks_dir.exists():
        return results
    for child in tasks_dir.iterdir():
        if not child.is_dir():
            continue
        logs = child / "logs"
        if logs.is_dir():
            results.append((child.name, logs))
    return sorted(results, key=lambda t: t[0])


def discover_jsonl(logs_dir: Path) -> List[Path]:
    return sorted([p for p in logs_dir.glob("*.jsonl") if p.is_file()])


def extract_metadata(path: Path) -> Tuple[str, str]:
    m = FILENAME_PATTERN.match(path.name)
    if not m:
        raise ValueError(f"Unrecognized filename pattern: {path.name}")
    return m.group("agent"), m.group("model")


def aggregate(files: Iterable[Path]) -> Dict[Tuple[str, str], Aggregate]:
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
    # Simple alphabetical sort is fine
    models = sorted({model for (_, model) in aggregates.keys()})
    agents = ["baseline", "stateful"]

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


def plot_task_bar(task: str, models, agents, success, completion, trials, output_dir: Path, show: bool):
    import matplotlib.pyplot as plt
    output_dir.mkdir(parents=True, exist_ok=True)

    x = range(len(models))
    width = 0.35

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    # Success rate subplot
    ax = axes[0]
    ax.bar([i - width / 2 for i in x], success[agents[0]], width, label=agents[0])
    ax.bar([i + width / 2 for i in x], success[agents[1]], width, label=agents[1])
    ax.set_title("Success Rate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Rate")
    ax.legend()

    # Completion rate subplot
    ax = axes[1]
    ax.bar([i - width / 2 for i in x], completion[agents[0]], width, label=agents[0])
    ax.bar([i + width / 2 for i in x], completion[agents[1]], width, label=agents[1])
    ax.set_title("Completion Rate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.legend()

    # Trial note
    flat_counts = [c for agent in agents for c in trials[agent] if c > 0]
    trial_note = ""
    if flat_counts:
        u = set(flat_counts)
        trial_note = f" (n={next(iter(u))} per agent/model)" if len(u) == 1 else " (trials vary)"

    fig.suptitle(f"{task} — Agent Success & Completion{trial_note}")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    outfile = output_dir / f"{task}_agent_comparison_rates.png"
    fig.savefig(outfile, dpi=150)
    print(f"Saved plot to {outfile}")
    if show:
        plt.show()
    plt.close(fig)


def main():
    args = parse_args()
    tasks = discover_tasks(args.tasks_dir)
    if not tasks:
        print(f"No task logs found under {args.tasks_dir}")
        return

    for task_name, logs_dir in tasks:
        files = discover_jsonl(logs_dir)
        if not files:
            print(f"[{task_name}] No JSONL files in {logs_dir}, skipping.")
            continue
        aggregates = aggregate(files)
        if not aggregates:
            print(f"[{task_name}] No valid records aggregated, skipping.")
            continue
        models, agents, success, completion, trials = prepare_series(aggregates)
        task_out = args.output_dir / task_name
        plot_task_bar(task_name, models, agents, success, completion, trials, task_out, args.show)


if __name__ == "__main__":  # pragma: no cover
    main()
