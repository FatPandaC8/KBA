class DomainError(Exception):
    """Base exception for all domain errors."""
    pass

class EntityNotFoundError(DomainError):
    """Raised when a domain entity is not found."""
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(f"{entity_name} with id '{entity_id}' not found.")
        self.entity_name = entity_name
        self.entity_id = entity_id

class ValidationError(DomainError):
    """Raised when domain constraints or invariants are violated."""
    pass

class AudioProcessingError(DomainError):
    """Raised when audio capture, decoding, or transcription fails."""
    pass
