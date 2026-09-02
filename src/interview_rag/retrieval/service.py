from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from interview_rag.adapters.faiss_store import (
    build_index,
    load_index,
    normalize,
    save_index_atomic,
    search,
)
from interview_rag.adapters.ollama_client import LanguageModelClient
from interview_rag.adapters.storage import SessionPaths, read_json, write_json_atomic
from interview_rag.errors import DataValidationError, IndexMismatchError
from interview_rag.models import IndexMetadata, Knowledge, RetrievedKnowledge

KNOWLEDGE_LIST = TypeAdapter(list[Knowledge])


def knowledge_to_text(knowledge: Knowledge) -> str:
    return "\n".join(
        [
            f"type: {knowledge.type.value}",
            f"topic: {knowledge.topic}",
            f"content: {knowledge.content}",
            f"reason: {knowledge.reason or ''}",
        ]
    )


def knowledge_hash(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataValidationError(f"knowledge.jsonを読み込めません: {error}") from error
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_knowledge(path: Path) -> list[Knowledge]:
    try:
        knowledge = KNOWLEDGE_LIST.validate_python(read_json(path))
    except ValidationError as error:
        raise DataValidationError(f"knowledge.jsonがSchemaに適合しません: {error}") from error
    if not knowledge:
        raise DataValidationError("knowledge.jsonに知識がありません")
    return knowledge


class RetrievalService:
    def __init__(self, client: LanguageModelClient) -> None:
        self.client = client

    def create_index(self, paths: SessionPaths) -> IndexMetadata:
        knowledge = load_knowledge(paths.knowledge)
        vectors = self.client.embed([knowledge_to_text(item) for item in knowledge])
        if len(vectors) != len(knowledge):
            raise DataValidationError("Embedding数とKnowledge数が一致しません")
        normalized = normalize(vectors)
        index = build_index(normalized.tolist())
        metadata = IndexMetadata(
            embedding_model=self.client.embedding_model,
            dimension=normalized.shape[1],
            knowledge_sha256=knowledge_hash(paths.knowledge),
            knowledge_ids=[item.id for item in knowledge],
        )
        save_index_atomic(index, paths.faiss_index)
        write_json_atomic(paths.index_metadata, metadata)
        return metadata

    def retrieve(self, paths: SessionPaths, question: str, top_k: int) -> list[RetrievedKnowledge]:
        if top_k < 1:
            raise DataValidationError("top-kは1以上にしてください")
        knowledge = load_knowledge(paths.knowledge)
        try:
            metadata = IndexMetadata.model_validate(read_json(paths.index_metadata))
        except ValidationError as error:
            raise DataValidationError(f"索引メタデータが不正です: {error}") from error
        self._validate_metadata(paths, metadata, knowledge)
        index = load_index(paths.faiss_index)
        query_vectors = self.client.embed([question])
        if len(query_vectors) != 1:
            raise DataValidationError("質問Embeddingが1件ではありません")
        if len(query_vectors[0]) != metadata.dimension:
            raise IndexMismatchError("Embedding次元が索引と異なります。indexを再実行してください")
        by_id = {item.id: item for item in knowledge}
        hits = search(index, query_vectors[0], top_k)
        return [
            RetrievedKnowledge(knowledge=by_id[metadata.knowledge_ids[position]], score=score)
            for position, score in hits
        ]

    def _validate_metadata(
        self, paths: SessionPaths, metadata: IndexMetadata, knowledge: list[Knowledge]
    ) -> None:
        if metadata.embedding_model != self.client.embedding_model:
            raise IndexMismatchError(
                "Embeddingモデルが索引作成時と異なります。indexを再実行してください"
            )
        if metadata.knowledge_sha256 != knowledge_hash(paths.knowledge):
            raise IndexMismatchError("knowledge.jsonが変更されています。indexを再実行してください")
        ids = [item.id for item in knowledge]
        if metadata.knowledge_ids != ids:
            raise IndexMismatchError(
                "Knowledge IDの並びが索引と異なります。indexを再実行してください"
            )
