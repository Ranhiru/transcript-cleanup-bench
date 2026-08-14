from __future__ import annotations

import yaml


def test_compose_ports_storage_and_evaluator_dispatcher() -> None:
    config = yaml.safe_load(open("compose.yaml"))
    services = config["services"]
    assert services["proxy"]["ports"] == ["127.0.0.1:4000:4000"]
    assert services["langfuse-web"]["ports"] == ["127.0.0.1:4001:3000"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["clickhouse"]
    assert "ports" not in services["redis"]
    assert all(port.startswith("127.0.0.1:") for port in services["minio"]["ports"])
    assert services["langfuse-web"]["image"].endswith(":4.0.0")
    assert services["langfuse-worker"]["environment"]["LANGFUSE_CODE_EVAL_DISPATCHER"] == "insecure-local"
    assert services["langfuse-worker"]["environment"][
        "QUEUE_CONSUMER_CODE_EVAL_EXECUTION_QUEUE_IS_ENABLED"
    ] == "true"
    assert services["langfuse-web"]["environment"]["TELEMETRY_ENABLED"] == "false"

