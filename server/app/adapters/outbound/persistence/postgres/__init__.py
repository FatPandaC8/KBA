"""PostgreSQL persistence adapter package.

One module per port (ADR R2). ``PostgresContainer`` wires every repository to
one ``Database`` (process-wide pool). No factory branching: this is the only
persistence adapter in the codebase.
"""

import os

from server.app.infrastructure.config import get_settings

from .admin_reads import (
    PostgresAdminAuditLogRepository,
    PostgresAdminRepository,
    PostgresAppSettingsRepository,
    PostgresLLMUsageRepository,
)
from .bookkeeping import (
    PostgresDuplicateRepository,
    PostgresSupportRepository,
    PostgresTombstoneRepository,
)
from .captures import PostgresCaptureRepository, PostgresEvalRecordRepository
from .conn import Database, UnitOfWork, transaction
from .entities import PostgresEntityRepository
from .jobs import PostgresJobRepository
from .knowledge import PostgresEmbeddingRepository, PostgresKnowledgeRepository
from .relationships import (
    PostgresRelationshipRepository,
    PostgresRelationshipTypeRegistry,
)
from .sessions import (
    PostgresConsentRepository,
    PostgresEmailTokenRepository,
    PostgresSessionRepository,
)
from .users import PostgresUserRepository

__all__ = [
    "Database",
    "UnitOfWork",
    "transaction",
    "PostgresContainer",
    "PostgresAdminAuditLogRepository",
    "PostgresAdminRepository",
    "PostgresAppSettingsRepository",
    "PostgresCaptureRepository",
    "PostgresConsentRepository",
    "PostgresDuplicateRepository",
    "PostgresEmailTokenRepository",
    "PostgresEmbeddingRepository",
    "PostgresEntityRepository",
    "PostgresEvalRecordRepository",
    "PostgresJobRepository",
    "PostgresKnowledgeRepository",
    "PostgresLLMUsageRepository",
    "PostgresRelationshipRepository",
    "PostgresRelationshipTypeRegistry",
    "PostgresSessionRepository",
    "PostgresSupportRepository",
    "PostgresTombstoneRepository",
    "PostgresUserRepository",
]


class PostgresContainer:
    """All repositories over one shared pool (composition root helper)."""

    def __init__(self, settings=None):
        if settings is None:
            settings = get_settings()
        # In tests each xdist worker sets DATABASE_URL before construction; a
        # stale process-level Database must not survive that switch.
        url = settings.database_url
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not configured (see .env.example). PostgreSQL "
                "is the only database driver in this codebase."
            )
        self.db = Database(settings)
        self._url = url

        self.user_repo = PostgresUserRepository(self.db)
        self.session_repo = PostgresSessionRepository(self.db)
        self.email_token_repo = PostgresEmailTokenRepository(self.db)
        self.consent_repo = PostgresConsentRepository(self.db)
        self.capture_repo = PostgresCaptureRepository(self.db)
        self.knowledge_repo = PostgresKnowledgeRepository(self.db)
        self.entity_repo = PostgresEntityRepository(self.db)
        self.rel_repo = PostgresRelationshipRepository(self.db)
        self.rel_type_repo = PostgresRelationshipTypeRegistry(self.db)
        self.duplicate_repo = PostgresDuplicateRepository(self.db)
        self.tombstone_repo = PostgresTombstoneRepository(self.db)
        self.support_repo = PostgresSupportRepository(self.db)
        self.job_repo = PostgresJobRepository(self.db)
        self.embedding_repo = PostgresEmbeddingRepository(self.db)
        self.eval_repo = PostgresEvalRecordRepository(self.db)
        self.audit_repo = PostgresAdminAuditLogRepository(self.db)
        self.llm_usage_repo = PostgresLLMUsageRepository(self.db)
        self.app_settings_repo = PostgresAppSettingsRepository(self.db)
        self.admin_repo = PostgresAdminRepository(self.db)

    @classmethod
    def from_settings(cls) -> "PostgresContainer":
        return cls()

    def open_pool(self) -> None:
        self.db.open()

    def close_pool(self) -> None:
        self.db.close()

    def unit_of_work(self):
        """Unit of work binding ALL repos to one transaction (R1)."""
        return self.db.unit_of_work()
