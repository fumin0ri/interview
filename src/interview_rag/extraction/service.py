from __future__ import annotations

from pydantic import ValidationError

from interview_rag.adapters.ollama_client import LanguageModelClient
from interview_rag.errors import DataValidationError
from interview_rag.models import ExtractionEnvelope, Knowledge

EXTRACTION_PROMPT = """以下はインタビュー記録です。

この人物について得られる知識を抽出してください。種類は次のいずれかです。
- fact
- experience
- decision
- reason
- lesson
- preference

特に「何をしたか」だけでなく、「なぜそう判断したか」「その経験から何を学んだか」
を抽出してください。記録にない内容は推測しないでください。
sourceは空または「{source}」にしてください。

インタビュー:
{transcript}
"""


class ExtractionService:
    def __init__(self, client: LanguageModelClient) -> None:
        self.client = client

    def extract(self, transcript: str, session_id: str) -> list[Knowledge]:
        if not transcript.strip():
            raise DataValidationError("インタビュー記録が空です")
        schema = ExtractionEnvelope.model_json_schema()
        prompt = EXTRACTION_PROMPT.format(source=session_id, transcript=transcript)
        raw = self.client.chat([{"role": "user", "content": prompt}], schema=schema)
        envelope = self._validate_or_repair(raw, schema)
        return [
            Knowledge(
                id=f"k{position:03d}",
                type=draft.type,
                topic=draft.topic.strip(),
                content=draft.content.strip(),
                reason=draft.reason.strip() if draft.reason and draft.reason.strip() else None,
                source=session_id,
            )
            for position, draft in enumerate(envelope.knowledge, start=1)
        ]

    def _validate_or_repair(self, raw: str, schema: dict[str, object]) -> ExtractionEnvelope:
        try:
            return ExtractionEnvelope.model_validate_json(raw)
        except ValidationError as first_error:
            repair_prompt = (
                "次の出力は指定JSON Schemaに適合しません。内容を追加・推測せず、"
                "Schemaに適合するJSONだけを返してください。\n\n"
                f"検証エラー:\n{first_error}\n\n不正な出力:\n{raw}"
            )
            repaired = self.client.chat([{"role": "user", "content": repair_prompt}], schema=schema)
            try:
                return ExtractionEnvelope.model_validate_json(repaired)
            except ValidationError as second_error:
                raise DataValidationError(
                    "知識抽出結果を2回検証しましたが、Schemaに適合しませんでした"
                ) from second_error
