import importlib.util
import os
import shutil
from typing import List

from server.app.application.dto import ProviderInfoDTO
from server.app.application.ports import ProviderRegistryPort


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class LocalProviderRegistry(ProviderRegistryPort):
    def __init__(self, pipeline_version: str = "v2.0-echo-mvp"):
        self.pipeline_version = pipeline_version

    def list_providers(self) -> List[ProviderInfoDTO]:
        stt_ready = _module_available("faster_whisper") and shutil.which("ffmpeg") is not None
        embeddings_ready = _module_available("fastembed")
        groq_ready = bool(os.getenv("GROQ_API_KEY"))
        return [
            ProviderInfoDTO(
                id="stt_local",
                name="faster-whisper (self-hosted)",
                kind="speech_to_text",
                receives=["audio recording"],
                trains_on_data=False,
                available=stt_ready,
                detail="" if stt_ready else "faster-whisper or ffmpeg is not installed",
            ),
            ProviderInfoDTO(
                id="embeddings_local",
                name="fastembed (self-hosted)",
                kind="embeddings",
                receives=["entity and relationship text"],
                trains_on_data=False,
                available=embeddings_ready,
                detail="" if embeddings_ready else "fastembed is not installed; semantic search falls back to lexical ranking",
            ),
            ProviderInfoDTO(
                id="extraction_local",
                name="local rule-based extraction (self-hosted)",
                kind="extraction",
                receives=["transcript text"],
                trains_on_data=False,
                available=True,
            ),
            ProviderInfoDTO(
                id="answering_local",
                name="local graph-grounded answerer (self-hosted)",
                kind="question_answering",
                receives=["entity and relationship summaries"],
                trains_on_data=False,
                available=True,
            ),
            ProviderInfoDTO(
                id="extraction_groq",
                name="Groq free models (hosted)",
                kind="extraction",
                receives=["transcript text"],
                trains_on_data=False,
                available=groq_ready,
                detail="" if groq_ready else "GROQ_API_KEY is not set",
            ),
            ProviderInfoDTO(
                id="answering_groq",
                name="Groq free models (hosted)",
                kind="question_answering",
                receives=["entity and relationship summaries"],
                trains_on_data=False,
                available=groq_ready,
                detail="" if groq_ready else "GROQ_API_KEY is not set",
            ),
        ]
