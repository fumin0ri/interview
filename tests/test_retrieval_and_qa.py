import json
from pathlib import Path

import pytest

from interview_rag.adapters.storage import SessionPaths, write_json_atomic
from interview_rag.errors import DataValidationError, IndexMismatchError
from interview_rag.models import Knowledge
from interview_rag.qa.service import QAService
from interview_rag.retrieval.service import RetrievalService, knowledge_to_text
from tests.fakes import FixedVectorClient


def sample_knowledge() -> list[Knowledge]:
    return [
        Knowledge(
            id="k001",
            type="experience",
            topic="モデル選定",
            content="複雑なモデルの精度が安定しなかった。",
            source="s1",
        ),
        Knowledge(
            id="k002",
            type="decision",
            topic="モデル選定",
            content="単純なモデルへ変更した。",
            reason="少量データで分散を抑えるため。",
            source="s1",
        ),
        Knowledge(
            id="k003",
            type="lesson",
            topic="技術選定",
            content="データ量と再現性を考慮する。",
            source="s1",
        ),
    ]


def prepare_index(tmp_path: Path) -> tuple[SessionPaths, FixedVectorClient, RetrievalService]:
    paths = SessionPaths.from_data_dir(tmp_path, "s1")
    knowledge = sample_knowledge()
    write_json_atomic(paths.knowledge, knowledge)
    vectors = {
        knowledge_to_text(knowledge[0]): [0.0, 1.0, 0.0],
        knowledge_to_text(knowledge[1]): [1.0, 0.0, 0.0],
        knowledge_to_text(knowledge[2]): [0.8, 0.2, 0.0],
        "なぜ変更した？": [1.0, 0.0, 0.0],
    }
    client = FixedVectorClient(vectors=vectors)
    retrieval = RetrievalService(client)
    retrieval.create_index(paths)
    return paths, client, retrieval


def test_retrieve_orders_by_cosine_and_limits_top_k(tmp_path: Path) -> None:
    paths, _, retrieval = prepare_index(tmp_path)
    hits = retrieval.retrieve(paths, "なぜ変更した？", 2)
    assert [hit.knowledge.id for hit in hits] == ["k002", "k003"]
    assert hits[0].score == pytest.approx(1.0)


def test_retrieve_returns_all_when_top_k_exceeds_count(tmp_path: Path) -> None:
    paths, _, retrieval = prepare_index(tmp_path)
    assert len(retrieval.retrieve(paths, "なぜ変更した？", 99)) == 3


def test_retrieve_detects_changed_knowledge(tmp_path: Path) -> None:
    paths, _, retrieval = prepare_index(tmp_path)
    knowledge = sample_knowledge()
    knowledge[0].content = "変更された内容"
    write_json_atomic(paths.knowledge, knowledge)
    with pytest.raises(IndexMismatchError, match="変更"):
        retrieval.retrieve(paths, "なぜ変更した？", 3)


def test_retrieve_detects_changed_embedding_model(tmp_path: Path) -> None:
    paths, client, retrieval = prepare_index(tmp_path)
    client.embedding_model = "another-model"
    with pytest.raises(IndexMismatchError, match="モデル"):
        retrieval.retrieve(paths, "なぜ変更した？", 3)


def test_answer_rejects_citation_outside_retrieval(tmp_path: Path) -> None:
    paths, client, retrieval = prepare_index(tmp_path)
    client.responses.append(
        json.dumps(
            {"answer": "根拠外", "sufficient": True, "cited_ids": ["k999"]},
            ensure_ascii=False,
        )
    )
    with pytest.raises(DataValidationError, match="検索結果外"):
        QAService(client, retrieval).answer(paths, "なぜ変更した？", 2)


def test_answer_forces_information不足_when_insufficient(tmp_path: Path) -> None:
    paths, client, retrieval = prepare_index(tmp_path)
    client.responses.append(
        json.dumps(
            {"answer": "推測回答", "sufficient": False, "cited_ids": []},
            ensure_ascii=False,
        )
    )
    record = QAService(client, retrieval).answer(paths, "なぜ変更した？", 2)
    assert record.answer == "情報不足"
    assert record.cited_ids == []
    assert paths.qa_log.exists()
