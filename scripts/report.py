#!/usr/bin/env python3
# pyright: reportAny=false
# ^ sqlite3.Row indexing is untyped; values are coerced at the boundary in fetch()
#   and everything downstream works on the dataclasses below.
"""Generate the benchmark summary in README.md from promptfoo's result database.

Reads the most recent eval (or --eval-id) out of ~/.promptfoo/promptfoo.db and
rewrites the block between the BENCHMARK markers in README.md. Also writes
results/summary.json so the published numbers can be audited without the
6.2MB promptfoo export or a local database.

Stdlib only, by design — this repo has no package manifest to install from.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

REPO = Path(__file__).resolve().parent.parent
DB = Path.home() / ".promptfoo" / "promptfoo.db"
README = REPO / "README.md"
SUMMARY = REPO / "results" / "summary.json"

START = "<!-- BENCHMARK:START -->"
END = "<!-- BENCHMARK:END -->"

BAR_WIDTH = 9


@dataclass(frozen=True)
class Result:
    """One promptfoo result row: a single test against one model and one prompt."""

    model: str
    prompt: str
    success: bool
    metrics: dict[str, float]


@dataclass
class Entry:
    """Aggregate for one (model, prompt) pair — a leaderboard row."""

    model: str
    prompt: str
    passed: int
    total: int
    pass_pct: float
    metrics: dict[str, float] = field(default_factory=dict)


def bar(pct: float) -> str:
    """Unicode meter. Renders identically everywhere and diffs one line per row."""
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def short_label(raw: str) -> str:
    """promptfoo stores labels as "v1: prompts/v1.txt: <entire prompt body>"."""
    return raw.split(":", 1)[0].strip() if ":" in raw else raw.strip()


def as_dict(blob: str) -> dict[str, object]:
    parsed: object = json.loads(blob or "{}")
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}


def json_label(blob: str) -> str:
    label = as_dict(blob).get("label")
    return str(label) if label is not None else "?"


def json_scores(blob: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in as_dict(blob).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(key)] = float(value)
    return out


def pinned_eval_id() -> str | None:
    """The eval currently published in the README, per results/summary.json.

    The README is pinned to a specific eval rather than to whatever ran most
    recently, so an ad-hoc `make eval` — a filtered diagnostic run, say — cannot
    quietly replace the published benchmark with three rows. `make bench` passes
    --latest to advance the pin deliberately.
    """
    if not SUMMARY.exists():
        return None
    value = as_dict(SUMMARY.read_text()).get("eval_id")
    return str(value) if value else None


def fetch(requested_id: str | None) -> tuple[str, list[Result]]:
    if not DB.exists():
        raise SystemExit(f"no promptfoo database at {DB} — run `make bench` first")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    if requested_id is not None:
        eval_id = requested_id
    else:
        latest = con.execute("select id from evals order by created_at desc limit 1").fetchone()
        if latest is None:
            raise SystemExit("no evals in the database — run `make bench` first")
        eval_id = str(latest["id"])

    raw = con.execute(
        """
        select prompt, provider, success, named_scores
        from eval_results where eval_id = ? order by created_at, rowid
        """,
        (eval_id,),
    ).fetchall()
    con.close()

    if not raw:
        raise SystemExit(f"eval {eval_id} has no results")

    results: list[Result] = []
    for row in raw:
        results.append(
            Result(
                model=json_label(str(row["provider"])),
                prompt=short_label(json_label(str(row["prompt"]))),
                success=bool(row["success"]),
                metrics=json_scores(str(row["named_scores"])),
            )
        )
    return eval_id, results


def aggregate(results: list[Result]) -> list[Entry]:
    """One Entry per (model, prompt) — a leaderboard row.

    Per-category scores are kept on each Entry for results/summary.json, but the
    README publishes only the leaderboard.
    """
    groups: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in results:
        groups[(r.model, r.prompt)].append(r)

    entries: list[Entry] = []
    for (model, prompt), rows in groups.items():
        passed = sum(1 for r in rows if r.success)
        scores: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            for key, value in r.metrics.items():
                scores[key].append(value)

        entries.append(
            Entry(
                model=model,
                prompt=prompt,
                passed=passed,
                total=len(rows),
                pass_pct=round(100 * passed / len(rows), 1),
                metrics={
                    key: round(100 * statistics.fmean(vals), 1)
                    for key, vals in sorted(scores.items())
                },
            )
        )

    # Winner = most tests passed. Model and prompt break ties so the ordering is
    # stable between runs and the README diff stays readable.
    entries.sort(key=lambda e: (-e.passed, e.model, e.prompt))
    return entries


def md_table(rows: list[list[str]], align: list[str]) -> list[str]:
    sep = {"l": ":---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(sep[a] for a in align) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out


def render(eval_id: str, entries: list[Entry], total: int) -> str:
    lines: list[str] = ["### Leaderboard", ""]
    lines.append("Ranked by tests passed. Best result first.")
    lines.append("")

    board = [["#", "model", "prompt", "passed", "score"]]
    for i, e in enumerate(entries, 1):
        board.append(
            [
                str(i),
                e.model,
                e.prompt,
                f"{e.passed}/{e.total}",
                f"`{bar(e.pass_pct)}` {e.pass_pct}%",
            ]
        )
    lines += md_table(board, ["r", "l", "l", "r", "l"])
    footer = " ".join(
        [
            f"Full per-test results: [`results/latest.csv`](results/latest.csv) ({total} rows).",
            "Per-category scores: [`results/summary.json`](results/summary.json).",
            f"Eval id `{eval_id}`.",
        ]
    )
    lines += ["", footer]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--eval-id", help="report on this specific eval")
    _ = ap.add_argument(
        "--latest",
        action="store_true",
        help="advance to the newest eval in the database (what `make bench` uses)",
    )
    _ = ap.add_argument("--stdout", action="store_true", help="print instead of editing README")
    args = ap.parse_args()

    # Default: stay on the eval the README already publishes.
    requested = args.eval_id or (None if args.latest else pinned_eval_id())
    if requested is not None and not args.eval_id:
        print(f"pinned to {requested} (--latest to advance)")

    eval_id, results = fetch(requested)
    entries = aggregate(results)
    block = render(eval_id, entries, len(results))

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    _ = SUMMARY.write_text(
        json.dumps(
            {
                "eval_id": eval_id,
                "results": len(results),
                "leaderboard": [asdict(e) for e in entries],
            },
            indent=2,
        )
        + "\n"
    )

    if args.stdout:
        print(block)
        return

    text = README.read_text()
    if START not in text or END not in text:
        raise SystemExit(f"README.md is missing the {START} / {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    _ = README.write_text(f"{head}{START}\n\n{block}\n\n{END}{tail}")
    print(f"README.md updated from {eval_id} ({len(results)} results)")
    print(f"{SUMMARY.relative_to(REPO)} written")


if __name__ == "__main__":
    main()
