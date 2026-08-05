# promptfoo arm

Evaluates the transcript-cleaner prompt with [promptfoo](https://promptfoo.dev).

The prompt takes a raw dictation transcript and returns a cleaned version — fixing mishears, removing filler words, formatting numbers without adding commentary or answering anything the transcript happens to ask.

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

Also needs a local/remote OpenAI compatible server serving `gemma-4-e4b-it-4bit`.
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
