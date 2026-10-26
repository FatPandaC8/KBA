import os
from functools import lru_cache
from fastapi import Header, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from server.app.infrastructure.config import get_settings, ServerSettings
from server.app.infrastructure.database import DatabaseManager
from server.app.adapters.outbound.persistence import (
    SqliteKnowledgeRepository,
    SqliteRelationshipRepository,
    SqliteEmbeddingRepository,
    SqliteCaptureRepository,
    SqliteEvalRecordRepository,
    SqliteJobStatusRepository,
)
from server.app.adapters.outbound.embeddings import FastEmbedProvider
from server.app.adapters.outbound.speech import FasterWhisperSpeechAdapter
from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.application.use_cases import (
    ProcessAudioCaptureUseCase,
    SemanticRecallUseCase,
    ManageKnowledgeUseCase,
    ManageRelationshipsUseCase,
    BackfillEmbeddingsUseCase,
    AdminSystemStatusUseCase,
)

security = HTTPBearer(auto_error=False)

class Container:
    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.db_manager = DatabaseManager(settings.db_path)
        self.db_manager.init_database()

        # Repositories
        self.knowledge_repo = SqliteKnowledgeRepository(self.db_manager)
        self.rel_repo = SqliteRelationshipRepository(self.db_manager)
        self.embedding_repo = SqliteEmbeddingRepository(self.db_manager)
        self.capture_repo = SqliteCaptureRepository(self.db_manager)
        self.eval_repo = SqliteEvalRecordRepository(self.db_manager)
        self.job_repo = SqliteJobStatusRepository(self.db_manager)

        # External Adapters
        self.embedder = FastEmbedProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.transcriber = FasterWhisperSpeechAdapter(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.extractor = SemanticKnowledgeExtractor(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            pipeline_version=settings.pipeline_version,
        )

        # Use cases
        self.process_audio_uc = ProcessAudioCaptureUseCase(
            capture_repo=self.capture_repo,
            knowledge_repo=self.knowledge_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            job_repo=self.job_repo,
            transcriber=self.transcriber,
            extractor=self.extractor,
            embedder=self.embedder,
            upload_dir=settings.upload_dir,
        )
        self.semantic_recall_uc = SemanticRecallUseCase(
            knowledge_repo=self.knowledge_repo,
            embedding_repo=self.embedding_repo,
            embedder=self.embedder,
        )
        self.manage_knowledge_uc = ManageKnowledgeUseCase(
            knowledge_repo=self.knowledge_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            extractor=self.extractor,
            embedder=self.embedder,
        )
        self.manage_relationships_uc = ManageRelationshipsUseCase(
            rel_repo=self.rel_repo,
        )
        self.backfill_embeddings_uc = BackfillEmbeddingsUseCase(
            knowledge_repo=self.knowledge_repo,
            embedding_repo=self.embedding_repo,
            embedder=self.embedder,
        )
        self.admin_status_uc = AdminSystemStatusUseCase(
            knowledge_repo=self.knowledge_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            capture_repo=self.capture_repo,
            job_repo=self.job_repo,
            pipeline_version=settings.pipeline_version,
            upload_dir=settings.upload_dir,
        )

_CONTAINER: Container = None

def get_container() -> Container:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = Container(get_settings())
    return _CONTAINER

def verify_admin_auth(
    credentials: HTTPAuthorizationCredentials = Security(security),
    x_admin_token: str = Header(default=None, alias="X-Admin-Token")
) -> bool:
    settings = get_settings()
    expected_token = settings.admin_token

    # Check Bearer token or X-Admin-Token header
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif x_admin_token:
        token = x_admin_token

    if not token or token != expected_token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid admin token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True
