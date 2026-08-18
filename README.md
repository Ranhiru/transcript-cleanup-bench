# Transcript Cleanup Bench

Benchmarks local LLM transcript cleanup with Langfuse experiments. It also provides an
OpenAI-compatible tracing proxy for [Handy](https://handy.computer/).

```text
Handy → proxy localhost:4000 → OpenAI-compatible API
             └── traces → Langfuse localhost:4001

Langfuse prompt + dataset → experiment runner → OpenAI-compatible API
                           └── traces, scores, and comparisons → Langfuse
```

Langfuse owns the prompts, the dataset, and the results. The tracked JSONL dataset and prompt
files only seed a fresh project.

## Hardware and server

| | |
|:---|:---|
| machine | MacBook Pro (Mac14,6) |
| chip | Apple M2 Max — 12 CPU cores (8P + 4E), 38 GPU cores |
| memory | 96 GB unified |
| macOS | 15.7.8 (24G824) |
| server | oMLX 0.5.5 (2128), prompt cache disabled |
| engine | mlx 0.32.0, mlx-lm 0.31.3 |
| Langfuse | 4.11.0 |

Sampler settings and model IDs are pinned in `benchmark.yaml`. Qwen uses thinking disabled; Gemma
models use their provider defaults.

## Setup

Install Docker, `uv`, and GNU Make, and configure any OpenAI-compatible API exposing the selected
model IDs.

```fish
cp .env.example .env
# Replace every change-me value in .env.
make init
```

`make init` runs `setup`, `up`, and `sync`. All three are idempotent and stay available
individually; `make help` lists every target. Keep credentials local — `.env` is ignored by Git.

Point Handy's custom OpenAI provider at `http://localhost:4000/v1` and set its prompt template to
exactly `${output}`, so its single user message carries only the raw transcript. The proxy rejects
other message shapes, replaces that message with the compiled Langfuse prompt, and injects
`OPENAI_API_KEY`, so Handy never needs the upstream credential. `OPENAI_API_HOST` selects the
upstream; a loopback address works both inside and outside the proxy container.

## Run experiments

```fish
make eval
make eval ARGS="--case happy-1 --model 'Gemma 4 E4B'"
make eval ARGS="--prompt-label production --prompt-label candidate"
make eval ARGS="--concurrency 2"
make status
make view
make down
```

Each model-and-resolved-prompt-version pair is a Langfuse dataset experiment. With no prompt
selector, `make eval` uses `LANGFUSE_PROMPT_LABEL` (`production` by default). Repeat
`--prompt-label` and `--prompt-version` to compare several selectors in one invocation; selectors
that resolve to the same numeric version run once. Filters change only that run — every trace,
score, and comparison lands in Langfuse either way.

Each item scores `pass` (boolean, all assertions held) and `assertion_rate` (fraction that held),
both defined for every item so runs stay comparable. Run-level scores add `pass_rate` over all 45
items, `pass_rate:<category>`, and a `pass_rate:negative-control` / `pass_rate:positive-case`
split, each carrying its own denominator in the score comment. Categories come from dataset item
metadata, so slice items by `metadata.category` in the Langfuse UI rather than by score name.

## Prompt workflow

`make sync` seeds `transcript-cleanup` only when it does not already exist — v1 labelled
`baseline`, v2 `production`. After that Langfuse is authoritative, and an existing prompt must be
a chat prompt carrying a `production` label.

Edit prompts in Langfuse, label a version `candidate`, then compare it with `production`:

```fish
make eval ARGS="--prompt-label production --prompt-label candidate"
```

Move the `production` label to the winner in Langfuse. The proxy does not cache prompts, so a new
label applies to the next Handy request; if Langfuse cannot resolve the prompt, completions fail
with an OpenAI-style 503.

`make dataset-export` refreshes the tracked seed, `make dataset-check` reports drift against
Langfuse, and `make test` runs the test suite.

## License

[MIT](LICENSE)
