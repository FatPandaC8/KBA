import json
import re
import string
import urllib.request
from typing import List, Tuple, Optional
from server.app.application.ports import KnowledgeExtractionPort
from server.app.domain.entities import KnowledgeItemEntity, RelationshipEntity
from server.app.domain.value_objects import RelationType, RelationStatus
from server.app.domain.errors import ValidationError

class SemanticKnowledgeExtractor(KnowledgeExtractionPort):
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini", pipeline_version: str = "v1.2-echo-real"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.pipeline_version = pipeline_version

    def extract(self, transcript: str, capture_id: str) -> KnowledgeItemEntity:
        clean_text = transcript.strip()
        if not clean_text:
            raise ValidationError("Cannot extract knowledge from empty transcript")

        # 1. Remote LLM extraction if API key configured
        if self.api_key:
            try:
                system_prompt = (
                    "You are the knowledge extraction engine for Echo. "
                    "Extract structured knowledge from this short spoken thought.\n"
                    "Return ONLY valid JSON with exactly these keys:\n"
                    "{\n"
                    '  "title": "string (concise, max 5 words)",\n'
                    '  "core_idea": "1-sentence summary of the main point",\n'
                    '  "details": "concrete supporting details or observations",\n'
                    '  "concepts": ["concept1", "concept2"],\n'
                    '  "tags": ["tag1", "tag2"],\n'
                    '  "open_questions": ["question 1"],\n'
                    '  "candidate_relations": ["related topic or entity"]\n'
                    "}"
                )
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": clean_text}
                    ],
                    "temperature": 0.2
                }
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=20) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"].strip()
                    if content.startswith("```json"):
                        content = content[7:-3]
                    elif content.startswith("```"):
                        content = content[3:-3]
                    parsed = json.loads(content.strip())

                    return KnowledgeItemEntity.create(
                        id=capture_id,
                        capture_id=capture_id,
                        title=parsed.get("title", self._generate_title_from_text(clean_text)),
                        core_idea=parsed.get("core_idea", clean_text),
                        details=parsed.get("details", clean_text),
                        transcript=clean_text,
                        concepts=parsed.get("concepts", []),
                        tags=parsed.get("tags", []),
                        open_questions=parsed.get("open_questions", []),
                        candidate_relations=parsed.get("candidate_relations", []),
                        provenance=f"voice-pipeline-{self.pipeline_version}-ai",
                    )
            except Exception as e:
                print(f"[Extract] Remote LLM error: {e}. Falling back to linguistic extractor.")

        # 2. Local semantic linguistic knowledge extractor
        title = self._generate_title_from_text(clean_text)
        core_idea = self._extract_core_idea(clean_text)
        details = clean_text
        concepts = self._extract_concepts(clean_text)
        tags = self._extract_tags(clean_text, concepts)
        open_questions = self._extract_questions(clean_text)
        candidate_relations = [f"Related to: {c}" for c in concepts[:3]]

        return KnowledgeItemEntity.create(
            id=capture_id,
            capture_id=capture_id,
            title=title,
            core_idea=core_idea,
            details=details,
            transcript=clean_text,
            concepts=concepts,
            tags=tags,
            open_questions=open_questions,
            candidate_relations=candidate_relations,
            provenance=f"voice-pipeline-{self.pipeline_version}-local",
        )

    def connect(self, new_item: KnowledgeItemEntity, existing_items: List[KnowledgeItemEntity]) -> List[RelationshipEntity]:
        relationships = []
        new_concepts = {c.lower() for c in new_item.concepts}
        new_tags = {t.lower() for t in new_item.tags}

        for existing in existing_items:
            if existing.id == new_item.id or existing.capture_id == new_item.capture_id:
                continue

            exist_concepts = {c.lower() for c in existing.concepts}
            exist_tags = {t.lower() for t in existing.tags}

            common_concepts = new_concepts & exist_concepts
            common_tags = new_tags & exist_tags

            if common_concepts:
                relationships.append(RelationshipEntity.create(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type=RelationType.SUPPORT,
                    status=RelationStatus.SUGGESTED,
                ))
            elif common_tags:
                relationships.append(RelationshipEntity.create(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type=RelationType.RELATED_TO,
                    status=RelationStatus.SUGGESTED,
                ))
            elif any(w.lower() in existing.title.lower() for w in new_item.title.split() if len(w) > 3):
                relationships.append(RelationshipEntity.create(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type=RelationType.RELATED_TO,
                    status=RelationStatus.SUGGESTED,
                ))

        return relationships

    def _generate_title_from_text(self, text: str) -> str:
        cleaned = re.sub(r"^(i want to|i think that|we need to|so we are going to|let's talk about|thought about)\s+", "", text, flags=re.IGNORECASE).strip()
        words = cleaned.split()
        if not words:
            words = text.split()
        raw_title = " ".join(words[:5]).strip(string.punctuation)
        if raw_title:
            return raw_title[0].upper() + raw_title[1:]
        return "Voice Capture"

    def _extract_core_idea(self, text: str) -> str:
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if sentences:
            first = sentences[0]
            if len(first) > 10:
                return first + "."
        return text

    def _extract_concepts(self, text: str) -> List[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
            "is", "was", "are", "were", "be", "been", "have", "has", "had", "do", "does",
            "did", "i", "you", "we", "they", "it", "this", "that", "there", "so", "going",
            "want", "need", "make", "take", "look", "video", "about", "all", "just"
        }
        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text.lower())
        meaningful = [w for w in words if w not in stopwords]

        caps = re.findall(r"\b[A-Z][a-z0-9]+\b", text)
        concepts = []
        for c in caps:
            if c.lower() not in stopwords and c.capitalize() not in concepts:
                concepts.append(c.capitalize())

        for w in meaningful:
            cap = w.capitalize()
            if cap not in concepts:
                concepts.append(cap)
            if len(concepts) >= 4:
                break

        if not concepts:
            concepts = ["Observation"]
        return concepts

    def _extract_tags(self, text: str, concepts: List[str]) -> List[str]:
        tags = set()
        lower = text.lower()
        if any(w in lower for w in ["software", "app", "code", "system", "tech", "program"]):
            tags.add("software")
        if any(w in lower for w in ["pet", "dog", "cat", "animal"]):
            tags.add("pets")
        if any(w in lower for w in ["research", "study", "tradeoff", "recall", "search"]):
            tags.add("research")
        if any(w in lower for w in ["idea", "insight", "thought", "future"]):
            tags.add("ideas")

        for c in concepts[:2]:
            tags.add(c.lower())

        return sorted(list(tags))[:4]

    def _extract_questions(self, text: str) -> List[str]:
        questions = [q.strip() + "?" for q in text.split("?") if len(q.strip()) > 5]
        if questions:
            return questions[:2]
        words = re.findall(r"\b[A-Za-z]{4,}\b", text.lower())
        topic = words[0] if words else "this topic"
        return [f"What are the next practical steps for {topic}?"]
