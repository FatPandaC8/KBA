import pytest
import numpy as np
from server.app.application.use_cases import SemanticRecallUseCase
from server.app.application.ports import (
    KnowledgeRepositoryPort,
    EmbeddingRepositoryPort,
    EmbeddingProviderPort,
)
from server.app.domain.entities import KnowledgeItemEntity

class FakeKnowledgeRepo(KnowledgeRepositoryPort):
    def __init__(self, items):
        self.items = {i.id: i for i in items}
    def get_all(self, query="", limit=None, offset=0, user_id=None):
        return list(self.items.values())
    def get_by_id(self, item_id): return self.items.get(item_id)
    def get_by_capture_id(self, capture_id): return None
    def save(self, item): self.items[item.id] = item
    def count(self, query=""): return len(self.items)
    def delete(self, item_id): self.items.pop(item_id, None)

class FakeEmbeddingRepo(EmbeddingRepositoryPort):
    def __init__(self, embeddings):
        self.embeddings = embeddings  # dict of item_id -> bytes
    def get_all(self, user_id=None):
        return list(self.embeddings.items())
    def get_by_item_id(self, item_id): return self.embeddings.get(item_id)
    def save(self, item_id, vector_bytes): self.embeddings[item_id] = vector_bytes
    def delete(self, item_id): self.embeddings.pop(item_id, None)
    def count(self): return len(self.embeddings)

class FakeEmbedder(EmbeddingProviderPort):
    def embed_text(self, text: str) -> bytes:
        # Mock 4-dim unit vector
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        return v.tobytes()
    def embed_item(self, item: KnowledgeItemEntity) -> bytes:
        return self.embed_text(item.title)
    def calculate_similarity(self, q_bytes: bytes, t_bytes: bytes) -> float:
        q = np.frombuffer(q_bytes, dtype=np.float32)
        t = np.frombuffer(t_bytes, dtype=np.float32)
        return float(np.dot(q, t))

def test_semantic_recall_use_case():
    k1 = KnowledgeItemEntity.create(
        id="item-1",
        capture_id="c1",
        title="Exact Match Item",
        core_idea="Idea 1",
    )
    k2 = KnowledgeItemEntity.create(
        id="item-2",
        capture_id="c2",
        title="Orthogonal Item",
        core_idea="Idea 2",
    )

    # item-1 has high similarity [1, 0, 0, 0], item-2 has zero similarity [0, 1, 0, 0]
    embed_map = {
        "item-1": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32).tobytes(),
        "item-2": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32).tobytes(),
    }

    uc = SemanticRecallUseCase(
        knowledge_repo=FakeKnowledgeRepo([k1, k2]),
        embedding_repo=FakeEmbeddingRepo(embed_map),
        embedder=FakeEmbedder(),
    )

    results = uc.execute(query="Search query", user_id="", limit=10)
    assert len(results) == 2
    assert results[0].item.id == "item-1"
    assert results[0].similarity_score == 1.0
    assert results[1].item.id == "item-2"
    assert results[1].similarity_score == 0.0
