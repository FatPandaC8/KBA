import os
import json
import urllib.request
import numpy as np
from typing import Optional
from server.app.application.ports import EmbeddingProviderPort
from server.app.domain.entities import KnowledgeItemEntity

_GLOBAL_EMBED_MODEL = None

def get_embed_model():
    """Lazily load fastembed bge-small-en-v1.5 model on CPU for local embeddings."""
    global _GLOBAL_EMBED_MODEL
    if _GLOBAL_EMBED_MODEL is None:
        try:
            from fastembed import TextEmbedding
            _GLOBAL_EMBED_MODEL = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        except Exception as e:
            print(f"[Embedding] Warning: Failed to load fastembed model: {e}")
            _GLOBAL_EMBED_MODEL = None
    return _GLOBAL_EMBED_MODEL

class FastEmbedProvider(EmbeddingProviderPort):
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed_text(self, text: str) -> bytes:
        clean = text.strip()
        if not clean:
            return np.zeros(384, dtype=np.float32).tobytes()

        # Try remote OpenAI embedding if API key is provided
        if self.api_key:
            try:
                payload = {
                    "input": clean,
                    "model": self.model
                }
                req = urllib.request.Request(
                    f"{self.base_url}/embeddings",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=10) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    raw_vec = data["data"][0]["embedding"]
                    vec = np.array(raw_vec, dtype=np.float32)
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                    return vec.tobytes()
            except Exception as e:
                print(f"[Embedding] Remote embedding failed: {e}. Falling back to local fastembed.")

        # Local fastembed model
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
        # If dimensions match, compute dot product (cosine similarity since normalized)
        if len(q_vec) != len(t_vec):
            # Pad or truncate if dimensions differ due to different models
            min_len = min(len(q_vec), len(t_vec))
            q_vec = q_vec[:min_len]
            t_vec = t_vec[:min_len]
        dot = float(np.dot(q_vec, t_vec))
        return round(dot, 4)
