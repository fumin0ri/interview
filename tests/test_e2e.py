import json
from pathlib import Path

from interview_rag.adapters.storage import SessionPaths, append_text, write_json_atomic
from interview_rag.evaluation.service import EvaluationService, calculate_summary
from interview_rag.extraction.service import ExtractionService
from interview_rag.interview.service import InterviewService
from interview_rag.qa.service import QAService
from interview_rag.retrieval.service import RetrievalService
from tests.fakes import FakeClient


def test_full_service_flow_without_ollama(tmp_path: Path) -> None:
    extraction = json.dumps(
        {
            "knowledge": [
                {
                    "type": "decision",
                    "topic": "技術選定",
                    "content": "単純な手法へ変更した。",
                    "reason": "少量データでは安定するため。",
                    "source": None,
                },
                {
                    "type": "lesson",
                    "topic": "技術選定",
                    "content": "データ量と再現性も考慮する。",
                    "reason": None,
                    "source": None,
                },
            ]
        },
        ensure_ascii=False,
    )
    grounded = json.dumps(
        {"answer": "少量データでの安定性を重視します。", "sufficient": True, "cited_ids": ["k001"]},
        ensure_ascii=False,
    )
    insufficient = json.dumps(
        {"answer": "情報不足", "sufficient": False, "cited_ids": []}, ensure_ascii=False
    )
    client = FakeClient(
        [
            "なぜその手法へ変更したのですか？",
            extraction,
            grounded,
            *([grounded] * 9),
            insufficient,
        ]
    )
    paths = SessionPaths.from_data_dir(tmp_path / "sessions", "e2e")
    paths.ensure()

    interviewer = InterviewService(client)
    first = interviewer.first_question("研究上の意思決定")
    append_text(paths.transcript, f"AI: {first}\n")
    answer = "少量データで複雑な手法が不安定だったため、単純な手法へ変更しました。"
    append_text(paths.transcript, f"Me: {answer}\n")
    follow_up = interviewer.next_question(
        "研究上の意思決定",
        30,
        [{"role": "assistant", "content": first}, {"role": "user", "content": answer}],
    )
    assert follow_up.startswith("なぜ")

    knowledge = ExtractionService(client).extract(
        paths.transcript.read_text(encoding="utf-8"), "e2e"
    )
    write_json_atomic(paths.knowledge, knowledge)
    retrieval = RetrievalService(client)
    metadata = retrieval.create_index(paths)
    assert metadata.knowledge_ids == ["k001", "k002"]

    qa = QAService(client, retrieval)
    record = qa.answer(paths, "技術選定で何を重視しますか？", 2)
    assert record.sufficient is True
    assert record.cited_ids == ["k001"]

    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        Path("examples/evaluation_questions.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    evaluation = EvaluationService(qa)
    run = evaluation.run(paths, "e2e", questions_path, 2)
    assert len(run.answers) == 10
    assert paths.evaluation_questions.exists()
    for index in range(10):
        evaluation.save_score(paths, run, index, 2 if index < 9 else 1, 0, None)
    summary = calculate_summary(evaluation.load_run(paths))
    assert summary.scored_count == 10
    assert summary.average_correctness == 1.9
    assert paths.evaluation_results.exists()
