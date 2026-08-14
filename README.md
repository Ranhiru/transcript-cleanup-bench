# Transcript Cleanup Bench

Benchmarks local LLM transcript cleanup with Langfuse experiments. It also provides an
OpenAI-compatible tracing proxy for [Handy](https://handy.computer/).

```text
Handy → proxy localhost:4000 → OpenAI-compatible API
             └── traces → Langfuse localhost:4001

Langfuse dataset → Langfuse experiment runner → OpenAI-compatible API
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

Sampler settings, prompt files, and model IDs are pinned in `benchmark.yaml`. Qwen uses thinking
disabled; Gemma models use their provider defaults.

## Setup

Install Docker, `uv`, GNU Make, and configure any OpenAI-compatible API exposing the selected
model IDs.

```fish
make init-env
make setup
make up
make sync
```

`make init-env` preserves existing configured values, securely generates all missing local
credentials, and writes `.env` with owner-only permissions. It prompts for the upstream
`OPENAI_API_KEY`; generated credentials remain local because `.env` is ignored by Git.

Configure Handy's custom OpenAI provider with base URL `http://localhost:4000/v1`. The proxy
injects `OPENAI_API_KEY`, so Handy does not need the upstream credential. Set `OPENAI_API_HOST`
to switch between a local server and a cloud provider. Both streaming and
non-streaming Chat Completions are supported and traced through Langfuse's OpenAI integration.

## Run experiments

```fish
make eval
make eval ARGS="--case happy-1 --model 'Gemma 4 E4B' --prompt v2"
make eval ARGS="--concurrency 2"
make status
make view
make down
```

Each model-and-prompt pair is a Langfuse dataset experiment. `make eval` prints its aggregate
summary and Langfuse URL. Case, model, prompt, and concurrency filters only change that run; all
traces, dataset-run links, failures, scores, and comparisons remain in Langfuse.

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
