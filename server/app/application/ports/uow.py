"""Unit of Work port (ADR R1).

``with uow:`` binds repositories to ONE connection/transaction. Commit on
clean exit, rollback on exception. Repositories never commit; use cases never
see a connection or SQL.
"""

from abc import ABC, abstractmethod


class UnitOfWorkPort(ABC):
    @abstractmethod
    def __enter__(self) -> "UnitOfWorkPort":
        """Open the transaction; every repo call joins it."""

    @abstractmethod
    def __exit__(self, exc_type, exc, tb) -> bool:
        """Commit when clean, rollback on any exception, always release."""

    @abstractmethod
    def commit(self) -> None:
        """Explicit early commit inside the block (rare)."""

    @abstractmethod
    def rollback(self) -> None:
        """Explicit rollback; the block exit still releases the connection."""
