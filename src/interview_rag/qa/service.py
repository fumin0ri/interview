from __future__ import annotations

import json

from pydantic import ValidationError

from interview_rag.adapters.ollama_client import LanguageModelClient
from interview_rag.adapters.storage import SessionPaths, append_jsonl
from interview_rag.errors import DataValidationError
from interview_rag.models import QARecord, QAResponse
from interview_rag.retrieval.service import RetrievalService

QA_PROMPT = """以下はこの人物についてインタビューから得られた知識です。
これらの情報のみを根拠として質問に日本語で回答してください。
根拠が不足している場合は、推測せず sufficient=false、answer="情報不足"、cited_ids=[]
としてください。根拠が十分な場合は、利用した知識IDだけをcited_idsに入れてください。

知識:
{knowledge}

質問:
{question}
"""


class QAService:
    def __init__(self, client: LanguageModelClient, retrieval: RetrievalService) -> None:
        self.client = client
        self.retrieval = retrieval

    def answer(
        self, paths: SessionPaths, question: str, top_k: int, *, persist: bool = True
    ) -> QARecord:
        question = question.strip()
        if not question:
            raise DataValidationError("質問は空にできません")
        retrieved = self.retrieval.retrieve(paths, question, top_k)
        knowledge_payload = [
            {
                "id": hit.knowledge.id,
                "type": hit.knowledge.type.value,
                "topic": hit.knowledge.topic,
                "content": hit.knowledge.content,
                "reason": hit.knowledge.reason,
            }
            for hit in retrieved
        ]
        prompt = QA_PROMPT.format(
            knowledge=json.dumps(knowledge_payload, ensure_ascii=False, indent=2),
            question=question,
        )
        raw = self.client.chat(
            [{"role": "user", "content": prompt}], schema=QAResponse.model_json_schema()
        )
        try:
            response = QAResponse.model_validate_json(raw)
        except ValidationError as error:
            raise DataValidationError(f"回答がSchemaに適合しません: {error}") from error
        valid_ids = {hit.knowledge.id for hit in retrieved}
        invalid_ids = set(response.cited_ids) - valid_ids
        if invalid_ids:
            raise DataValidationError(
                f"回答が検索結果外のKnowledge IDを参照しました: {sorted(invalid_ids)}"
            )
        answer = response.answer if response.sufficient else "情報不足"
        cited_ids = response.cited_ids if response.sufficient else []
        record = QARecord(
            question=question,
            answer=answer,
            sufficient=response.sufficient,
            cited_ids=cited_ids,
            retrieved=retrieved,
        )
        if persist:
            append_jsonl(paths.qa_log, record)
        return record
