from pathlib import Path

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数と.envから読み込む実行設定。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_host: HttpUrl = Field(default="http://localhost:11434", validation_alias="OLLAMA_HOST")
    ollama_chat_model: str = Field(default="qwen3:8b", validation_alias="OLLAMA_CHAT_MODEL")
    ollama_embed_model: str = Field(default="embeddinggemma", validation_alias="OLLAMA_EMBED_MODEL")
    ollama_timeout_seconds: float = Field(
        default=120.0, gt=0, validation_alias="OLLAMA_TIMEOUT_SECONDS"
    )
    default_top_k: int = Field(default=3, ge=1, validation_alias="DEFAULT_TOP_K")
    data_dir: Path = Field(default=Path("data/sessions"), validation_alias="DATA_DIR")

    @field_validator("ollama_chat_model", "ollama_embed_model")
    @classmethod
    def model_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("モデル名は空にできません")
        return value

    @property
    def ollama_host_string(self) -> str:
        return str(self.ollama_host).rstrip("/")
