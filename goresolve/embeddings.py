import hashlib
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


def _token_bucket(token: str, dim: int) -> int:
    digest = hashlib.md5(token.encode()).digest()
    return int.from_bytes(digest[:4], 'little') % dim


class FakeEmbedder:
    """Deterministic bag-of-hashed-tokens embedder for unit tests (no model download)."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in text.lower().split():
                out[i, _token_bucket(tok, self.dim)] += 1.0
            norm = np.linalg.norm(out[i]) or 1.0
            out[i] /= norm
        return out


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = 'sentence-transformers/all-MiniLM-L6-v2'):
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


def cosine_topk(
    query_vecs: np.ndarray,
    doc_vecs: np.ndarray,
    doc_ids: list[str],
    *,
    top_k: int,
    min_cosine: float,
) -> list[tuple[str, float]]:
    scores = query_vecs @ doc_vecs.T
    best_by_id: dict[str, float] = {}

    for q_idx in range(scores.shape[0]):
        row = scores[q_idx]
        ranked = sorted(
            ((doc_ids[i], float(row[i])) for i in range(len(doc_ids)) if row[i] >= min_cosine),
            key=lambda item: item[1],
            reverse=True,
        )
        for doc_id, score in ranked[:top_k]:
            if doc_id not in best_by_id or score > best_by_id[doc_id]:
                best_by_id[doc_id] = score

    return sorted(best_by_id.items(), key=lambda item: item[1], reverse=True)[:top_k]
