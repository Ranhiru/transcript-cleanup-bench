# promptfoo arm

Evaluates the transcript-cleaner prompt with [promptfoo](https://promptfoo.dev).

The prompt takes a raw dictation transcript and returns a cleaned version — fixing mishears, removing filler words, formatting numbers without adding commentary or answering anything the transcript happens to ask.

## Setup

Needs a local/remote OpenAI compatible server serving `gemma-4-e4b-it-4bit`. Currently using OMLX

```fish
set -gx OMLX_API_KEY 123456
```

## Run

```fish
npx promptfoo@latest eval    # run every test against the prompt
npx promptfoo@latest view    # open the results grid in a browser
```

## Files

- `promptfooconfig.yaml` — the whole eval: prompts, providers, and tests
- `prompt-v1.txt` — baseline prompt, with `{{transcript}}` as the input placeholder
- `prompt-v2.txt` — revised prompt, compared against v1 in every run
- `tests/*.yaml` — one file per case category, picked up by a glob

Both prompts come from the `transcription-prompt-eval` repo, where they are `prompt.txt`
(sha `3f57dab2`) and `prompt-v9.txt` (sha `e4fca361`). The v1/v2 numbering is local to
this repo.
