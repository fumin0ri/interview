from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import typer
from pydantic import ValidationError

from interview_rag.adapters.ollama_client import OllamaClient
from interview_rag.adapters.storage import (
    SessionPaths,
    append_text,
    read_json,
    write_json_atomic,
)
from interview_rag.config import Settings
from interview_rag.errors import InterviewRAGError
from interview_rag.evaluation.service import EvaluationService, calculate_summary
from interview_rag.extraction.service import ExtractionService
from interview_rag.interview.service import InterviewService, parse_transcript
from interview_rag.models import SessionManifest, utc_now_iso
from interview_rag.qa.service import QAService
from interview_rag.retrieval.service import RetrievalService

app = typer.Typer(
    name="interview-rag",
    help="インタビューから暗黙知を抽出し、Vector RAGで活用するCLI",
    no_args_is_help=True,
)
T = TypeVar("T")


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        typer.echo(f"設定エラー: {error}", err=True)
        raise typer.Exit(2) from error


def _client(settings: Settings) -> OllamaClient:
    return OllamaClient(
        host=settings.ollama_host_string,
        chat_model=settings.ollama_chat_model,
        embedding_model=settings.ollama_embed_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def _paths(settings: Settings, session_id: str) -> SessionPaths:
    return SessionPaths.from_data_dir(settings.data_dir, session_id)


def _run(action: Callable[[], T]) -> T:
    try:
        return action()
    except InterviewRAGError as error:
        typer.echo(f"エラー: {error}", err=True)
        raise typer.Exit(1) from error
    except (ConnectionError, TimeoutError, OSError) as error:
        typer.echo(f"接続または入出力エラー: {error}", err=True)
        raise typer.Exit(1) from error


def _load_or_create_manifest(
    paths: SessionPaths, settings: Settings, session_id: str, topic: str, minutes: int
) -> SessionManifest:
    if paths.manifest.exists():
        try:
            return SessionManifest.model_validate(read_json(paths.manifest))
        except ValidationError as error:
            raise InterviewRAGError(f"manifest.jsonが不正です: {error}") from error
    return SessionManifest(
        session_id=session_id,
        topic=topic,
        target_minutes=minutes,
        chat_model=settings.ollama_chat_model,
        embedding_model=settings.ollama_embed_model,
        status={"interview_complete": False, "extracted": False, "indexed": False},
    )


def _update_manifest(paths: SessionPaths, key: str, value: bool = True) -> None:
    try:
        manifest = SessionManifest.model_validate(read_json(paths.manifest))
    except ValidationError as error:
        raise InterviewRAGError(f"manifest.jsonが不正です: {error}") from error
    manifest.status[key] = value
    manifest.updated_at = utc_now_iso()
    write_json_atomic(paths.manifest, manifest)


def _services(settings: Settings) -> tuple[RetrievalService, QAService]:
    client = _client(settings)
    retrieval = RetrievalService(client)
    return retrieval, QAService(client, retrieval)


@app.command()
def doctor() -> None:
    """Ollama接続、モデル、Embedding次元を確認する。"""

    def action() -> None:
        settings = _settings()
        client = _client(settings)
        typer.echo(f"Ollama: {settings.ollama_host_string}")
        names = client.model_names()
        missing = [
            name
            for name in (settings.ollama_chat_model, settings.ollama_embed_model)
            if name not in names
        ]
        if missing:
            raise InterviewRAGError(
                f"Ollamaにモデルがありません: {', '.join(missing)}。サーバー側でpullしてください"
            )
        response = client.chat(
            [{"role": "user", "content": "接続確認です。OKとのみ回答してください。"}]
        )
        vectors = client.embed(["接続確認"])
        if len(vectors) != 1 or not vectors[0]:
            raise InterviewRAGError("Embeddingモデルが有効なベクトルを返しませんでした")
        typer.echo(f"Chat model: {settings.ollama_chat_model} ({response.strip()})")
        typer.echo(f"Embedding model: {settings.ollama_embed_model} (dimension={len(vectors[0])})")
        typer.echo("診断結果: OK")

    _run(action)


@app.command("interview")
def interview_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
    topic: str = typer.Option("研究で困った経験と意思決定", "--topic", help="インタビューのテーマ"),
    minutes: int = typer.Option(30, "--minutes", min=1, help="目標時間（分）"),
) -> None:
    """Ollamaと対話し、インタビュー記録を逐次保存する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        paths.ensure()
        manifest = _load_or_create_manifest(paths, settings, session_id, topic, minutes)
        write_json_atomic(paths.manifest, manifest)
        service = InterviewService(_client(settings))
        conversation = (
            parse_transcript(paths.transcript.read_text(encoding="utf-8"))
            if paths.transcript.exists()
            else []
        )
        started = time.monotonic()
        if conversation and conversation[-1]["role"] == "assistant":
            question = conversation[-1]["content"]
            question_logged = True
        elif conversation:
            question = service.next_question(manifest.topic, manifest.target_minutes, conversation)
            question_logged = False
        else:
            question = service.first_question(manifest.topic)
            question_logged = False
        typer.echo("終了するには :done または ：done と入力してください。")
        try:
            while True:
                typer.echo(f"\nAI: {question}")
                if not question_logged:
                    append_text(paths.transcript, f"AI: {question}\n")
                answer = typer.prompt("Me")
                if answer.strip() in {":done", "：done"}:
                    _update_manifest(paths, "interview_complete")
                    typer.echo("インタビューを保存して終了しました。")
                    return
                append_text(paths.transcript, f"Me: {answer}\n")
                conversation.extend(
                    [
                        {"role": "assistant", "content": question},
                        {"role": "user", "content": answer},
                    ]
                )
                elapsed_minutes = (time.monotonic() - started) / 60
                if elapsed_minutes >= manifest.target_minutes:
                    typer.echo("目標時間に到達しました。続けるか、:doneで終了できます。")
                question = service.next_question(
                    manifest.topic, manifest.target_minutes, conversation
                )
                question_logged = False
        except (KeyboardInterrupt, EOFError):
            typer.echo("\n入力済みの発話を保存して終了しました。")

    _run(action)


@app.command("extract")
def extract_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
) -> None:
    """インタビュー記録から構造化知識を抽出する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        if not paths.transcript.exists():
            raise InterviewRAGError(f"インタビュー記録がありません: {paths.transcript}")
        transcript = paths.transcript.read_text(encoding="utf-8")
        knowledge = ExtractionService(_client(settings)).extract(transcript, session_id)
        write_json_atomic(paths.knowledge, knowledge)
        _update_manifest(paths, "extracted")
        _update_manifest(paths, "indexed", False)
        typer.echo(f"{len(knowledge)}件の知識を保存しました: {paths.knowledge}")

    _run(action)


