from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np

from interview_rag.errors import DataValidationError


def normalize(vectors: list[list[float]] | np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype="float32")
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise DataValidationError("Embeddingは空でない2次元配列である必要があります")
    if not np.isfinite(array).all():
        raise DataValidationError("Embeddingに非有限値が含まれています")
    faiss.normalize_L2(array)
    if np.any(np.linalg.norm(array, axis=1) == 0):
        raise DataValidationError("ゼロベクトルのEmbeddingは索引化できません")
    return array


def build_index(vectors: list[list[float]]) -> faiss.IndexFlatIP:
    array = normalize(vectors)
    index = faiss.IndexFlatIP(array.shape[1])
    index.add(array)
    return index


def save_index_atomic(index: faiss.Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    faiss.write_index(index, str(temporary))
    temporary.replace(path)


def load_index(path: Path) -> faiss.Index:
    if not path.exists():
        raise DataValidationError(f"FAISS索引がありません: {path}")
    return faiss.read_index(str(path))


def search(index: faiss.Index, query: list[float], top_k: int) -> list[tuple[int, float]]:
    if index.ntotal == 0:
        return []
    query_array = normalize([query])
    scores, positions = index.search(query_array, min(top_k, index.ntotal))
    return [
        (int(position), float(score))
        for position, score in zip(positions[0], scores[0], strict=True)
        if position >= 0
    ]
