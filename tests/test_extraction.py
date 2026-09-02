import json

import pytest

from interview_rag.errors import DataValidationError
from interview_rag.extraction.service import ExtractionService
from tests.fakes import FakeClient


def valid_extraction() -> str:
    return json.dumps(
        {
            "knowledge": [
                {
                    "type": "decision",
                    "topic": "技術選定",
                    "content": "単純な手法へ変更した。",
                    "reason": "少量データだったため。",
                    "source": "ignored",
                },
                {
                    "type": "lesson",
                    "topic": "技術選定",
                    "content": "データ量も考慮する。",
                    "reason": "",
                    "source": None,
                },
            ]
        },
        ensure_ascii=False,
    )


def test_extract_assigns_ids_and_overrides_source() -> None:
    client = FakeClient([valid_extraction()])
    result = ExtractionService(client).extract("AI: 質問\nMe: 回答", "interview_001")
    assert [item.id for item in result] == ["k001", "k002"]
    assert {item.source for item in result} == {"interview_001"}
    assert result[1].reason is None


def test_extract_repairs_invalid_json_once() -> None:
    client = FakeClient(["not json", valid_extraction()])
    result = ExtractionService(client).extract("AI: 質問\nMe: 回答", "s1")
    assert len(result) == 2
    assert len(client.chat_calls) == 2


def test_extract_fails_after_second_invalid_response() -> None:
    client = FakeClient(["not json", "still not json"])
    with pytest.raises(DataValidationError):
        ExtractionService(client).extract("AI: 質問\nMe: 回答", "s1")


def test_extract_rejects_empty_transcript() -> None:
    with pytest.raises(DataValidationError):
        ExtractionService(FakeClient()).extract("  ", "s1")
