"""Composition root (ADR R7).

One Settings object, one persistence backend (PostgreSQL), no factory
branching. Repositories come from ``persistence.postgres.PostgresContainer``
(one process-wide pool per process). The FastAPI lifespan opens and closes
the pool; the API process is the only server process (pipeline split, S2).
"""

import logging
import secrets
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from server.app.adapters.outbound.embeddings import FastEmbedProvider
from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.adapters.outbound.extraction.groq import GroqExtractionAdapter
from server.app.adapters.outbound.identity import (
    GoogleTokenInfoVerifier,
    LogEmailAdapter,
)
from server.app.adapters.outbound.llm.factory import build_llm_client
from server.app.adapters.outbound.persistence.postgres import PostgresContainer
from server.app.adapters.outbound.providers import LocalProviderRegistry
from server.app.adapters.outbound.speech import FasterWhisperSpeechAdapter
from server.app.application.auth import AuthService, ConsentService
from server.app.application.use_cases import (
    AccountDeletionUseCase,
    AdminConsoleUseCase,
    AdminSystemStatusUseCase,
    BackfillEmbeddingsUseCase,
    DeleteCaptureUseCase,
    GraphQueryUseCase,
    ManageKnowledgeUseCase,
    ManageRelationshipsUseCase,
    PurgeRetainedAudioUseCase,
    SemanticRecallUseCase,
)
from server.app.adapters.outbound.persistence.postgres import UnitOfWork
from server.app.application.use_cases.text_kb import TextKBSettings, TextKBUseCase
from server.app.application.use_cases.ingest import name_similarity as name_similarity_lookup
from server.app.domain.entities import UserEntity
from server.app.domain.errors import AuthError
from server.app.infrastructure.config import ServerSettings, get_settings

security = HTTPBearer(auto_error=False)
logger = logging.getLogger("echo.container")


