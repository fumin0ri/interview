from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from interview_rag.errors import DataValidationError

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise DataValidationError(
            "session IDは英数字で始まる64文字以内の英数字・ハイフン・アンダースコアにしてください"
        )
    return session_id


@dataclass(frozen=True)
class SessionPaths:
    root: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path, session_id: str) -> SessionPaths:
        validate_session_id(session_id)
        return cls(root=data_dir / session_id)

    @property
    def transcript(self) -> Path:
        return self.root / "interview.txt"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge.json"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def faiss_index(self) -> Path:
        return self.index_dir / "faiss.index"

    @property
    def index_metadata(self) -> Path:
        return self.index_dir / "metadata.json"

    @property
    def qa_log(self) -> Path:
        return self.root / "qa.jsonl"

    @property
    def evaluation_dir(self) -> Path:
        return self.root / "evaluation"

    @property
    def evaluation_results(self) -> Path:
        return self.evaluation_dir / "results.json"

    @property
    def evaluation_questions(self) -> Path:
        return self.evaluation_dir / "questions.json"

    @property
    def evaluation_summary(self) -> Path:
        return self.evaluation_dir / "summary.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


def write_json_atomic(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, BaseModel):
        serializable = value.model_dump(mode="json")
    elif isinstance(value, list):
        serializable = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        serializable = value
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise DataValidationError(f"ファイルがありません: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataValidationError(f"JSONを読み込めません: {path}: {error}") from error


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def append_jsonl(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(value.model_dump_json() + "\n")
        handle.flush()
