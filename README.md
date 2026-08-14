# Transcript Cleanup Bench

Benchmarks local LLM transcript cleanup with Langfuse experiments. It also provides an
OpenAI-compatible tracing proxy for [Handy](https://handy.computer/).

```text
Handy → proxy localhost:4000 → OpenAI-compatible API
             └── traces → Langfuse localhost:4001

Langfuse prompt + dataset → experiment runner → OpenAI-compatible API
                           └── traces, scores, and comparisons → Langfuse
```

Langfuse is the sole benchmark results store. The tracked JSONL dataset is a reproducible seed
for initializing a fresh local project, not a second results or schema system.

## Hardware and server

| | |
|:---|:---|
| machine | MacBook Pro (Mac14,6) |
| chip | Apple M2 Max — 12 CPU cores (8P + 4E), 38 GPU cores |
| memory | 96 GB unified |
| macOS | 15.7.8 (24G824) |
| server | oMLX 0.5.5 (2128), prompt cache disabled |
| engine | mlx 0.32.0, mlx-lm 0.31.3 |
| Langfuse | 4.0.0 |

Sampler settings and model IDs are pinned in `benchmark.yaml`. The prompt is managed in Langfuse;
the committed prompt files are used only to seed a fresh project. Qwen uses thinking disabled;
Gemma models use their provider defaults.

## Setup

Install Docker, `uv`, GNU Make, and configure any OpenAI-compatible API exposing the selected
model IDs.

```fish
cp .env.example .env
# Replace every change-me value in .env.
make setup
make up
make sync
```

Configure `.env` from the tracked example before starting the stack. Keep credentials local;
`.env` is ignored by Git.

Configure Handy's custom OpenAI provider with base URL `http://localhost:4000/v1`. The proxy
injects `OPENAI_API_KEY`, so Handy does not need the upstream credential. Set `OPENAI_API_HOST`
to switch between a local server and a cloud provider. Both streaming and
non-streaming Chat Completions are supported and traced through Langfuse's OpenAI integration.
Set Handy's custom prompt template to exactly `${output}` so its single user message contains only
the raw transcript. The proxy rejects other message shapes and replaces that message with the
compiled `LANGFUSE_PROMPT_NAME` / `LANGFUSE_PROMPT_LABEL` chat prompt.
If Handy omits `temperature`, the proxy supplies `0`; an explicitly configured Handy temperature
is preserved.

`make sync` creates two prompt versions only when `transcript-cleanup` does not exist: v1 receives
the `baseline` label and v2 receives `production`. After creation, Langfuse is authoritative and
sync never changes prompt content or labels. An existing prompt must be a chat prompt with a
`production` label.

## Run experiments

```fish
make eval
make eval ARGS="--case happy-1 --model 'Gemma 4 E4B'"
make eval ARGS="--prompt-label production"
make eval ARGS="--prompt-label candidate"
make eval ARGS="--prompt-version 2"
make eval ARGS="--prompt-label candidate --prompt-version 2"
make eval ARGS="--concurrency 2"
make status
make view
make down
```

Each model-and-resolved-prompt-version pair is a Langfuse dataset experiment. With no prompt
selector, `make eval` uses `LANGFUSE_PROMPT_LABEL` (`production` by default). Repeat
`--prompt-label` and `--prompt-version` to compare several selectors in one invocation; selectors
that resolve to the same numeric version are run once. `make eval` prints each aggregate summary
and Langfuse URL. Case, model, prompt, and concurrency filters only change that run; all traces,
dataset-run links, prompt-version links, failures, scores, and comparisons remain in Langfuse.

## Prompt workflow

Edit prompts and create versions in Langfuse, then label a version `candidate`. Compare it with
`production` in the Langfuse UI or run:

```fish
make eval ARGS="--prompt-label production --prompt-label candidate"
```

After a successful comparison, move the `production` label to the winning version in Langfuse.
The proxy disables prompt caching, so new label assignments apply to the next Handy request. It
has no local fallback: if Langfuse cannot resolve the configured prompt, completions fail with an
OpenAI-style 503 response.

The dataset seed can be refreshed deliberately with `make dataset-export`, and
`make dataset-check` compares it with the current Langfuse dataset.

## Scheduled MinIO export

The Compose stack already creates the `langfuse` bucket and permits the internal `minio`
hostname in both Langfuse containers. Scheduled export settings are project integrations, so set
this up once in **Project Settings → Integrations → Blob Storage** (or through Langfuse's public
blob-storage integration REST API):

- Provider: S3-compatible
- Endpoint: `http://minio:9000`
- Region: `auto`
- Access key: `minio`
- Secret key: the `MINIO_ROOT_PASSWORD` value from `.env`
- Bucket: `langfuse`
- Prefix: `exports/`
- Export source: enriched observations and scores
- Format: JSONL with gzip compression
- History: full history
- Schedule: daily

Use the integration's **Validate** action before saving. Scheduled integrations are intentionally
not configured through Compose environment variables; `LANGFUSE_S3_BATCH_EXPORT_*` variables are
for the separate on-demand batch-export feature. See Langfuse's
[scheduled blob export](https://langfuse.com/docs/api-and-data-platform/features/export-to-blob-storage)
and [self-hosted MinIO configuration](https://langfuse.com/self-hosting/deployment/infrastructure/blobstorage)
documentation.
