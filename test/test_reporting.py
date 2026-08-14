from transcript_cleanup_bench.reporting import render


def test_legacy_summary_is_marked() -> None:
    block = render(
        {
            "legacy": True,
            "leaderboard": [
                {"model": "M", "prompt": "v1", "passed": 1, "total": 2, "pass_pct": 50.0}
            ],
        }
    )
    assert "Legacy Promptfoo baseline" in block


def test_langfuse_summary_records_dataset_reproducibility() -> None:
    block = render(
        {
            "results": 360,
            "dataset_version": "2026-08-14T00:00:00+00:00",
            "snapshot_sha256": "abc",
            "leaderboard": [
                {"model": "M", "prompt": "v1", "passed": 45, "total": 45, "pass_pct": 100.0}
            ],
        }
    )
    assert "360 rows" in block
    assert "2026-08-14T00:00:00+00:00" in block
    assert "Snapshot SHA-256 `abc`" in block
