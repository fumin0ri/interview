from __future__ import annotations

from interview_rag.adapters.ollama_client import LanguageModelClient
from interview_rag.errors import DataValidationError

INTERVIEW_SYSTEM_PROMPT = """あなたは熟練者の暗黙知を引き出すインタビュアーです。
テーマは「{topic}」です。目標時間は約{minutes}分です。
会話履歴を踏まえ、次の質問を日本語で一つだけ返してください。
事実だけで終わらせず、「何をしたか」「なぜそう判断したか」「結果はどうだったか」
「そこから何を学んだか」を順に具体化してください。
回答を評価したり、知識を補ったり、複数の質問を同時にしたりしないでください。
既に十分具体的な点は繰り返さず、別の重要な判断や経験へ移ってください。"""


class InterviewService:
    def __init__(self, client: LanguageModelClient) -> None:
        self.client = client

    @staticmethod
    def first_question(topic: str) -> str:
        return f"{topic}について、特に判断や工夫が必要だった具体的な経験を教えてください。"

    def next_question(self, topic: str, minutes: int, conversation: list[dict[str, str]]) -> str:
        messages = [
            {
                "role": "system",
                "content": INTERVIEW_SYSTEM_PROMPT.format(topic=topic, minutes=minutes),
            },
            *conversation,
        ]
        question = " ".join(self.client.chat(messages, temperature=0.3).split())
        if not question:
            raise DataValidationError("Ollamaが空の質問を返しました")
        return question


def parse_transcript(transcript: str) -> list[dict[str, str]]:
    """CLIが保存した一行一発話形式をOllamaの会話履歴へ戻す。"""
    conversation: list[dict[str, str]] = []
    expected = "AI"
    for line_number, raw_line in enumerate(transcript.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("AI: "):
            speaker, role, content = "AI", "assistant", line[4:].strip()
        elif line.startswith("Me: "):
            speaker, role, content = "Me", "user", line[4:].strip()
        else:
            raise DataValidationError(
                f"interview.txtの{line_number}行目が 'AI: ' または 'Me: ' で始まりません"
            )
        if speaker != expected:
            raise DataValidationError(
                f"interview.txtの{line_number}行目で発話順が不正です（期待: {expected}）"
            )
        if not content:
            raise DataValidationError(f"interview.txtの{line_number}行目の発話が空です")
        conversation.append({"role": role, "content": content})
        expected = "Me" if speaker == "AI" else "AI"
    return conversation
