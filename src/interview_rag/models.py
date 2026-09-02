from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeType(StrEnum):
    FACT = "fact"
    EXPERIENCE = "experience"
    DECISION = "decision"
    REASON = "reason"
    LESSON = "lesson"
    PREFERENCE = "preference"


class KnowledgeDraft(StrictModel):
    type: KnowledgeType
    topic: str = Field(min_length=1)
    content: str = Field(min_length=1)
    reason: str | None = None
    source: str | None = None


class Knowledge(StrictModel):
    id: str = Field(pattern=r"^k\d{3,}$")
    type: KnowledgeType
    topic: str = Field(min_length=1)
    content: str = Field(min_length=1)
    reason: str | None = None
    source: str = Field(min_length=1)


class ExtractionEnvelope(StrictModel):
    knowledge: list[KnowledgeDraft]


class RetrievedKnowledge(StrictModel):
    knowledge: Knowledge
    score: float


class QAResponse(StrictModel):
    answer: str = Field(min_length=1)
    sufficient: bool
    cited_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sufficient_answer_needs_citation(self) -> QAResponse:
        if self.sufficient and not self.cited_ids:
            raise ValueError("根拠ありの回答にはcited_idsが必要です")
        return self


class QARecord(StrictModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    question: str
    answer: str
    sufficient: bool
    cited_ids: list[str]
    retrieved: list[RetrievedKnowledge]


class IndexMetadata(StrictModel):
    created_at: str = Field(default_factory=utc_now_iso)
    embedding_model: str
    dimension: int = Field(gt=0)
    knowledge_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_ids: list[str]


class QuestionCategory(StrEnum):
    FACT = "fact"
    REASONING = "reasoning"
    SYNTHESIS = "synthesis"


class EvaluationQuestion(StrictModel):
    id: str = Field(min_length=1)
    category: QuestionCategory
    question: str = Field(min_length=1)


class EvaluationAnswer(StrictModel):
    question: EvaluationQuestion
    answer: str
    sufficient: bool
    cited_ids: list[str]
    retrieved: list[RetrievedKnowledge]
    correctness: int | None = Field(default=None, ge=0, le=2)
    hallucination: int | None = Field(default=None, ge=0, le=1)
    comment: str | None = None


class EvaluationRun(StrictModel):
    session_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    answers: list[EvaluationAnswer] = Field(default_factory=list)


class CategorySummary(StrictModel):
    count: int
    average_correctness: float


class EvaluationSummary(StrictModel):
    scored_count: int
    average_correctness: float
    hallucination_rate: float
    categories: dict[str, CategorySummary]


class SessionManifest(StrictModel):
    session_id: str
    topic: str
    target_minutes: int
    chat_model: str
    embedding_model: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    status: dict[str, bool] = Field(default_factory=dict)
