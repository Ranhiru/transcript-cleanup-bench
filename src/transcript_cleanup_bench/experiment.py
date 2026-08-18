from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langfuse import Evaluation
from langfuse.langchain import CallbackHandler
from langfuse.model import ChatPromptClient

from .config import DATASET_NAME, EXTRA_BODY_OPTIONS, REPO, langfuse_client, load_env
from .prompts import prompt_label, prompt_name, resolve

CONFIG = REPO / "benchmark.yaml"


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text())


def selected(
    values: list[dict[str, Any]], requested: list[str] | None
) -> list[dict[str, Any]]:
    if not requested:
        return values
    wanted = set(requested)
    chosen = [value for value in values if value["id"] in wanted or value.get("label") in wanted]
    missing = wanted - {value["id"] for value in chosen} - {value.get("label") for value in chosen}
    if missing:
        raise SystemExit("unknown filter values: " + ", ".join(sorted(missing)))
    return chosen


@dataclass(frozen=True)
class PromptSelection:
    prompt: ChatPromptClient
    requested_label: str | None


def resolve_prompt_selections(
    langfuse: Any,
    name: str,
    labels: list[str] | None,
    versions: list[int] | None,
) -> list[PromptSelection]:
    requested_labels = list(dict.fromkeys(labels or ([prompt_label()] if not versions else [])))
    requested_versions = list(dict.fromkeys(versions or []))
    selections: list[PromptSelection] = []
    seen_versions: set[int] = set()

    for label in requested_labels:
        resolved = resolve(langfuse, name=name, label=label)
        if resolved.version not in seen_versions:
            selections.append(PromptSelection(resolved, label))
            seen_versions.add(resolved.version)
    for version in requested_versions:
        resolved = resolve(langfuse, name=name, version=version)
        if resolved.version not in seen_versions:
            selections.append(PromptSelection(resolved, None))
            seen_versions.add(resolved.version)
    return selections


