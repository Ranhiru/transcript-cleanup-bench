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


def assertion_evaluator(
    *, output: Any, expected_output: dict[str, Any], **_: Any
) -> list[Evaluation]:
    normalized = str(output if output is not None else "").strip()

    def check(assertion: dict[str, Any]) -> bool:
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

    checked = [
        {"index": index, **assertion, "passed": check(assertion)}
        for index, assertion in enumerate(expected_output["assertions"])
    ]
    failed = [assertion for assertion in checked if not assertion["passed"]]
    evaluations = [
        Evaluation(
            name="pass",
            value=not failed,
            data_type="BOOLEAN",
            comment=f"{len(checked) - len(failed)} of {len(checked)} assertions passed",
            metadata={"failedAssertions": failed},
        )
    ]
    for metric in dict.fromkeys(assertion["metric"] for assertion in checked):
        matching = [assertion for assertion in checked if assertion["metric"] == metric]
        metric_failures = [assertion for assertion in matching if not assertion["passed"]]
        evaluations.append(
            Evaluation(
                name=metric,
                value=(len(matching) - len(metric_failures)) / len(matching),
                data_type="NUMERIC",
                metadata={"failedAssertions": metric_failures},
            )
        )
    return evaluations


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
        max_concurrency=concurrency,
        metadata={
            "model": model["id"],
            "model_label": model["label"],
            "prompt_name": langfuse_prompt.name,
            "prompt_version": langfuse_prompt.version,
            "prompt_label": selection.requested_label,
        },
    )


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
        for model in models:
            for selection in selections:
                result = run_pair(dataset, config, model, selection, concurrency, started_at)
                print(result.format())
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
