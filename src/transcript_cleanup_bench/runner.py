from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from . import GENERATION_NAME
from .dataset import client, export, snapshot_hash
from .env import load_env
from .reporting import publish

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "benchmark.yaml"
CSV_PATH = REPO / "results" / "latest.csv"
SUMMARY_PATH = REPO / "results" / "summary.json"


@dataclass
class Execution:
    experiment_id: str
    run_name: str
    observation_id: str
    trace_id: str
    item_id: str
    legacy_identifier: str
    model_id: str
    model: str
    prompt: str
    output: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    expected_score_names: tuple[str, ...]
    scores: dict[str, float | bool]


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text())


def render_prompt(path: Path, transcript: str) -> str:
    return path.read_text().replace("{{transcript}}", transcript)


def available_models(config: dict[str, Any]) -> set[str]:
    headers = {"Authorization": f"Bearer {os.environ['OMLX_API_KEY']}"}
    with httpx.Client(timeout=10) as http:
        response = http.get(f"{config['omlx_url'].rstrip('/')}/models", headers=headers)
        response.raise_for_status()
    data = response.json().get("data", [])
    return {str(model["id"]) for model in data if isinstance(model, dict) and "id" in model}


def selected(values: list[dict[str, Any]], requested: list[str] | None) -> list[dict[str, Any]]:
    if not requested:
        return values
    wanted = set(requested)
    chosen = [value for value in values if value["id"] in wanted or value.get("label") in wanted]
    missing = wanted - {value["id"] for value in chosen} - {value.get("label") for value in chosen}
    if missing:
        raise SystemExit("unknown filter values: " + ", ".join(sorted(missing)))
    return chosen


def score_pages(langfuse, experiment_id: str) -> list[Any]:
    cursor = None
    scores: list[Any] = []
    while True:
        page = langfuse.api.scores_v3.get_many_v3(
            experiment_id=experiment_id,
            limit=100,
            cursor=cursor,
        )
        scores.extend(page.data)
        cursor = page.meta.cursor
        if cursor is None:
            return scores


def wait_for_scores(langfuse, executions: list[Execution], timeout: int) -> None:
    expected_ids = {execution.observation_id for execution in executions}
    deadline = time.monotonic() + timeout
    by_observation: dict[str, dict[str, float | bool]] = {}
    complete: set[str] = set()
    experiment_ids = sorted({execution.experiment_id for execution in executions})
    while time.monotonic() < deadline:
        by_observation.clear()
        for experiment_id in experiment_ids:
            for score in score_pages(langfuse, experiment_id):
                subject = score.subject
                if subject is None or getattr(subject, "kind", None) != "observation":
                    continue
                by_observation.setdefault(subject.id, {})[score.name] = score.value
        complete = {
            execution.observation_id
            for execution in executions
            if set(execution.expected_score_names)
            <= set(by_observation.get(execution.observation_id, {}))
        }
        if expected_ids <= complete:
            for execution in executions:
                execution.scores = by_observation[execution.observation_id]
            return
        time.sleep(2)
    missing = expected_ids - complete
    raise SystemExit(f"timed out waiting for evaluator scores ({len(missing)} executions missing)")


def run_pair(
    langfuse,
    dataset,
    config: dict[str, Any],
    model: dict[str, Any],
    prompt: dict[str, Any],
    concurrency: int,
    version: datetime,
    digest: str,
    benchmark_id: str,
) -> list[Execution]:
    executions: list[Execution] = []
    parameters = {**config["sampler"]}
    if model.get("chat_template_kwargs") is not None:
        parameters["chat_template_kwargs"] = model["chat_template_kwargs"]
    run_name = f"{benchmark_id}-{model['id']}-{prompt['id']}"

    async def run_all() -> None:
        semaphore = asyncio.Semaphore(concurrency)
        headers = {"Authorization": f"Bearer {os.environ['OMLX_API_KEY']}"}
        run_metadata = {
            "model": model["id"],
            "prompt": prompt["id"],
            "dataset_version": version.isoformat(),
            "snapshot_sha256": digest,
        }

        async with httpx.AsyncClient(timeout=None) as http:
            async def execute(item) -> None:
                async with semaphore:
                    rendered = render_prompt(REPO / prompt["file"], item.input["transcript"])
                    body = {
                        "model": model["id"],
                        "messages": [{"role": "user", "content": rendered}],
                        **parameters,
                    }
                    generation = langfuse.start_observation(
                        name=GENERATION_NAME,
                        as_type="generation",
                        input=body["messages"],
                        model=model["id"],
                        model_parameters=parameters,
                        metadata={"model_label": model["label"], **run_metadata},
                    )
                    run_item = await asyncio.to_thread(
                        langfuse.api.dataset_run_items.create,
                        run_name=run_name,
                        run_description=f"{model['label']} / {prompt['id']}",
                        metadata=run_metadata,
                        dataset_item_id=item.id,
                        trace_id=generation.trace_id,
                        observation_id=generation.id,
                        dataset_version=version,
                    )
                    started = time.monotonic()
                    try:
                        response = await http.post(
                            f"{config['omlx_url'].rstrip('/')}/chat/completions",
                            headers=headers,
                            json=body,
                        )
                        response.raise_for_status()
                        payload = response.json()
                        choice = payload["choices"][0]
                        output = choice["message"]["content"]
                        usage = payload.get("usage") or {}
                        elapsed = round((time.monotonic() - started) * 1000, 3)
                        generation.update(
                            output=output,
                            usage_details=usage,
                            metadata={
                                "latency_ms": elapsed,
                                "finish_reason": choice.get("finish_reason"),
                                **run_metadata,
                            },
                        )
                        executions.append(
                            Execution(
                                experiment_id=run_item.dataset_run_id,
                                run_name=run_name,
                                observation_id=generation.id,
                                trace_id=generation.trace_id,
                                item_id=item.id,
                                legacy_identifier=item.metadata["legacy_identifier"],
                                model_id=model["id"],
                                model=model["label"],
                                prompt=prompt["id"],
                                output=output,
                                latency_ms=elapsed,
                                prompt_tokens=usage.get("prompt_tokens"),
                                completion_tokens=usage.get("completion_tokens"),
                                total_tokens=usage.get("total_tokens"),
                                expected_score_names=tuple(
                                    sorted(
                                        {"pass"}
                                        | {
                                            assertion["metric"]
                                            for assertion in item.expected_output["assertions"]
                                        }
                                    )
                                ),
                                scores={},
                            )
                        )
                    except Exception as error:
                        generation.update(level="ERROR", status_message=str(error))
                        raise
                    finally:
                        generation.end()

            await asyncio.gather(*(execute(item) for item in dataset.items))

    asyncio.run(run_all())
    if len({execution.experiment_id for execution in executions}) != 1:
        raise RuntimeError(f"Langfuse created inconsistent experiment IDs for {run_name}")
    return executions


