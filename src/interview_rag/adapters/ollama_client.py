from __future__ import annotations

from typing import Any, Protocol

import ollama

from interview_rag.errors import InterviewRAGError


class LanguageModelClient(Protocol):
    chat_model: str
    embedding_model: str

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def model_names(self) -> list[str]: ...


class OllamaClient:
    def __init__(
        self,
        host: str,
        chat_model: str,
        embedding_model: str,
        timeout_seconds: float,
    ) -> None:
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self._client = ollama.Client(host=host, timeout=timeout_seconds)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        try:
            response = self._client.chat(
                model=self.chat_model,
                messages=messages,
                format=schema,
                options={"temperature": temperature},
                stream=False,
            )
        except (ollama.RequestError, ollama.ResponseError) as error:
            raise InterviewRAGError(f"Ollama Chat APIエラー: {error}") from error
        return response.message.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._client.embed(model=self.embedding_model, input=texts)
        except (ollama.RequestError, ollama.ResponseError) as error:
            raise InterviewRAGError(f"Ollama Embed APIエラー: {error}") from error
        return response.embeddings

    def model_names(self) -> list[str]:
        try:
            response = self._client.list()
        except (ollama.RequestError, ollama.ResponseError) as error:
            raise InterviewRAGError(f"Ollama Models APIエラー: {error}") from error
        return [model.model for model in response.models if model.model]
