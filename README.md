# promptfoo arm

Evaluates the transcript-cleaner prompt with [promptfoo](https://promptfoo.dev).

The prompt takes a raw dictation transcript and returns a cleaned version — fixing mishears, removing filler words, formatting numbers without adding commentary or answering anything the transcript happens to ask.

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

Run serialised (`maxConcurrency: 1`) and uncached, with every sampler value pinned in `promptfooconfig.yaml`. Greedy decoding, so re-running should reproduce these numbers.

### By category

| model | prompt | happy-path | spelling | mishears-listed | mishears-unlisted | numbers-symbols | preservation | no-commentary |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|
| Qwen 3.6 35B-A3B | v2 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Gemma 4 12B QAT | v2 | 100.0% | 100.0% | 100.0% | 91.7% | 100.0% | 88.9% | 100.0% |
| Gemma 4 E2B | v2 | 100.0% | 100.0% | 100.0% | 75.0% | 100.0% | 100.0% | 100.0% |
| Gemma 4 E4B | v2 | 100.0% | 100.0% | 100.0% | 91.7% | 79.2% | 100.0% | 100.0% |
| Gemma 4 12B QAT | v1 | 100.0% | 100.0% | 57.1% | 83.3% | 100.0% | 66.7% | 100.0% |
| Gemma 4 E4B | v1 | 100.0% | 100.0% | 100.0% | 83.3% | 79.2% | 100.0% | 100.0% |
| Qwen 3.6 35B-A3B | v1 | 100.0% | 100.0% | 71.4% | 83.3% | 95.8% | 77.8% | 100.0% |
| Gemma 4 E2B | v1 | 100.0% | 100.0% | 85.7% | 58.3% | 87.5% | 77.8% | 100.0% |

Full per-test results: [`results/latest.csv`](results/latest.csv) (312 rows). Aggregates: [`results/summary.json`](results/summary.json). Eval id `eval-grE-2026-08-05T02:35:39`.

<!-- BENCHMARK:END -->

Regenerate with `make bench` (runs the suite) or `make report` (rebuilds the tables from
the published run without re-running anything). Everything between the markers above is
generated — edit `scripts/report.py`, not the tables.

`make report` stays pinned to the eval recorded in `results/summary.json`, so a filtered
`make eval` cannot quietly replace the benchmark with a handful of rows. `make bench`
moves the pin.

### Hardware and server

| | |
|:---|:---|
| machine | MacBook Pro (Mac14,6) |
| chip | Apple M2 Max — 12 CPU cores (8P + 4E), 38 GPU cores |
| memory | 96 GB unified |
| macOS | 15.7.8 (24G824) |
| server | oMLX 0.5.5 (2128), prompt cache disabled |
| engine | mlx 0.32.0, mlx-lm 0.31.3 |
| promptfoo | 0.122.0 (pinned in the `Makefile`) |

All four models are 4-bit quantised and served from a single local oMLX instance.

Sampler settings are pinned per provider in `promptfooconfig.yaml` rather than taken
from the OMLX defaults, so the settings that produced these numbers are visible in the
repo. Any value not sent by promptfoo falls back to whatever the server defaults to,
which is invisible in the results — so they are all set explicitly.

## Setup

Needs Node.js 20+ (for `npx`) and GNU Make. Everything else comes from the pinned
promptfoo version in the `Makefile` — there is nothing to `npm install` in this repo.

```fish
make install    # pre-download the pinned promptfoo into the npx cache
make version    # confirm which version is actually being run
```

If you would rather have the binary on your `PATH`, install the *same* version the
`Makefile` pins so results stay comparable:

```fish
npm install -g promptfoo@0.122.0
# or
brew install promptfoo    # tracks latest — check `promptfoo --version` matches
```

Also needs a local/remote OpenAI compatible server serving the exact model IDs listed in `promptfooconfig.yaml`.
Currently using OMLX

```fish
set -gx OMLX_API_KEY 123456
```

## Run

```fish
make eval    # run every test against the prompts
make view    # open the results grid in a browser
make         # list the available targets
```

Extra flags go through `ARGS`:

```fish
make eval ARGS="--filter-pattern mishears"
```

The version is pinned in the `Makefile` (`PROMPTFOO_VERSION`) rather than using
`promptfoo@latest`, so a new promptfoo release can't silently change eval results.
Bump it deliberately and re-run the full suite.

## Files

- `Makefile` — entry point; pins the promptfoo version
- `promptfooconfig.yaml` — the whole eval: prompts, providers, and tests
- `prompts/v1.txt` — baseline prompt, with `{{transcript}}` as the input placeholder
- `prompts/v2.txt` — revised prompt, compared against v1 in every run
- `tests/*.yaml` — one file per case category, picked up by a glob

Prompts are listed one-by-one in `promptfooconfig.yaml` instead of globbed like the
tests. The `v1`/`v2` labels appear in every result and are what the metric queries
group on, and a glob both drops them for filenames and orders by the filesystem —
which put v2 in the first column. Adding a prompt means adding a line to the config.

Both prompts come from the `transcription-prompt-eval` repo, where they are `prompt.txt`
(sha `3f57dab2`) and `prompt-v9.txt` (sha `e4fca361`). The v1/v2 numbering is local to
this repo.