def write_artifacts(
    executions: list[Execution], benchmark_id: str, version: datetime, digest: str
) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        field
        for field in asdict(executions[0])
        if field not in {"scores", "expected_score_names"}
    ] + ["pass", "scores"]
    with CSV_PATH.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for execution in sorted(executions, key=lambda row: (row.model, row.prompt, row.item_id)):
            row = asdict(execution)
            scores = row.pop("scores")
            row.pop("expected_score_names")
            row["pass"] = scores.get("pass")
            row["scores"] = json.dumps(scores, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)

    groups: dict[tuple[str, str], list[Execution]] = {}
    for execution in executions:
        groups.setdefault((execution.model, execution.prompt), []).append(execution)
    leaderboard = []
    for (model, prompt), rows in groups.items():
        passed = sum(execution.scores.get("pass") is True for execution in rows)
        metrics = sorted({name for row in rows for name in row.scores if name != "pass"})
        leaderboard.append(
            {
                "model": model,
                "prompt": prompt,
                "passed": passed,
                "total": len(rows),
                "pass_pct": round(100 * passed / len(rows), 1),
                "metrics": {
                    name: round(
                        100 * sum(float(row.scores[name]) for row in rows if name in row.scores)
                        / sum(name in row.scores for row in rows),
                        1,
                    )
                    for name in metrics
                },
            }
        )
    leaderboard.sort(key=lambda row: (-row["passed"], row["model"], row["prompt"]))
    summary = {
        "benchmark_id": benchmark_id,
        "dataset": "evaluation/transcript-cleanup",
        "dataset_version": version.isoformat(),
        "snapshot_sha256": digest,
        "results": len(executions),
        "leaderboard": leaderboard,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    publish(summary)


def main() -> None:
    load_env(REPO / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--prompt", action="append")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.publish and (args.case or args.model or args.prompt or args.concurrency not in {None, 1}):
        raise SystemExit("publishable benchmarks reject filters and require concurrency 1")
    models = selected(config["models"], args.model)
    prompts = selected(config["prompts"], args.prompt)
    concurrency = args.concurrency or (config["publish_concurrency"] if args.publish else config["concurrency"])
    missing_models = {model["id"] for model in models} - available_models(config)
    if missing_models:
        raise SystemExit("oMLX is missing configured models: " + ", ".join(sorted(missing_models)))

    langfuse = client()
    try:
        version, digest = export(langfuse) if args.publish else (datetime.now(UTC), snapshot_hash())
        dataset = langfuse.get_dataset(config["dataset"], version=version)
        if args.case:
            wanted = set(args.case)
            dataset.items = [
                item
                for item in dataset.items
                if item.id in wanted or item.metadata.get("legacy_identifier") in wanted
            ]
            if not dataset.items:
                raise SystemExit("case filter matched no dataset items")
        expected = len(models) * len(prompts) * len(dataset.items)
        if args.publish and expected != 360:
            raise SystemExit(f"publishable benchmark requires 360 executions, got {expected}")
        benchmark_id = datetime.now(UTC).strftime("bench-%Y%m%dT%H%M%SZ")
        executions: list[Execution] = []
        for model in models:
            for prompt in prompts:
                executions.extend(
                    run_pair(
                        langfuse,
                        dataset,
                        config,
                        model,
                        prompt,
                        concurrency,
                        version,
                        digest,
                        benchmark_id,
                    )
                )
        if len(executions) != expected:
            raise SystemExit(f"incomplete experiment matrix: expected {expected}, got {len(executions)}")
        langfuse.flush()
        wait_for_scores(langfuse, executions, int(config["score_timeout_seconds"]))
        if args.publish:
            write_artifacts(executions, benchmark_id, version, digest)
        print(f"completed {len(executions)} scored executions")
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
