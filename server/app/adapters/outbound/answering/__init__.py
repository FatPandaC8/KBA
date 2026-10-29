"""Deterministic, evidence-grounded local answerer (QA-02, QA-03).

The answerer only restates retrieved graph evidence. It never receives raw
transcripts and never invents content: when evidence is insufficient it
refuses and says what is missing.
"""

import uuid
from typing import List

from server.app.application.dto import AnswerDraft, CitationDTO, EvidenceItem
from server.app.application.ports import AnswerProviderPort

_MIN_EVIDENCE_SCORE = 0.12


class LocalGraphAnswerProvider(AnswerProviderPort):
    def answer(
        self,
        question: str,
        evidence: List[EvidenceItem],
        contradictions: List[str],
    ) -> AnswerDraft:
        if not (question or "").strip():
            return AnswerDraft(
                text="Please ask a question about your notes.",
                refused=True,
                refusal_reason="empty_question",
            )

        usable = [item for item in evidence if item.score >= _MIN_EVIDENCE_SCORE]
        if not usable:
            return AnswerDraft(
                text="There is not enough evidence in your graph to answer that.",
                refused=True,
                refusal_reason="insufficient_evidence",
            )

        facts: List[str] = []
        citations: List[CitationDTO] = []
        seen_citations = set()

        for item in sorted(usable, key=lambda entry: entry.score, reverse=True):
            if item.kind == "relationship" and item.related_name:
                relation = (item.relation_type or "").lower()
                if relation in {"related to", "connected to"}:
                    fact = f"{item.name} is {relation} {item.related_name}"
                elif relation:
                    fact = f"{item.name} {relation} {item.related_name}"
                else:
                    fact = f"{item.name} is connected to {item.related_name}"
                if item.description:
                    fact += f" ({item.description})"
            elif item.description:
                fact = f"{item.name}: {item.description}"
            else:
                kind = (item.entity_type or "concept").replace("_", " ")
                fact = f"{item.name} is recorded as a {kind} in your notes."

            if item.certainty == "uncertain":
                fact += " This link is marked uncertain in your notes."
            facts.append(fact)

            key = (item.kind, item.target_id)
            if key not in seen_citations:
                seen_citations.add(key)
                citations.append(CitationDTO(
                    id=str(uuid.uuid4()),
                    kind=item.kind,
                    target_id=item.target_id,
                    name=item.name,
                ))

        inferences: List[str] = []
        relationship_names = [item for item in usable if item.kind == "relationship"]
        if len(relationship_names) >= 2:
            inferences.append(
                "The retrieved relationships connect these notes indirectly; "
                "this connection is inferred, not stated in a single recording."
            )

        text_parts: List[str] = []
        if contradictions:
            text_parts.append(
                "Your notes contain conflicting statements about this: "
                + "; ".join(sorted(set(contradictions)))
                + "."
            )
        text_parts.append("Based on your notes: " + " ".join(facts))
        if inferences:
            text_parts.append("Inference: " + " ".join(inferences))

        return AnswerDraft(
            text="\n\n".join(text_parts),
            facts=facts,
            inferences=inferences,
            contradictions=sorted(set(contradictions)),
            citations=citations,
        )
