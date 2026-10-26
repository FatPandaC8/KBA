import os
import json
import re
import string
import subprocess
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Tuple, Optional
import numpy as np

from .schemas import KnowledgeItem, KnowledgeRelationship

PIPELINE_VERSION = "v1.2-echo-real"

_GLOBAL_WHISPER_MODEL = None

def get_whisper_model():
    """Lazily load faster-whisper tiny model on CPU for local STT."""
    global _GLOBAL_WHISPER_MODEL
    if _GLOBAL_WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel
            # Load tiny model with int8 quantization for ultra-fast, robust transcription on CPU
            _GLOBAL_WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
        except Exception as e:
            print(f"[STT] Warning: Failed to load faster-whisper model: {e}")
            _GLOBAL_WHISPER_MODEL = None
    return _GLOBAL_WHISPER_MODEL

def decode_audio_ffmpeg(file_path: str, sr: int = 16000) -> np.ndarray:
    """Decodes any audio format (including Android AAC/M4A) via ffmpeg into normalized 16kHz float32 audio."""
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0", "-i", file_path,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sr), "-"
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio decode error ({proc.returncode}): {proc.stderr.decode('utf-8', errors='ignore')}")
    raw_bytes = proc.stdout
    if not raw_bytes:
        raise ValueError("Audio file decoded to 0 bytes")
    return np.frombuffer(raw_bytes, np.int16).flatten().astype(np.float32) / 32768.0

class ExtractionPipeline:
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model

    def transcribe(self, audio_file_path: str) -> str:
        """
        Transcribe short audio (<=30s) using local faster-whisper STT engine (or remote Whisper if configured).
        Does NOT fabricate or return hardcoded text.
        """
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        file_size = os.path.getsize(audio_file_path)
        if file_size < 100:
            raise ValueError(f"Audio file is too small or corrupted ({file_size} bytes)")

        # 1. If remote OpenAI API key is configured, attempt remote Whisper first
        if self.api_key:
            try:
                boundary = "----WebKitFormBoundaryEchoSTT7MA4"
                with open(audio_file_path, "rb") as f:
                    file_bytes = f.read()

                body = (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="file"; filename="audio.m4a"\r\n'
                    f"Content-Type: audio/m4a\r\n\r\n"
                ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

                req = urllib.request.Request(
                    f"{self.base_url}/audio/transcriptions",
                    data=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": f"multipart/form-data; boundary={boundary}"
                    }
                )
                with urllib.request.urlopen(req, timeout=20) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    text = data.get("text", "").strip()
                    if text:
                        return text
            except Exception as e:
                print(f"[STT] Remote Whisper failed: {e}. Falling back to local faster-whisper.")

        # 2. Local real faster-whisper STT using ffmpeg audio pipeline
        whisper_model = get_whisper_model()
        if whisper_model is None:
            raise RuntimeError("Local faster-whisper STT engine is not available")

        audio_arr = decode_audio_ffmpeg(audio_file_path, sr=16000)
        duration_sec = len(audio_arr) / 16000.0

        # Transcribe
        segments, info = whisper_model.transcribe(
            audio_arr,
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        transcript = " ".join([seg.text.strip() for seg in segments]).strip()

        # Handle empty/unintelligible speech
        if not transcript:
            raise ValueError(f"Recording ({duration_sec:.1f}s) contained no intelligible speech or silence.")

        return transcript

    def extract_knowledge(self, transcript: str, capture_id: str) -> Tuple[KnowledgeItem, List[KnowledgeRelationship]]:
        """
        Transforms validated speech transcript into structured knowledge:
        - title
        - core_idea
        - details
        - concepts
        - tags
        - open_questions
        - candidate_relations
        """
        clean_text = transcript.strip()
        if not clean_text:
            raise ValueError("Cannot extract knowledge from empty transcript")

        # 1. Remote LLM extraction if API key is provided
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

                    item = KnowledgeItem(
                        capture_id=capture_id,
                        title=parsed.get("title", self._generate_title_from_text(clean_text)),
                        core_idea=parsed.get("core_idea", clean_text),
                        details=parsed.get("details", clean_text),
                        transcript=clean_text,
                        concepts=parsed.get("concepts", []),
                        tags=parsed.get("tags", []),
                        open_questions=parsed.get("open_questions", []),
                        candidate_relations=parsed.get("candidate_relations", []),
                        provenance=f"voice-pipeline-{PIPELINE_VERSION}-ai"
                    )
                    return item, []
            except Exception as e:
                print(f"[Extract] Remote LLM error: {e}. Falling back to semantic linguistic extractor.")

        # 2. Local semantic linguistic knowledge extractor (never fabricates random facts, directly analyzes transcript)
        title = self._generate_title_from_text(clean_text)
        core_idea = self._extract_core_idea(clean_text)
        details = clean_text
        concepts = self._extract_concepts(clean_text)
        tags = self._extract_tags(clean_text, concepts)
        open_questions = self._extract_questions(clean_text)
        candidate_relations = [f"Related to: {c}" for c in concepts[:3]]

        item = KnowledgeItem(
            capture_id=capture_id,
            title=title,
            core_idea=core_idea,
            details=details,
            transcript=clean_text,
            concepts=concepts,
            tags=tags,
            open_questions=open_questions,
            candidate_relations=candidate_relations,
            provenance=f"voice-pipeline-{PIPELINE_VERSION}-local"
        )
        return item, []

    def _generate_title_from_text(self, text: str) -> str:
        # Strip prefixes like "I want to", "So we are going to", "The thought is that"
        cleaned = re.sub(r"^(i want to|i think that|we need to|so we are going to|let's talk about|thought about)\s+", "", text, flags=re.IGNORECASE).strip()
        words = cleaned.split()
        if not words:
            words = text.split()
        raw_title = " ".join(words[:5]).strip(string.punctuation)
        # Capitalize nicely
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
        # Filter stopwords and extract key entity phrases
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
            "is", "was", "are", "were", "be", "been", "have", "has", "had", "do", "does",
            "did", "i", "you", "we", "they", "it", "this", "that", "there", "so", "going",
            "want", "need", "make", "take", "look", "video", "about", "all", "just"
        }
        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text.lower())
        meaningful = [w for w in words if w not in stopwords]

        # Prioritize capitalized phrases from original text if present
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
        # Look for existing questions
        questions = [q.strip() + "?" for q in text.split("?") if len(q.strip()) > 5]
        if questions:
            return questions[:2]
        # Generate an open inquiry based on core topic
        words = re.findall(r"\b[A-Za-z]{4,}\b", text.lower())
        topic = words[0] if words else "this topic"
        return [f"What are the next practical steps for {topic}?"]

    def connect_knowledge(self, new_item: KnowledgeItem, existing_items: List[KnowledgeItem]) -> List[KnowledgeRelationship]:
        """
        Derives candidate relationships to existing items based on shared concepts, tags, or vocabulary.
        """
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
                relationships.append(KnowledgeRelationship(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type="Supports",
                    status="suggested"
                ))
            elif common_tags:
                relationships.append(KnowledgeRelationship(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type="Related to",
                    status="suggested"
                ))
            elif any(w.lower() in existing.title.lower() for w in new_item.title.split() if len(w) > 3):
                relationships.append(KnowledgeRelationship(
                    from_id=new_item.id,
                    to_id=existing.id,
                    relation_type="Related to",
                    status="suggested"
                ))

        return relationships
