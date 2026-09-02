from pathlib import Path

import pytest
from pydantic import ValidationError

from interview_rag.adapters.storage import validate_session_id
from interview_rag.config import Settings
from interview_rag.errors import DataValidationError
from interview_rag.interview.service import parse_transcript
from interview_rag.models import Knowledge, QAResponse


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://192.0.2.10:11434")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "chat-model")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "embed-model")
    monkeypatch.setenv("DEFAULT_TOP_K", "5")
    monkeypatch.setenv("DATA_DIR", "private-data")
    settings = Settings(_env_file=None)
    assert settings.ollama_host_string == "http://192.0.2.10:11434"
    assert settings.ollama_chat_model == "chat-model"
    assert settings.ollama_embed_model == "embed-model"
    assert settings.default_top_k == 5
    assert settings.data_dir == Path("private-data")


def test_knowledge_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Knowledge(
            id="k001",
            type="opinion",
            topic="topic",
            content="content",
            source="session",
        )


def test_qa_requires_citation_when_sufficient() -> None:
    with pytest.raises(ValidationError):
        QAResponse(answer="回答", sufficient=True, cited_ids=[])


@pytest.mark.parametrize("session_id", ["../escape", "has space", "", "_starts_wrong"])
def test_session_id_rejects_unsafe_values(session_id: str) -> None:
    with pytest.raises(DataValidationError):
        validate_session_id(session_id)


def test_session_id_accepts_safe_value() -> None:
    assert validate_session_id("interview_001") == "interview_001"


def test_parse_transcript_supports_dangling_question_for_resume() -> None:
    conversation = parse_transcript("AI: 質問1\nMe: 回答1\nAI: 質問2\n")
    assert conversation[-1] == {"role": "assistant", "content": "質問2"}


def test_parse_transcript_rejects_invalid_speaker_order() -> None:
    with pytest.raises(DataValidationError, match="発話順"):
        parse_transcript("AI: 質問1\nAI: 質問2\n")
