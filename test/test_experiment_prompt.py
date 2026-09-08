import pytest
from langfuse.api import Prompt_Chat
from langfuse.model import ChatPromptClient

from transcript_cleanup_bench.experiment import experiment_prompt_template
from transcript_cleanup_bench.vocabulary import VocabularyContext


def prompt(system: str) -> ChatPromptClient:
    return ChatPromptClient(
        Prompt_Chat(
            name="transcript-cleanup",
            version=7,
            type="chat",
            labels=[],
            tags=[],
            config={},
            prompt=[
                {"role": "system", "content": system},
                {"role": "user", "content": "{{transcript}}"},
            ],
        )
    )


VOCABULARY = VocabularyContext(
    prompt="KNOWN VOCABULARY\n\n- Meetily: meeting transcription application",
    revision="revision-1",
)


def test_experiment_template_binds_vocabulary_and_keeps_transcript_variable() -> None:
    template = experiment_prompt_template(
        prompt("Clean the transcript.\n\n{{vocabulary}}"), VOCABULARY
    )

    messages = template.invoke({"transcript": "raw words"}).messages

    assert template.input_variables == ["transcript"]
    assert messages[0].content.endswith(VOCABULARY.prompt)
    assert messages[1].content == "raw words"


def test_experiment_template_rejects_a_prompt_without_vocabulary_placeholder() -> None:
    with pytest.raises(ValueError, match="must contain.*vocabulary"):
        experiment_prompt_template(prompt("Clean the transcript."), VOCABULARY)