class Container:
    def __init__(self, settings: ServerSettings):
        self.settings = settings

        persistence = PostgresContainer(settings)
        self.persistence = persistence

        # Repositories (all bound to the one pool in `persistence.db`)
        self.knowledge_repo = persistence.knowledge_repo
        self.entity_repo = persistence.entity_repo
        self.rel_repo = persistence.rel_repo
        self.rel_type_repo = persistence.rel_type_repo
        self.duplicate_repo = persistence.duplicate_repo
        self.embedding_repo = persistence.embedding_repo
        self.capture_repo = persistence.capture_repo
        self.eval_repo = persistence.eval_repo
        self.user_repo = persistence.user_repo
        self.session_repo = persistence.session_repo
        self.email_token_repo = persistence.email_token_repo
        self.consent_repo = persistence.consent_repo
        self.tombstone_repo = persistence.tombstone_repo
        self.support_repo = persistence.support_repo
        self.audit_repo = persistence.audit_repo
        self.llm_usage_repo = persistence.llm_usage_repo
        self.app_settings_repo = persistence.app_settings_repo
        self.admin_repo = persistence.admin_repo
        self.db = persistence.db

        self._ai_config_restored = False
        self._restore_llm_prefs()

        # STT and embeddings stay local. Only text ever reaches a hosted LLM.
        self.embedder = FastEmbedProvider()
        self.transcriber = FasterWhisperSpeechAdapter()
        self.llm_client = build_llm_client(settings, self.llm_usage_repo)
        self.extractor = (
            GroqExtractionAdapter(
                self.llm_client,
                pipeline_version=settings.pipeline_version,
                repair_attempts=settings.llm_repair_attempts,
                max_prompt_chars=settings.llm_max_prompt_chars,
            )
            if self.llm_client is not None
            else SemanticKnowledgeExtractor(pipeline_version=settings.pipeline_version)
        )
        self.provider_registry = LocalProviderRegistry(settings)
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
            entity_repo=self.entity_repo,
        )
        self.consent_service = ConsentService(self.consent_repo, settings)

        # Use cases
        self.graph_query_uc = GraphQueryUseCase(
            entity_repo=self.entity_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            embedder=self.embedder,
            duplicate_repo=self.duplicate_repo,
            support_repo=self.support_repo,
            tombstone_repo=self.tombstone_repo,
        )
        # Pipeline split (S1/S2): synchronous Text-KB in the request; the
        # failure is stored on the capture row in a separate small tx (rule 5).
        self.ingestor = TextKBUseCase(
            capture_repo=self.capture_repo,
            knowledge_repo=self.knowledge_repo,
            entity_repo=self.entity_repo,
            rel_repo=self.rel_repo,
            duplicate_repo=self.duplicate_repo,
            embedding_repo=self.embedding_repo,
            embedder=self.embedder,
            support_repo=self.support_repo,
            tombstone_repo=self.tombstone_repo,
            extraction=self.extractor,
            settings=TextKBSettings(
                max_text_chars=settings.max_text_kb_chars,
                name_similarity_fn=name_similarity_lookup,
                auto_link_threshold=settings.duplicate_auto_link_threshold,
                flag_threshold=settings.duplicate_flag_threshold,
                relationship_registry=self.rel_type_repo,
                store_last_error=True,
                uow_factory=lambda: UnitOfWork(self.db.pool()),
            ),
        )

        def _store_capture_error(user_id: str, capture_id: str, error_text: str) -> None:
            self.capture_repo.mark_error(
                capture_id, user_id=user_id, error_text=error_text,
            )

        self.ingestor.on_capture_error = _store_capture_error
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
            relationship_type_repo=self.rel_type_repo,
        )
        self.backfill_embeddings_uc = BackfillEmbeddingsUseCase(
            knowledge_repo=self.knowledge_repo,
            embedding_repo=self.embedding_repo,
            embedder=self.embedder,
        )
        self.delete_capture_uc = DeleteCaptureUseCase(
            capture_repo=self.capture_repo,
            knowledge_repo=self.knowledge_repo,
            entity_repo=self.entity_repo,
            rel_repo=self.rel_repo,
            duplicate_repo=self.duplicate_repo,
            embedding_repo=self.embedding_repo,
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
            entity_repo=self.entity_repo,
            rel_repo=self.rel_repo,
            duplicate_repo=self.duplicate_repo,
            embedding_repo=self.embedding_repo,
            eval_repo=self.eval_repo,
            tombstone_repo=self.tombstone_repo,
            support_repo=self.support_repo,
            upload_dir=settings.upload_dir,
            audit_repo=self.audit_repo,
        )
        self.admin_status_uc = AdminSystemStatusUseCase(
            knowledge_repo=self.knowledge_repo,
            rel_repo=self.rel_repo,
            embedding_repo=self.embedding_repo,
            capture_repo=self.capture_repo,
            pipeline_version=settings.pipeline_version,
            upload_dir=settings.upload_dir,
        )

        self.admin_console_uc = AdminConsoleUseCase(
            admin_repo=self.admin_repo,
            auth_service=self.auth_service,
            user_repo=self.user_repo,
            account_delete=self.delete_account_uc,
            capture_delete=self.delete_capture_uc,
            entity_repo=self.entity_repo,
            ingestor=self.ingestor,
            upload_dir=settings.upload_dir,
            password_min_length=settings.password_min_length,
        )

    def open_database(self) -> None:
        """Open the pool explicitly (FastAPI lifespan startup)."""
        self.persistence.open_pool()

    def close_database(self) -> None:
        self.persistence.close_pool()

    def _restore_llm_prefs(self) -> None:
        """Admin runtime overrides survive a restart after a DB round-trip.

        Read lazily and only once; the env var remains the default and the
        persisted selection wins when an operator explicitly chose it.
        """
        if self._ai_config_restored:
            return
        self._ai_config_restored = True
        try:
            stored_provider = self.app_settings_repo.get("llm_provider")
            stored_model = self.app_settings_repo.get("llm_model")
        except Exception:
            return
        if stored_provider:
            self.settings.llm_provider = stored_provider.strip().lower()
        if stored_model:
            self.settings.groq_model = stored_model.strip()

    def ai_config(self) -> Dict[str, Any]:
        """Admin-visible AI configuration. Never includes the API key."""
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        usage = self.llm_usage_repo.usage_since(since)
        return {
            "provider": self.settings.llm_provider,
            "model": self.settings.llm_model,
            "provider_available": self.settings.llm_provider_available,
            "key_configured": bool(self.settings.groq_api_key),
            "local_only": self.llm_client is None,
            "limits": self.settings.llm_limits(),
            "consent_version": self.settings.effective_consent_version,
            "last_24h_calls": usage["calls"],
            "last_24h_tokens": usage["total_tokens"],
            "recent_calls": self.llm_usage_repo.last_calls(10),
            "providers": [
                {"provider": "rule_based", "model": "", "available": True, "hosted": False},
                {
                    "provider": "groq",
                    "model": self.settings.groq_model,
                    "available": bool(self.settings.groq_api_key),
                    "hosted": True,
                },
            ],
        }

    def configure_llm(self, provider: str, model: str) -> Dict[str, Any]:
        from server.app.domain.errors import ValidationError

        provider = (provider or "").strip().lower()
        model = (model or "").strip()
        allowed = {"rule_based", "groq"}
        if self.settings.app_env == "test":
            allowed.add("fake")
        if provider not in allowed:
            raise ValidationError(f"Unsupported LLM provider: {provider!r}")
        if provider == "groq" and not self.settings.groq_api_key:
            raise ValidationError(
                "GROQ_API_KEY is not configured on the server; refusing to select Groq."
            )
        if provider == "groq" and not model:
            raise ValidationError("A model name is required when selecting Groq.")

        previous_provider, previous_model = self.settings.llm_provider, self.settings.groq_model
        self.settings.llm_provider = provider
        if model:
            self.settings.groq_model = model
        try:
            client = build_llm_client(self.settings, self.llm_usage_repo)
        except Exception:
            self.settings.llm_provider = previous_provider
            self.settings.groq_model = previous_model
            raise

        self.llm_client = client
        self.extractor = (
            GroqExtractionAdapter(
                client,
                pipeline_version=self.settings.pipeline_version,
                repair_attempts=self.settings.llm_repair_attempts,
                max_prompt_chars=self.settings.llm_max_prompt_chars,
            )
            if client is not None
            else SemanticKnowledgeExtractor(
                pipeline_version=self.settings.pipeline_version
            )
        )
        # Use cases hold references; swap the adapters in place so a running
        # instance picks up the new provider without a restart.
        self.ingestor.extraction = self.extractor
        self.manage_knowledge_uc.extractor = self.extractor
        self.provider_registry.settings = self.settings

        self.app_settings_repo.set("llm_provider", provider)
        self.app_settings_repo.set("llm_model", self.settings.llm_model)
        logger.info(
            "ai_config_changed provider=%s model=%s",
            provider,
            self.settings.llm_model,
        )
        return self.ai_config()

    def test_llm(self) -> Dict[str, Any]:
        """Minimal provider call for ADM-07. Returns status, never the key."""
        from server.app.adapters.outbound.llm.validation import (
            TEST_SCHEMA,
            TEST_SCHEMA_NAME,
        )
        from server.app.domain.errors import (
            ProviderError,
            ProviderNetworkError,
            ProviderSchemaError,
            QuotaExhaustedError,
        )

        if self.llm_client is None:
            return {
                "ok": True,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": False,
                "detail": "Local rule-based provider selected; no hosted call is made.",
            }
        try:
            response = self.llm_client.complete_json(
                operation="admin_test",
                system="Return the JSON object {\"ok\": true} and nothing else.",
                user="ping",
                schema=TEST_SCHEMA,
                schema_name=TEST_SCHEMA_NAME,
                max_tokens=128,
                temperature=0.0,
            )
            return {
                "ok": True,
                "provider": response.provider,
                "model": response.model,
                "network_call": True,
                "total_tokens": response.total_tokens,
                "latency_ms": response.latency_ms,
                "detail": "Provider answered successfully.",
            }
        except QuotaExhaustedError as exc:
            return {
                "ok": False,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": True,
                "error_class": "quota_exhausted",
                "retry_after": getattr(exc, "retry_after", 0),
                "detail": str(exc),
            }
        except ProviderSchemaError as exc:
            return {
                "ok": False,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": True,
                "error_class": "schema_invalid",
                "detail": str(exc),
            }
        except ProviderNetworkError as exc:
            return {
                "ok": False,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": True,
                "error_class": "network_error",
                "detail": str(exc),
            }
        except ProviderError as exc:
            return {
                "ok": False,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": True,
                "error_class": getattr(exc, "error_class", "provider_failure"),
                "detail": str(exc),
            }
        except Exception as exc:  # never leak a traceback to the admin UI
            logger.warning("ai_test_failed error=%s", type(exc).__name__)
            return {
                "ok": False,
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "network_call": True,
                "error_class": "unknown",
                "detail": "The provider test failed.",
            }


_CONTAINER: Optional[Container] = None


def get_container() -> Container:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = Container(get_settings())
    return _CONTAINER


def reset_container() -> None:
    """For tests: drop the singleton so a new DATABASE_URL is honoured."""
    global _CONTAINER
    _CONTAINER = None


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
