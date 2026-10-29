import os

import numpy as np

from server.app.application.ports import EmbeddingProviderPort
from server.app.domain.entities import KnowledgeItemEntity

_GLOBAL_EMBED_MODEL = None
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_DIMENSION = 384


def get_embed_model():
    """Lazily load the local fastembed model on CPU. No paid API is used."""
    global _GLOBAL_EMBED_MODEL
    if _GLOBAL_EMBED_MODEL is None:
        try:
            from fastembed import TextEmbedding

            _GLOBAL_EMBED_MODEL = TextEmbedding(model_name=MODEL_NAME)
        except Exception as e:
            print(f"[Embedding] Warning: Failed to load fastembed model: {e}")
            _GLOBAL_EMBED_MODEL = None
    return _GLOBAL_EMBED_MODEL


class FastEmbedProvider(EmbeddingProviderPort):
    def __init__(self, model_name: str = MODEL_NAME):
        self._model_name = model_name
        self.dimension = MODEL_DIMENSION

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> bytes:
        clean = text.strip()
        if not clean:
            return np.zeros(self.dimension, dtype=np.float32).tobytes()

        model = get_embed_model()
        if model is None:
            raise RuntimeError("Embedding model is not available")

        embeddings = list(model.embed([clean]))
        vec = embeddings[0].astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tobytes()

    def embed_item(self, item: KnowledgeItemEntity) -> bytes:
        parts = [item.title, item.core_idea]
        if item.details and item.details != item.core_idea:
            parts.append(item.details)
        if item.concepts:
            parts.append("Concepts: " + ", ".join(item.concepts))
        if item.tags:
            parts.append("Tags: " + ", ".join(item.tags))
        text = "\n".join(parts)
        return self.embed_text(text)

    def calculate_similarity(self, query_bytes: bytes, target_bytes: bytes) -> float:
        q_vec = np.frombuffer(query_bytes, dtype=np.float32)
        t_vec = np.frombuffer(target_bytes, dtype=np.float32)
        # Never mix vectors from different models/dimensions. A mismatch is a
        # re-index signal, not something to paper over by truncating.
        if len(q_vec) != len(t_vec):
            return 0.0
        dot = float(np.dot(q_vec, t_vec))
        return round(dot, 4)
