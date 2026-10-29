"""Ask AI: GraphRAG retrieval, conversations and display-only citations (QA)."""

import uuid
from typing import Dict, List, Optional

from server.app.application.dto import (
    AnswerDraft,
    AnswerDTO,
    CitationDTO,
    ConversationDTO,
    EvidenceItem,
    MessageDTO,
)
from server.app.application.ports import (
    AnswerProviderPort,
    CitationRepositoryPort,
    ConversationRepositoryPort,
    EmbeddingProviderPort,
    EmbeddingRepositoryPort,
    EntityRepositoryPort,
    MessageRepositoryPort,
    RelationshipRepositoryPort,
)
from server.app.domain.entities import (
    CitationEntity,
    ConversationEntity,
    MessageEntity,
    current_utc_iso,
)
from server.app.domain.errors import (
    EntityNotFoundError,
    ProviderError,
    ProviderNetworkError,
    QuotaExhaustedError,
    ValidationError,
)
from server.app.domain.value_objects import Certainty, ErrorClass

from .graph import GraphQueryUseCase

_MIN_SCORE = 0.12
_MAX_EVIDENCE = 24


class AskQuestionUseCase:
    def __init__(
        self,
        conversation_repo: ConversationRepositoryPort,
        message_repo: MessageRepositoryPort,
        citation_repo: CitationRepositoryPort,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        embedder: EmbeddingProviderPort,
        answerer: AnswerProviderPort,
        graph_query: GraphQueryUseCase,
    ):
        self.conversation_repo = conversation_repo
        self.message_repo = message_repo
        self.citation_repo = citation_repo
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.embedding_repo = embedding_repo
        self.embedder = embedder
        self.answerer = answerer
        self.graph_query = graph_query

    # ----------------------------------------------------------- conversations
    def list_conversations(self, user_id: str) -> List[ConversationDTO]:
        return [
            ConversationDTO(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            for conversation in self.conversation_repo.list_for_user(user_id)
        ]

    def get_conversation(self, user_id: str, conversation_id: str) -> ConversationDTO:
        conversation = self.conversation_repo.get_by_id(conversation_id, user_id)
        if not conversation:
            raise EntityNotFoundError("Conversation", conversation_id)
        messages = [
            self._message_to_dto(message, user_id)
            for message in self.message_repo.list_for_conversation(conversation_id, user_id)
        ]
        return ConversationDTO(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=messages,
        )

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        if not self.conversation_repo.get_by_id(conversation_id, user_id):
            raise EntityNotFoundError("Conversation", conversation_id)
        for message in self.message_repo.list_for_conversation(conversation_id, user_id):
            self.citation_repo.delete_for_message(message.id, user_id)
        self.message_repo.delete_for_conversation(conversation_id, user_id)
        self.conversation_repo.delete(conversation_id, user_id)

    # -------------------------------------------------------------------- ask
    def ask(self, user_id: str, question: str, conversation_id: Optional[str] = None) -> AnswerDTO:
        question_text = (question or "").strip()
        if not question_text:
            raise ValidationError("Question cannot be empty")
        if len(question_text) > 1000:
            raise ValidationError("Question is too long")

        conversation = self._conversation_for(user_id, conversation_id, question_text)
        self._save_message(MessageEntity(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            user_id=user_id,
            role="user",
            content=question_text,
        ))

        try:
            evidence, contradictions = self._retrieve(user_id, question_text)
        except Exception as exc:  # retrieval failure must be explicit (QA-05)
            return self._failed_answer(conversation, user_id, exc, "retrieval_failed")

        try:
            draft = self.answerer.answer(question_text, evidence, contradictions)
            self._validate_draft(draft)
        except QuotaExhaustedError as exc:
            return self._failed_answer(conversation, user_id, exc, ErrorClass.QUOTA_EXHAUSTED)
        except ProviderNetworkError as exc:
            return self._failed_answer(conversation, user_id, exc, ErrorClass.NETWORK)
        except ProviderError as exc:
            return self._failed_answer(conversation, user_id, exc, ErrorClass.PROVIDER)
        except Exception as exc:
            return self._failed_answer(conversation, user_id, exc, ErrorClass.PROVIDER)

        message = self._save_message(MessageEntity(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=draft.text,
            status="ready",
        ))
        citations = self._save_citations(user_id, message.id, draft, evidence)
        self.conversation_repo.touch(conversation.id, user_id)
        return AnswerDTO(
            conversation_id=conversation.id,
            message=self._message_to_dto(message, user_id, citations),
            facts=draft.facts,
            inferences=draft.inferences,
            contradictions=draft.contradictions,
            refused=draft.refused,
            refusal_reason=draft.refusal_reason,
        )

    # -------------------------------------------------------------- retrieval
    def _retrieve(self, user_id: str, question: str):
        search = self.graph_query.search(user_id, question, limit=10)
        entities = {entity.id: entity for entity in self.entity_repo.get_all(user_id=user_id)}
        evidence: Dict[tuple, EvidenceItem] = {}

        def add(item: EvidenceItem) -> None:
            key = (item.kind, item.target_id)
            existing = evidence.get(key)
            if existing is None or item.score > existing.score:
                evidence[key] = item

        for scored in search.entities:
            add(EvidenceItem(
                kind="entity",
                target_id=scored.entity.id,
                name=scored.entity.name,
                entity_type=scored.entity.entity_type,
                description=scored.entity.description,
                certainty=scored.entity.certainty,
                confidence=scored.entity.confidence,
                score=scored.score,
                source_capture_id=scored.entity.capture_id,
            ))

        contradictions: List[str] = []
        frontier = [scored.entity.id for scored in search.entities[:5]]
        seen_relationships = set()
        for rel in search.relationships:
            source = entities.get(rel.from_id)
            target = entities.get(rel.to_id)
            if not source or not target:
                continue
            seen_relationships.add(rel.id)
            add(EvidenceItem(
                kind="relationship",
                target_id=rel.id,
                name=source.name,
                related_name=target.name,
                relation_type=rel.relation_type,
                certainty=rel.certainty,
                confidence=rel.confidence,
                score=0.8,
            ))
            if rel.certainty == Certainty.CONFLICTING:
                contradictions.append(
                    f"{source.name} {rel.relation_type.lower()} {target.name}"
                )

        # Follow one hop so multi-hop questions have the connecting nodes.
        for entity_id in frontier:
            for rel in self.rel_repo.list_for_entity(user_id, entity_id)[:8]:
                if rel.id in seen_relationships:
                    continue
                seen_relationships.add(rel.id)
                source = entities.get(rel.from_id)
                target = entities.get(rel.to_id)
                if not source or not target:
                    continue
                add(EvidenceItem(
                    kind="relationship",
                    target_id=rel.id,
                    name=source.name,
                    related_name=target.name,
                    relation_type=rel.relation_type,
                    certainty=rel.certainty,
                    confidence=rel.confidence,
                    score=0.45,
                ))
                for entity in (source, target):
                    add(EvidenceItem(
                        kind="entity",
                        target_id=entity.id,
                        name=entity.name,
                        entity_type=entity.entity_type,
                        description=entity.description,
                        certainty=entity.certainty,
                        confidence=entity.confidence,
                        score=0.4,
                        source_capture_id=entity.capture_id,
                    ))
                if rel.certainty == Certainty.CONFLICTING:
                    contradictions.append(
                        f"{source.name} {rel.relation_type.lower()} {target.name}"
                    )

        ordered = sorted(evidence.values(), key=lambda item: item.score, reverse=True)
        return ordered[:_MAX_EVIDENCE], sorted(set(contradictions))

    # ---------------------------------------------------------------- helpers
    def _conversation_for(
        self, user_id: str, conversation_id: Optional[str], question: str
    ) -> ConversationEntity:
        if conversation_id:
            conversation = self.conversation_repo.get_by_id(conversation_id, user_id)
            if not conversation:
                raise EntityNotFoundError("Conversation", conversation_id)
            return conversation
        now = current_utc_iso()
        conversation = ConversationEntity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=question[:60],
            created_at=now,
            updated_at=now,
        )
        self.conversation_repo.save(conversation)
        return conversation

    def _save_message(self, message: MessageEntity) -> MessageEntity:
        self.message_repo.save(message)
        return message

    def _save_citations(
        self, user_id: str, message_id: str, draft: AnswerDraft, evidence: List[EvidenceItem]
    ) -> List[CitationEntity]:
        citations = list(draft.citations)
        if not citations:
            citations = [
                CitationDTO(
                    id=str(uuid.uuid4()),
                    kind=item.kind,
                    target_id=item.target_id,
                    name=item.name,
                )
                for item in evidence[:6]
            ]
        saved: List[CitationEntity] = []
        for citation in citations:
            entity = CitationEntity(
                id=str(uuid.uuid4()),
                message_id=message_id,
                user_id=user_id,
                kind=citation.kind,
                target_id=citation.target_id,
                name_snapshot=citation.name,
            )
            self.citation_repo.save(entity)
            saved.append(entity)
        return saved

    def _validate_draft(self, draft: AnswerDraft) -> None:
        if not isinstance(draft, AnswerDraft):
            raise ProviderError("Malformed provider response")
        if not isinstance(draft.text, str) or not draft.text.strip():
            raise ProviderError("Malformed provider response")
        for field in (draft.facts, draft.inferences, draft.contradictions, draft.citations):
            if not isinstance(field, list):
                raise ProviderError("Malformed provider response")

    def _failed_answer(
        self, conversation: ConversationEntity, user_id: str, exc: Exception, error_class: str
    ) -> AnswerDTO:
        message = self._save_message(MessageEntity(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content="",
            status="failed",
            error_class=error_class,
            error_message=str(exc),
        ))
        self.conversation_repo.touch(conversation.id, user_id)
        detail = {
            ErrorClass.QUOTA_EXHAUSTED: "The free provider quota is exhausted. Try again later.",
            ErrorClass.NETWORK: "The provider could not be reached. Check your connection and retry.",
            ErrorClass.PROVIDER: "The provider failed to answer. You can retry.",
            "retrieval_failed": "Your notes could not be searched. You can retry.",
        }.get(error_class, "The answer could not be generated.")
        return AnswerDTO(
            conversation_id=conversation.id,
            message=self._message_to_dto(message, user_id),
            refused=True,
            refusal_reason=detail,
        )

    def _message_to_dto(
        self, message: MessageEntity, user_id: str, citations: Optional[List[CitationEntity]] = None
    ) -> MessageDTO:
        stored = citations if citations is not None else self.citation_repo.list_for_message(message.id, user_id)
        dto_citations = []
        for citation in stored:
            if citation.kind == "relationship":
                deleted = self.rel_repo.get_by_id(citation.target_id, user_id=user_id) is None
            else:
                deleted = self.entity_repo.get_by_id(citation.target_id, user_id=user_id) is None
            dto_citations.append(CitationDTO(
                id=citation.id,
                kind=citation.kind,
                target_id=citation.target_id,
                name=citation.name_snapshot,
                deleted=deleted,
            ))
        return MessageDTO(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            error_class=message.error_class,
            error_message=message.error_message,
            created_at=message.created_at,
            citations=dto_citations,
        )
