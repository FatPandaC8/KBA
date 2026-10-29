import secrets
from typing import Optional

from fastapi import Header, HTTPException, Security
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
    SqliteUserRepository,
    SqliteSessionRepository,
    SqliteEmailTokenRepository,
    SqliteConsentRepository,
    SqliteTombstoneRepository,
    SqliteRecordSupportRepository,
)
from server.app.adapters.outbound.embeddings import FastEmbedProvider
from server.app.adapters.outbound.speech import FasterWhisperSpeechAdapter
from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.adapters.outbound.identity import LogEmailAdapter, GoogleTokenInfoVerifier
from server.app.application.use_cases import (
    ProcessAudioCaptureUseCase,
    SemanticRecallUseCase,
    ManageKnowledgeUseCase,
    ManageRelationshipsUseCase,
    BackfillEmbeddingsUseCase,
    AdminSystemStatusUseCase,
    DeleteCaptureUseCase,
    PurgeRetainedAudioUseCase,
    AccountDeletionUseCase,
)
from server.app.application.auth import AuthService, ConsentService
from server.app.domain.entities import UserEntity
from server.app.domain.errors import AuthError

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
        self.user_repo = SqliteUserRepository(self.db_manager)
        self.session_repo = SqliteSessionRepository(self.db_manager)
        self.email_token_repo = SqliteEmailTokenRepository(self.db_manager)
        self.consent_repo = SqliteConsentRepository(self.db_manager)
        self.tombstone_repo = SqliteTombstoneRepository(self.db_manager)
        self.support_repo = SqliteRecordSupportRepository(self.db_manager)

        # Free/local AI adapters only. No paid provider or paid fallback exists.
        self.embedder = FastEmbedProvider()
        self.transcriber = FasterWhisperSpeechAdapter()
        self.extractor = SemanticKnowledgeExtractor(pipeline_version=settings.pipeline_version)
        self.email_port = LogEmailAdapter(settings.email_outbox_path)
        self.google_verifier = GoogleTokenInfoVerifier(settings.google_client_id)

        # Auth services
        self.auth_service = AuthService(
            user_repo=self.user_repo,
            session_repo=self.session_repo,
            email_token_repo=self.email_token_repo,
            email_port=self.email_port,
            google_verifier=self.google_verifier,
            settings=settings,
        )
        self.consent_service = ConsentService(self.consent_repo, settings)

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
        self.delete_capture_uc = DeleteCaptureUseCase(
            capture_repo=self.capture_repo,
            knowledge_repo=self.knowledge_repo,
            job_repo=self.job_repo,
            eval_repo=self.eval_repo,
            support_repo=self.support_repo,
            upload_dir=settings.upload_dir,
        )
        self.purge_audio_uc = PurgeRetainedAudioUseCase(
            capture_repo=self.capture_repo,
            upload_dir=settings.upload_dir,
        )
        self.delete_account_uc = AccountDeletionUseCase(
            user_repo=self.user_repo,
            session_repo=self.session_repo,
            email_token_repo=self.email_token_repo,
            consent_repo=self.consent_repo,
            capture_repo=self.capture_repo,
            knowledge_repo=self.knowledge_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            job_repo=self.job_repo,
            eval_repo=self.eval_repo,
            tombstone_repo=self.tombstone_repo,
            support_repo=self.support_repo,
            upload_dir=settings.upload_dir,
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


_CONTAINER: Optional[Container] = None


def get_container() -> Container:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = Container(get_settings())
    return _CONTAINER


def _extract_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    header_token: Optional[str],
) -> Optional[str]:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return header_token


def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_client_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
) -> str:
    token = _extract_bearer_token(credentials, x_client_token)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def get_current_user(token: str = Security(get_bearer_token)) -> UserEntity:
    container = get_container()
    try:
        return container.auth_service.authenticate(token)
    except AuthError:
        raise HTTPException(
            status_code=401,
            detail="Session is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_verified_user(user: UserEntity = Security(get_current_user)) -> UserEntity:
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Verify your email before creating records.",
        )
    return user


def require_current_consent(user: UserEntity = Security(require_verified_user)) -> UserEntity:
    container = get_container()
    if not container.consent_service.has_current_consent(user.id):
        raise HTTPException(
            status_code=403,
            detail="AI provider consent is required before recording.",
        )
    return user


def verify_admin_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> bool:
    settings = get_settings()
    expected = settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin authentication is not configured on this server.",
        )
    token = _extract_bearer_token(credentials, x_admin_token)
    if not token or not secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: valid admin token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True
