# Transcript Cleanup Bench

Benchmarks how effective local LLM models are at transcript clean up, using [promptfoo](https://promptfoo.dev). The goal is consistently compare these models across standardized tasks while improving the prompt

Currently used with [Handy](https://handy.computer/)

### Hardware and server

| | |
|:---|:---|
| machine | MacBook Pro (Mac14,6) |
| chip | Apple M2 Max — 12 CPU cores (8P + 4E), 38 GPU cores |
| memory | 96 GB unified |
| macOS | 15.7.8 (24G824) |
| server | oMLX 0.5.5 (2128), prompt cache disabled |
| engine | mlx 0.32.0, mlx-lm 0.31.3 |
| promptfoo | 0.122.0 |

Sampler settings are pinned per provider in `promptfooconfig.yaml` rather than taken
from the OMLX defaults, so the settings that produced these numbers are visible in the
repo. Any value not sent by promptfoo falls back to whatever the server defaults to,
which is invisible in the results — so they are all set explicitly.

## Models used and defaults

Currently testing the Gemma family and Qwen3.6 MoE model that works reasonably fast. Latency is not measured yet because 
promptfoo's recorded latency_ms is far too low to be real. Also OMLX has a cache that can skew results during repeated runs with the same prompt.

All the models used here have thinking turned off from the server. Apart from hardcoded values in the promptfoo config, all settings are taken from general OMLX presets for each model family

Qwen3.6 MoE model use the `qwen3.5/6(r, general)` preset, while Gemma models use the `gemma4` preset.

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

Full per-test results: [`results/latest.csv`](results/latest.csv) (312 rows). Per-category scores: [`results/summary.json`](results/summary.json). Eval id `eval-grE-2026-08-05T02:35:39`.

<!-- BENCHMARK:END -->

Regenerate with `make bench` (runs the suite) or `make report` (rebuilds the leaderboard
from the published run without re-running anything). Everything between the markers above
is generated — edit `scripts/report.py`, not the table.

`make report` stays pinned to the eval recorded in `results/summary.json`, so a filtered
`make eval` cannot quietly replace the benchmark with a handful of rows. `make bench`
moves the pin.

## Setup

Needs Node.js 20+, promptfoo and GNU Make. 

```fish
make install    # pre-download the pinned promptfoo into the npx cache
make version    # confirm which version is actually being run
```

If you would rather have the binary on your `PATH`, install the *same* version the
`Makefile` pins so results stay comparable:

Also needs a local/remote OpenAI compatible server serving the exact model IDs listed in `promptfooconfig.yaml`.
This repo uses [OMLX](https://omlx.ai)

## Run

```fish
make eval    # run every test against the prompts
make view    # open the results grid in a browser
make         # list the available targets
```
