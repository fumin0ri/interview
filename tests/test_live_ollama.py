import os

import pytest

from interview_rag.adapters.ollama_client import OllamaClient
from interview_rag.config import Settings


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_OLLAMA_TESTS") != "1", reason="RUN_OLLAMA_TESTS is not 1")
def test_live_ollama_chat_and_embedding() -> None:
    settings = Settings()
    client = OllamaClient(
        settings.ollama_host_string,
        settings.ollama_chat_model,
        settings.ollama_embed_model,
        settings.ollama_timeout_seconds,
    )
    assert client.chat([{"role": "user", "content": "OKとのみ回答してください"}]).strip()
    vectors = client.embed(["接続確認"])
    assert len(vectors) == 1
    assert len(vectors[0]) > 0
