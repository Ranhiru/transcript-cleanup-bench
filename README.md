# Transcript Cleanup Bench

Benchmarks local LLM transcript cleanup against an authoritative Langfuse dataset. It also
provides an OpenAI-compatible tracing proxy for [Handy](https://handy.computer/).

```text
Handy → proxy localhost:4000 → oMLX localhost:8000
             └── traces → Langfuse localhost:4001

Langfuse dataset → benchmark runner → oMLX
                 └── experiments and scores → Langfuse
```

### Hardware and server

| | |
|:---|:---|
| machine | MacBook Pro (Mac14,6) |
| chip | Apple M2 Max — 12 CPU cores (8P + 4E), 38 GPU cores |
| memory | 96 GB unified |
| macOS | 15.7.8 (24G824) |
| server | oMLX 0.5.5 (2128), prompt cache disabled |
| engine | mlx 0.32.0, mlx-lm 0.31.3 |
| Langfuse | 4.0.0 |

Sampler settings and model IDs are pinned in `benchmark.yaml`. The benchmark runner calls
oMLX directly; Handy uses the proxy so live traffic is traced without duplicating experiment
traces.

## Models used and defaults

The suite covers three Gemma variants and Qwen3.6 MoE. Qwen uses the `qwen3.5/6(r, general)`
preset with thinking disabled, while Gemma models use the `gemma4` preset.

## Results

<!-- BENCHMARK:START -->

### Leaderboard

Ranked by tests passed. Best result first.

| # | model | prompt | passed | score |
|---:|:---|:---|---:|:---|
| 1 | Qwen 3.6 35B-A3B | v2 | 39/39 | `█████████` 100.0% |
| 2 | Gemma 4 12B QAT | v2 | 38/39 | `█████████` 97.4% |
| 3 | Gemma 4 E2B | v2 | 36/39 | `████████░` 92.3% |
| 4 | Gemma 4 E4B | v2 | 35/39 | `████████░` 89.7% |
| 5 | Gemma 4 12B QAT | v1 | 34/39 | `████████░` 87.2% |
| 6 | Gemma 4 E4B | v1 | 34/39 | `████████░` 87.2% |
| 7 | Qwen 3.6 35B-A3B | v1 | 34/39 | `████████░` 87.2% |
| 8 | Gemma 4 E2B | v1 | 31/39 | `███████░░` 79.5% |

Legacy Promptfoo baseline; it remains for comparison until the first complete Langfuse benchmark is published.

<!-- BENCHMARK:END -->

`make bench` publishes a complete serial 360-execution run. `make report` only rebuilds this
section from `results/summary.json`.

## Setup

Install Docker, `uv`, GNU Make, and an OpenAI-compatible oMLX server exposing the model IDs
in `benchmark.yaml`.

```fish
cp .env.example .env
# Replace every change-me value, then:
make setup
make up
make sync
```

Configure Handy's custom OpenAI provider with base URL `http://localhost:4000/v1`. The proxy
injects `OMLX_API_KEY`; Handy does not need the oMLX credential.

## Run

```fish
make eval                                      # full diagnostic run, concurrency 8
make eval ARGS="--case happy-1 --model 'Gemma 4 E4B' --prompt v2"
make bench                                     # complete serial publishable benchmark
make dataset-export                            # refresh the tracked backup from Langfuse
make dataset-check                             # fail if Langfuse and the backup differ
make report                                    # rebuild README without services
make status
make view
make down
```

Langfuse at `http://localhost:4001` is the dataset editing source of truth. The tracked
`datasets/evaluation-transcript-cleanup.jsonl` file is generated; do not edit it manually.
