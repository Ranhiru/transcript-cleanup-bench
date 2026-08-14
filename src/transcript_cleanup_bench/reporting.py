from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
SUMMARY = REPO / "results" / "summary.json"
START = "<!-- BENCHMARK:START -->"
END = "<!-- BENCHMARK:END -->"
BAR_WIDTH = 9


def bar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def render(summary: dict[str, Any]) -> str:
    lines = ["### Leaderboard", "", "Ranked by tests passed. Best result first.", ""]
    lines += [
        "| # | model | prompt | passed | score |",
        "|---:|:---|:---|---:|:---|",
    ]
    for rank, entry in enumerate(summary["leaderboard"], 1):
        lines.append(
            f"| {rank} | {entry['model']} | {entry['prompt']} | "
            f"{entry['passed']}/{entry['total']} | `{bar(entry['pass_pct'])}` {entry['pass_pct']}% |"
        )
    lines.append("")
    if summary.get("legacy"):
        lines.append(
            "Legacy Promptfoo baseline; it remains for comparison until the first complete "
            "Langfuse benchmark is published."
        )
    else:
        lines.append(
            " ".join(
                [
                    f"Full per-test results: [`results/latest.csv`](results/latest.csv) ({summary['results']} rows).",
                    "Per-category scores: [`results/summary.json`](results/summary.json).",
                    f"Dataset version `{summary['dataset_version']}`.",
                    f"Snapshot SHA-256 `{summary['snapshot_sha256']}`.",
                ]
            )
        )
    return "\n".join(lines)


def publish(summary: dict[str, Any]) -> None:
    text = README.read_text()
    if START not in text or END not in text:
        raise SystemExit(f"README.md is missing the {START} / {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{START}\n\n{render(summary)}\n\n{END}{tail}")


def main() -> None:
    publish(json.loads(SUMMARY.read_text()))
    print("README.md updated from results/summary.json")