@app.command("index")
def index_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
) -> None:
    """KnowledgeをEmbeddingし、FAISS索引を作成する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        retrieval, _ = _services(settings)
        metadata = retrieval.create_index(paths)
        _update_manifest(paths, "indexed")
        typer.echo(
            f"{len(metadata.knowledge_ids)}件を索引化しました "
            f"(dimension={metadata.dimension}, model={metadata.embedding_model})"
        )

    _run(action)


@app.command("ask")
def ask_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
    question: str = typer.Option(..., "--question", help="質問"),
    top_k: int | None = typer.Option(None, "--top-k", min=1, help="検索件数"),
) -> None:
    """Top-k Knowledgeだけを根拠に質問へ回答する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        _, qa = _services(settings)
        record = qa.answer(paths, question, top_k or settings.default_top_k)
        typer.echo(f"回答: {record.answer}")
        typer.echo(f"根拠ID: {', '.join(record.cited_ids) if record.cited_ids else 'なし'}")
        typer.echo("検索結果:")
        for hit in record.retrieved:
            typer.echo(f"  {hit.knowledge.id}  score={hit.score:.4f}  {hit.knowledge.content}")

    _run(action)


@app.command("eval-run")
def eval_run_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
    questions: Path = typer.Option(..., "--questions", exists=True, dir_okay=False),
    top_k: int | None = typer.Option(None, "--top-k", min=1, help="検索件数"),
) -> None:
    """10問を一括実行し、評価用回答を保存する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        _, qa = _services(settings)
        run = EvaluationService(qa).run(
            paths, session_id, questions, top_k or settings.default_top_k
        )
        typer.echo(f"{len(run.answers)}問の回答を保存しました: {paths.evaluation_results}")

    _run(action)


def _prompt_choice(label: str, choices: set[int]) -> int:
    while True:
        value = typer.prompt(label)
        try:
            parsed = int(value)
        except ValueError:
            typer.echo(f"{sorted(choices)}のいずれかを入力してください。")
            continue
        if parsed in choices:
            return parsed
        typer.echo(f"{sorted(choices)}のいずれかを入力してください。")


@app.command("eval-score")
def eval_score_command(
    session_id: str = typer.Option(..., "--session", help="セッションID"),
) -> None:
    """評価回答を人手採点し、集計する。"""

    def action() -> None:
        settings = _settings()
        paths = _paths(settings, session_id)
        service = EvaluationService()
        run = service.load_run(paths)
        try:
            for index, answer in enumerate(run.answers):
                if answer.correctness is not None and answer.hallucination is not None:
                    continue
                typer.echo(f"\n[{answer.question.id} / {answer.question.category.value}]")
                typer.echo(f"質問: {answer.question.question}")
                typer.echo(f"回答: {answer.answer}")
                typer.echo(f"根拠ID: {', '.join(answer.cited_ids) if answer.cited_ids else 'なし'}")
                correctness = _prompt_choice("正確性 (2=正しい, 1=一部正しい, 0=誤り)", {0, 1, 2})
                hallucination = _prompt_choice("Hallucination (0=なし, 1=あり)", {0, 1})
                comment = typer.prompt("コメント（任意）", default="", show_default=False)
                service.save_score(paths, run, index, correctness, hallucination, comment or None)
        except (KeyboardInterrupt, EOFError):
            typer.echo("\n入力済みの採点を保存しました。次回同じコマンドで再開できます。")
            return
        summary = calculate_summary(run)
        write_json_atomic(paths.evaluation_summary, summary)
        typer.echo("\n評価完了")
        typer.echo(f"平均正確性: {summary.average_correctness:.3f} / 2")
        typer.echo(f"Hallucination率: {summary.hallucination_rate:.1%}")
        typer.echo(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))

    _run(action)


if __name__ == "__main__":
    app()
