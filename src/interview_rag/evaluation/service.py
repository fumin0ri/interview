from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from interview_rag.adapters.storage import SessionPaths, read_json, write_json_atomic
from interview_rag.errors import DataValidationError
from interview_rag.models import (
    CategorySummary,
    EvaluationAnswer,
    EvaluationQuestion,
    EvaluationRun,
    EvaluationSummary,
    QuestionCategory,
)
from interview_rag.qa.service import QAService

QUESTION_LIST = TypeAdapter(list[EvaluationQuestion])


def load_questions(path: Path) -> list[EvaluationQuestion]:
    try:
        questions = QUESTION_LIST.validate_python(read_json(path))
    except ValidationError as error:
        raise DataValidationError(f"評価質問がSchemaに適合しません: {error}") from error
    if len(questions) != 10:
        raise DataValidationError("評価質問はちょうど10問にしてください")
    if len({question.id for question in questions}) != len(questions):
        raise DataValidationError("評価質問のIDが重複しています")
    present = {question.category for question in questions}
    required = set(QuestionCategory)
    if present != required:
        raise DataValidationError("fact / reasoning / synthesisの各カテゴリを含めてください")
    return questions


def calculate_summary(run: EvaluationRun) -> EvaluationSummary:
    scored = [
        answer
        for answer in run.answers
        if answer.correctness is not None and answer.hallucination is not None
    ]
    if not scored:
        raise DataValidationError("採点済み回答がありません")
    grouped: dict[str, list[int]] = defaultdict(list)
    for answer in scored:
        assert answer.correctness is not None
        grouped[answer.question.category.value].append(answer.correctness)
    categories = {
        category: CategorySummary(count=len(scores), average_correctness=sum(scores) / len(scores))
        for category, scores in sorted(grouped.items())
    }
    hallucination_count = sum(answer.hallucination or 0 for answer in scored)
    return EvaluationSummary(
        scored_count=len(scored),
        average_correctness=sum(answer.correctness or 0 for answer in scored) / len(scored),
        hallucination_rate=hallucination_count / len(scored),
        categories=categories,
    )


class EvaluationService:
    def __init__(self, qa: QAService | None = None) -> None:
        self.qa = qa

    def run(
        self,
        paths: SessionPaths,
        session_id: str,
        questions_path: Path,
        top_k: int,
    ) -> EvaluationRun:
        if self.qa is None:
            raise DataValidationError("eval-runにはQAサービスが必要です")
        questions = load_questions(questions_path)
        write_json_atomic(paths.evaluation_questions, questions)
        run = EvaluationRun(session_id=session_id)
        write_json_atomic(paths.evaluation_results, run)
        for question in questions:
            record = self.qa.answer(paths, question.question, top_k, persist=False)
            run.answers.append(
                EvaluationAnswer(
                    question=question,
                    answer=record.answer,
                    sufficient=record.sufficient,
                    cited_ids=record.cited_ids,
                    retrieved=record.retrieved,
                )
            )
            write_json_atomic(paths.evaluation_results, run)
        return run

    @staticmethod
    def load_run(paths: SessionPaths) -> EvaluationRun:
        try:
            return EvaluationRun.model_validate(read_json(paths.evaluation_results))
        except ValidationError as error:
            raise DataValidationError(f"評価結果がSchemaに適合しません: {error}") from error

    @staticmethod
    def save_score(
        paths: SessionPaths,
        run: EvaluationRun,
        answer_index: int,
        correctness: int,
        hallucination: int,
        comment: str | None,
    ) -> None:
        if correctness not in (0, 1, 2):
            raise DataValidationError("正確性は0、1、2のいずれかです")
        if hallucination not in (0, 1):
            raise DataValidationError("hallucinationは0または1です")
        answer = run.answers[answer_index]
        answer.correctness = correctness
        answer.hallucination = hallucination
        answer.comment = comment.strip() if comment and comment.strip() else None
        write_json_atomic(paths.evaluation_results, run)
