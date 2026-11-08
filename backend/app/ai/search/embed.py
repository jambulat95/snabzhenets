"""Эмбеддинги. Боевой вариант — BGE-M3 на CPU сервера; каталог провайдеру не уходит."""

import hashlib
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

Vectors = NDArray[np.float32]


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> Vectors:
        """Нормированные векторы, по строке на текст."""
        ...


class BgeM3Embedder:
    name = "BAAI/bge-m3"

    def __init__(self, device: str = "cpu", batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.name, device=device)
        self._batch = batch_size
        self._cache: dict[str, NDArray[np.float32]] = {}

    def encode(self, texts: list[str]) -> Vectors:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            vecs = self._model.encode(
                missing, batch_size=self._batch, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )  # fmt: skip
            self._cache.update(zip(missing, vecs.astype(np.float32), strict=True))
        return np.stack([self._cache[t] for t in texts])


class HashingEmbedder:
    """Для тестов: детерминированный вектор по триграммам символов, без модели."""

    name = "hashing-trigram"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> Vectors:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            s = f"  {t.casefold()} "
            for j in range(len(s) - 2):
                h = int(hashlib.md5(s[j : j + 3].encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1
            norm = np.linalg.norm(out[i])
            if norm:
                out[i] /= norm
        return out
