import os
import sqlite3
import threading
from typing import Optional

_LOCAL = threading.local()

_USER_SCOPED_TABLES = (
    "captures",
    "knowledge_items",
    "entities",
    "relationships",
    "knowledge_embeddings",
    "processing_jobs",
    "model_eval_records",
    "conversations",
    "messages",
    "answer_citations",
    "duplicate_candidates",
)


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        # Use thread-local connection for clean pooling per thread
        conn = getattr(_LOCAL, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign key constraints for high concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            _LOCAL.conn = conn
        return conn

    def init_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                email_normalized TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                email_verified_at TEXT,
                is_locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT,
                expires_at TEXT,
                revoked_at TEXT,
                last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS email_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT,
                expires_at TEXT,
                used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS consents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                version TEXT NOT NULL,
                providers_hash TEXT NOT NULL,
                providers_json TEXT NOT NULL,
                granted INTEGER NOT NULL,
                created_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tombstones (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                normalized_key TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(user_id, kind, normalized_key)
            );

            CREATE TABLE IF NOT EXISTS record_supports (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(record_id, target_kind, target_id)
            );

            CREATE TABLE IF NOT EXISTS captures (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                idempotency_key TEXT NOT NULL,
                audio_path TEXT,
                duration_ms INTEGER,
                status TEXT,
                created_at TEXT,
                UNIQUE(user_id, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS knowledge_items (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                capture_id TEXT,
                title TEXT,
                core_idea TEXT,
                details TEXT DEFAULT '',
                transcript TEXT,
                concepts TEXT,
                tags TEXT,
                open_questions TEXT,
                candidate_relations TEXT DEFAULT '[]',
                provenance TEXT,
                user_edited INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                capture_id TEXT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'concept',
                description TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                certainty TEXT NOT NULL DEFAULT 'confirmed',
                provenance TEXT NOT NULL DEFAULT 'voice-capture',
                provider_id TEXT NOT NULL DEFAULT '',
                model_version TEXT NOT NULL DEFAULT '',
                user_edited INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                from_id TEXT,
                to_id TEXT,
                relation_type TEXT,
                status TEXT,
                confidence REAL NOT NULL DEFAULT 0.6,
                certainty TEXT NOT NULL DEFAULT 'confirmed',
                source_capture_id TEXT NOT NULL DEFAULT '',
                provenance TEXT NOT NULL DEFAULT 'voice-capture',
                user_edited INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                UNIQUE(user_id, from_id, to_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS model_eval_records (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                capture_id TEXT,
                transcript TEXT,
                structured_json TEXT,
                user_corrected INTEGER DEFAULT 0,
                consent_given INTEGER DEFAULT 0,
                pipeline_version TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                item_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                embedding BLOB,
                model_name TEXT NOT NULL DEFAULT '',
                dimension INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS processing_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                capture_id TEXT,
                stage TEXT,
                status TEXT,
                attempt INTEGER NOT NULL DEFAULT 0,
                error_class TEXT NOT NULL DEFAULT '',
                lease_owner TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT '',
                stage_outputs TEXT NOT NULL DEFAULT '{}',
                duration_ms INTEGER,
                error_message TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS duplicate_candidates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                score REAL NOT NULL,
                decision TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(user_id, entity_id, candidate_id)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ready',
                error_class TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS answer_citations (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                name_snapshot TEXT NOT NULL DEFAULT '',
                created_at TEXT,
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
            );
            """
        )

        self._migrate_legacy_tables(c)

        # Performance optimization: strategic query indexes
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created_at ON knowledge_items(created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_capture_id ON knowledge_items(capture_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_user ON knowledge_items(user_id, created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_from_to ON relationships(from_id, to_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_status ON relationships(status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_user ON relationships(user_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_captures_created ON captures(created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_captures_user ON captures(user_id, created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_eval_consent ON model_eval_records(consent_given);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_capture ON processing_jobs(capture_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_user ON processing_jobs(user_id, created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_email_tokens_token ON email_tokens(token_hash);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_consents_user ON consents(user_id, created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_record_supports_record ON record_supports(record_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_record_supports_target ON record_supports(user_id, target_kind, target_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entities_user_name ON entities(user_id, normalized_name);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entities_capture ON entities(capture_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entities_user_type ON entities(user_id, entity_type);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_capture ON relationships(source_capture_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_answer_citations_message ON answer_citations(message_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_answer_citations_user ON answer_citations(user_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_user ON duplicate_candidates(user_id, decision);")

        conn.commit()
        conn.close()

    @staticmethod
    def _column_exists(c: sqlite3.Cursor, table: str, column: str) -> bool:
        rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _migrate_legacy_tables(self, c: sqlite3.Cursor) -> None:
        """Bring databases created before the ownership model up to date.

        Development data may be reset, but a migration must never destroy it.
        Legacy rows are retained with an empty ``user_id`` and are therefore
        invisible to every authenticated user.
        """
        # ``captures`` has a legacy UNIQUE(idempotency_key) constraint that
        # cannot be relaxed with ALTER TABLE, so rebuild it once.
        if not self._column_exists(c, "captures", "user_id"):
            c.execute("ALTER TABLE captures RENAME TO captures_legacy")
            c.execute(
                """
                CREATE TABLE captures (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL,
                    audio_path TEXT,
                    duration_ms INTEGER,
                    status TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, idempotency_key)
                );
                """
            )
            c.execute(
                """
                INSERT INTO captures (id, user_id, idempotency_key, audio_path, duration_ms, status, created_at)
                SELECT id, '', idempotency_key, audio_path, duration_ms, status, created_at FROM captures_legacy
                """
            )
            c.execute("DROP TABLE captures_legacy")

        additions = {
            "knowledge_items": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
                "user_edited": "INTEGER NOT NULL DEFAULT 0",
                "provider_id": "TEXT NOT NULL DEFAULT ''",
                "model_version": "TEXT NOT NULL DEFAULT ''",
            },
            "relationships": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
                "user_edited": "INTEGER NOT NULL DEFAULT 0",
                "confidence": "REAL NOT NULL DEFAULT 0.6",
                "certainty": "TEXT NOT NULL DEFAULT 'confirmed'",
                "source_capture_id": "TEXT NOT NULL DEFAULT ''",
                "provenance": "TEXT NOT NULL DEFAULT 'voice-capture'",
            },
            "knowledge_embeddings": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
                "model_name": "TEXT NOT NULL DEFAULT ''",
                "dimension": "INTEGER NOT NULL DEFAULT 0",
            },
            "processing_jobs": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
                "attempt": "INTEGER NOT NULL DEFAULT 0",
                "error_class": "TEXT NOT NULL DEFAULT ''",
                "lease_owner": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
                "stage_outputs": "TEXT NOT NULL DEFAULT '{}'",
            },
            "model_eval_records": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
            },
        }

        for table, columns in additions.items():
            for column, ddl in columns.items():
                if not self._column_exists(c, table, column):
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
