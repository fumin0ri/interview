import json
from pathlib import Path

import pytest

from interview_rag.adapters.storage import SessionPaths, write_json_atomic
from interview_rag.errors import DataValidationError
from interview_rag.evaluation.service import EvaluationService, calculate_summary, load_questions
from interview_rag.models import (
    EvaluationAnswer,
    EvaluationQuestion,
    EvaluationRun,
    QuestionCategory,
)


def question(number: int, category: QuestionCategory) -> EvaluationQuestion:
    return EvaluationQuestion(id=f"q{number:02d}", category=category, question=f"質問{number}")


def ten_questions() -> list[EvaluationQuestion]:
    categories = [
        QuestionCategory.FACT,
        QuestionCategory.FACT,
        QuestionCategory.FACT,
        QuestionCategory.REASONING,
        QuestionCategory.REASONING,
        QuestionCategory.REASONING,
        QuestionCategory.SYNTHESIS,
        QuestionCategory.SYNTHESIS,
        QuestionCategory.SYNTHESIS,
        QuestionCategory.SYNTHESIS,
    ]
    return [question(index, category) for index, category in enumerate(categories, start=1)]


def test_load_questions_requires_exactly_ten(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    write_json_atomic(path, ten_questions()[:9])
    with pytest.raises(DataValidationError, match="10問"):
        load_questions(path)


def test_load_questions_requires_all_categories(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    write_json_atomic(
        path,
        [question(index, QuestionCategory.FACT) for index in range(1, 11)],
    )
    with pytest.raises(DataValidationError, match="各カテゴリ"):
        load_questions(path)


def test_save_score_persists_and_summary_aggregates(tmp_path: Path) -> None:
    paths = SessionPaths.from_data_dir(tmp_path, "s1")
    run = EvaluationRun(
        session_id="s1",
        answers=[
            EvaluationAnswer(
                question=question(1, QuestionCategory.FACT),
                answer="回答1",
                sufficient=True,
                cited_ids=["k001"],
                retrieved=[],
            ),
            EvaluationAnswer(
                question=question(2, QuestionCategory.REASONING),
                answer="回答2",
                sufficient=False,
                cited_ids=[],
                retrieved=[],
            ),
        ],
    )
    service = EvaluationService()
    service.save_score(paths, run, 0, 2, 0, "正しい")
    service.save_score(paths, run, 1, 1, 1, None)
    restored = service.load_run(paths)
    summary = calculate_summary(restored)
    assert summary.scored_count == 2
    assert summary.average_correctness == pytest.approx(1.5)
    assert summary.hallucination_rate == pytest.approx(0.5)
    assert summary.categories["fact"].average_correctness == 2.0


def test_invalid_manual_score_is_rejected(tmp_path: Path) -> None:
    paths = SessionPaths.from_data_dir(tmp_path, "s1")
    run = EvaluationRun(session_id="s1", answers=[])
    with pytest.raises(DataValidationError):
        EvaluationService.save_score(paths, run, 0, 3, 0, None)


def test_question_file_example_is_valid() -> None:
    path = Path("examples/evaluation_questions.json")
    questions = load_questions(path)
    assert len(questions) == 10
    assert json.loads(path.read_text(encoding="utf-8"))[0]["category"] == "fact"
