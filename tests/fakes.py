from __future__ import annotations

import hashlib
from typing import Any


class FakeClient:
    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        chat_model: str = "fake-chat",
        embedding_model: str = "fake-embed",
    ) -> None:
        self.responses = list(responses or [])
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.chat_calls: list[tuple[list[dict[str, str]], dict[str, Any] | None]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.chat_calls.append((messages, schema))
        if not self.responses:
            raise AssertionError("FakeClientの応答キューが空です")
        return self.responses.pop(0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = [float(digest[index] + 1) for index in range(4)]
            vectors.append(vector)
        return vectors

    def model_names(self) -> list[str]:
        return [self.chat_model, self.embedding_model]


class FixedVectorClient(FakeClient):
    def __init__(
        self,
        responses: list[str] | None = None,
        vectors: dict[str, list[float]] | None = None,
        *,
        embedding_model: str = "fake-embed",
    ) -> None:
        super().__init__(responses, embedding_model=embedding_model)
        self.vectors = vectors or {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(text, [1.0, 0.0, 0.0]) for text in texts]