def check_assertions(output: Any, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each assertion with its position and whether it held."""
    normalized = str(output if output is not None else "").strip()

    def holds(assertion: dict[str, Any]) -> bool:
        kind = assertion["type"]
        value = assertion["value"]
        if kind == "equals":
            return normalized == value
        if kind == "contains":
            return value in normalized
        if kind == "regex":
            return re.search(value, normalized) is not None
        if kind == "not-regex":
            return re.search(value, normalized) is None
        if kind == "not-icontains":
            return value.lower() not in normalized.lower()
        if kind == "not-icontains-any":
            folded = normalized.lower()
            return not any(candidate.lower() in folded for candidate in value)
        raise ValueError(f"Unsupported assertion type: {kind}")

    return [
        {"index": index, **assertion, "passed": holds(assertion)}
        for index, assertion in enumerate(assertions)
    ]


def assertion_evaluator(
    *, output: Any, expected_output: dict[str, Any], **_: Any
) -> list[Evaluation]:
    """Score one item. Both scores are defined for every item so runs stay comparable."""
    checked = check_assertions(output, expected_output["assertions"])
    failed = [assertion for assertion in checked if not assertion["passed"]]
    held = len(checked) - len(failed)
    summary = f"{held} of {len(checked)} assertions passed"
    return [
        Evaluation(
            name="pass",
            value=not failed,
            data_type="BOOLEAN",
            comment=summary,
            metadata={"failedAssertions": failed},
        ),
        Evaluation(
            name="assertion_rate",
            value=held / len(checked) if checked else 1.0,
            data_type="NUMERIC",
            comment=summary,
            metadata={"failedAssertions": failed},
        ),
    ]


def facet_pass_rates(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    """Aggregate pass rates over dataset facets, attached to the run rather than an item.

    Categories live in dataset item metadata, so each rate carries its own denominator
    instead of being averaged over whichever items happened to define a metric.
    """
    groups: dict[str, list[bool]] = {}
    for result in item_results:
        outcome = next(
            (item.value for item in result.evaluations if item.name == "pass"), None
        )
        if outcome is None:
            continue
        metadata = getattr(result.item, "metadata", None) or {}
        facets = ["pass_rate"]
        if category := metadata.get("category"):
            facets.append(f"pass_rate:{category}")
        facets.append(
            "pass_rate:negative-control"
            if metadata.get("negative_control")
            else "pass_rate:positive-case"
        )
        for facet in facets:
            groups.setdefault(facet, []).append(bool(outcome))

    return [
        Evaluation(
            name=facet,
            value=sum(outcomes) / len(outcomes),
            data_type="NUMERIC",
            comment=f"{sum(outcomes)} of {len(outcomes)} items passed",
            metadata={"items": len(outcomes)},
        )
        for facet, outcomes in sorted(groups.items())
    ]


def filter_cases(dataset: Any, cases: list[str] | None) -> Any:
    if not cases:
        return dataset
    wanted = set(cases)
    dataset.items = [
        item
        for item in dataset.items
        if item.id in wanted or (item.metadata or {}).get("legacy_identifier") in wanted
    ]
    if not dataset.items:
        raise SystemExit("case filter matched no dataset items")
    return dataset


def run_pair(
    dataset: Any,
    config: dict[str, Any],
    model: dict[str, Any],
    selection: PromptSelection,
    concurrency: int,
    started_at: str,
):
    sampler = config["sampler"]
    available = {**sampler, **model}
    extensions = {
        key: available[key]
        for key in EXTRA_BODY_OPTIONS
        if available.get(key) is not None
    }
    llm = ChatOpenAI(
        model=model["id"],
        base_url=os.environ["OPENAI_API_HOST"],
        api_key=os.environ["OPENAI_API_KEY"],
        temperature=sampler["temperature"],
        max_tokens=sampler["max_tokens"],
        top_p=sampler["top_p"],
        presence_penalty=sampler["presence_penalty"],
        frequency_penalty=sampler["frequency_penalty"],
        extra_body=extensions,
    )
    langfuse_prompt = selection.prompt
    template = ChatPromptTemplate.from_messages(langfuse_prompt.get_langchain_prompt())
    template.metadata = {"langfuse_prompt": langfuse_prompt}
    chain = template | llm

    async def task(*, item: Any, **_: Any) -> str:
        response = await chain.ainvoke(
            {"transcript": item.input["transcript"]},
            config={"callbacks": [CallbackHandler()]},
        )
        return str(response.content)

    selector = selection.requested_label or f"version-{langfuse_prompt.version}"
    run_name = (
        f"{started_at}-{model['id']}-{langfuse_prompt.name}-"
        f"v{langfuse_prompt.version}-{selector}"
    )
    return dataset.run_experiment(
        name=(
            f"{model['label']} / {langfuse_prompt.name} "
            f"v{langfuse_prompt.version} ({selector})"
        ),
        run_name=run_name,
        description="Transcript cleanup benchmark",
        task=task,
        evaluators=[assertion_evaluator],
        run_evaluators=[facet_pass_rates],
        max_concurrency=concurrency,
        metadata={
            "model": model["id"],
            "model_label": model["label"],
            "prompt_name": langfuse_prompt.name,
            "prompt_version": langfuse_prompt.version,
            "prompt_label": selection.requested_label,
        },
    )


def leaderboard(rows: list[tuple[dict[str, Any], Any]]) -> str:
    """Rank models by pass rate. Langfuse orders experiments by time and cannot sort by score.

    Facets are rows and models are columns, so adding a category grows the table
    downwards rather than past the width of a terminal.
    """
    def rate(result: Any, name: str) -> float | None:
        return next(
            (item.value for item in result.run_evaluations if item.name == name), None
        )

    def mean_assertion_rate(result: Any) -> float:
        values = [
            score.value
            for item in result.item_results
            for score in item.evaluations
            if score.name == "assertion_rate"
        ]
        return sum(values) / len(values) if values else 0.0

    ranked = sorted(
        rows,
        key=lambda row: (rate(row[1], "pass_rate") or 0, mean_assertion_rate(row[1])),
        reverse=True,
    )
    facets = sorted(
        {
            item.name
            for _, result in rows
            for item in result.run_evaluations
            if item.name != "pass_rate"
        }
    )
    measures: list[tuple[str, Any]] = [
        ("pass_rate", lambda result: rate(result, "pass_rate")),
        ("assertion_rate", mean_assertion_rate),
    ]
    measures += [
        (facet.removeprefix("pass_rate:"), lambda result, facet=facet: rate(result, facet))
        for facet in facets
    ]

    label = max(len(name) for name, _ in measures) + 2
    columns = [model["label"] for model, _ in ranked]
    cell = max(max(len(name) for name in columns), 7) + 2
    lines = [
        "",
        "Leaderboard — ranked by pass rate, then assertion rate",
        "",
        "measure".ljust(label) + "".join(name.rjust(cell) for name in columns),
        "-" * (label + cell * len(columns)),
    ]
    for name, measure in measures:
        values = [measure(result) for _, result in ranked]
        lines.append(
            name.ljust(label)
            + "".join(("-" if v is None else f"{v:.3f}").rjust(cell) for v in values)
        )
    return "\n".join(lines)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--prompt-label", action="append")
    parser.add_argument("--prompt-version", action="append", type=int)
    parser.add_argument("--concurrency", type=int)
    args = parser.parse_args()
    config = load_config()
    models = selected(config["models"], args.model)
    concurrency = args.concurrency or config["concurrency"]
    if concurrency < 1:
        raise SystemExit("concurrency must be at least 1")

    langfuse = langfuse_client()
    try:
        dataset = filter_cases(langfuse.get_dataset(DATASET_NAME), args.case)
        started_at = datetime.now(UTC).strftime("eval-%Y%m%dT%H%M%SZ")
        selections = resolve_prompt_selections(
            langfuse,
            prompt_name(),
            args.prompt_label,
            args.prompt_version,
        )
        rows = []
        for model in models:
            for selection in selections:
                result = run_pair(dataset, config, model, selection, concurrency, started_at)
                print(result.format())
                rows.append((model, result))
        if len(rows) > 1:
            print(leaderboard(rows))
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
