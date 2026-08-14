from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langfuse import Evaluation
from langfuse.langchain import CallbackHandler

from .dataset import client

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "benchmark.yaml"


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text())


def render_prompt(path: Path, transcript: str) -> str:
    return path.read_text().replace("{{transcript}}", transcript)


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
            comment="All assertions passed" if not failed else json.dumps(failed, ensure_ascii=False),
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
    prompt: dict[str, Any],
    concurrency: int,
    started_at: str,
):
    sampler = config["sampler"]
    extensions = {
        key: value
        for key, value in {
            "top_k": sampler.get("top_k"),
            "min_p": sampler.get("min_p"),
            "repetition_penalty": sampler.get("repetition_penalty"),
            "chat_template_kwargs": model.get("chat_template_kwargs"),
        }.items()
        if value is not None
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
    prompt_path = REPO / prompt["file"]

    async def task(*, item: Any, **_: Any) -> str:
        rendered = render_prompt(prompt_path, item.input["transcript"])
        response = await llm.ainvoke(
            [{"role": "user", "content": rendered}],
            config={"callbacks": [CallbackHandler()]},
        )
        return str(response.content)

    run_name = f"{started_at}-{model['id']}-{prompt['id']}"
    return dataset.run_experiment(
        name=f"{model['label']} / {prompt['id']}",
        run_name=run_name,
        description="Transcript cleanup benchmark",
        task=task,
        evaluators=[assertion_evaluator],
        max_concurrency=concurrency,
        metadata={
            "model": model["id"],
            "model_label": model["label"],
            "prompt": prompt["id"],
        },
    )


def main() -> None:
    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--prompt", action="append")
    parser.add_argument("--concurrency", type=int)
    args = parser.parse_args()
    config = load_config()
    models = selected(config["models"], args.model)
    prompts = selected(config["prompts"], args.prompt)
    concurrency = args.concurrency or config["concurrency"]
    if concurrency < 1:
        raise SystemExit("concurrency must be at least 1")

    langfuse = client()
    try:
        dataset = filter_cases(langfuse.get_dataset(config["dataset"]), args.case)
        started_at = datetime.now(UTC).strftime("eval-%Y%m%dT%H%M%SZ")
        for model in models:
            for prompt in prompts:
                result = run_pair(dataset, config, model, prompt, concurrency, started_at)
                print(result.format())
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
