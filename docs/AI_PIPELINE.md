# AI Pipeline & Evaluation Reference

This document provides a technical specification of the audio capture constraints, speech-to-text (STT) ingestion, structured knowledge extraction, relationship inference, Semantic Recall requirements, and the offline evaluation pipeline.

---

## 1. Audio Capture Constraints & Decoding

### Mobile Recording Specification
- **Enforced Duration Limit:** Maximum 30 seconds.
- **Auto-Cutoff Implementation:** In [`HomeScreen`](../mobile/lib/ui/screens/home/home_screen.dart), a 1-second interval periodic timer (`_recordTimer`) triggers `_toggleRecording()` automatically once `_recordSeconds >= 30`.
- **Encoding & Audio Format:** 
  - Library: `record` (`AudioRecorder`).
  - Configuration: `AudioEncoder.aacLc`, 64,000 bps bit rate, 44,100 Hz sample rate.
  - Container: `.m4a` file stored in `recordings/` directory under app documents.

### Backend Audio Normalization
Android produces variable bit rate AAC in an M4A container. The backend converts incoming audio using `ffmpeg`:

```python
# server/app/pipeline.py
def decode_audio_ffmpeg(file_path: str, sr: int = 16000) -> np.ndarray:
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0", "-i", file_path,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sr), "-"
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio decode error: {proc.stderr.decode('utf-8', errors='ignore')}")
    raw_bytes = proc.stdout
    if not raw_bytes:
        raise ValueError("Audio file decoded to 0 bytes")
    return np.frombuffer(raw_bytes, np.int16).flatten().astype(np.float32) / 32768.0
```

- Normalizes audio to single-channel (mono) 16kHz signed 16-bit PCM.
- Normalizes integer PCM samples to `[-1.0, 1.0]` float32 array for STT ingestion.

---

## 2. Speech-to-Text (STT) Processing

The backend engine (`ExtractionPipeline.transcribe()` in `server/app/pipeline.py`) operates with two STT paths:

### 1. Local STT (`faster-whisper`) — Default
- **Engine:** `faster-whisper` lazily loaded as a singleton.
- **Model:** `tiny` model with `int8` CPU quantization.
- **VAD Configuration:** `vad_filter=True`, `min_silence_duration_ms=500`.
- **Validation:** If speech transcript is empty or contains only non-speech noise, raises `ValueError("Recording contained no intelligible speech or silence.")` which maps to HTTP 422.

### 2. Remote Whisper API — Fallback / Optional
- If `OPENAI_API_KEY` is provided, the backend attempts `POST https://api.openai.com/v1/audio/transcriptions` with model `whisper-1`.
- If remote transcription fails (e.g., timeout, network failure), it automatically falls back to local `faster-whisper`.

---

## 3. Structured Knowledge Extraction

Once speech is converted to text, `ExtractionPipeline.extract_knowledge()` extracts structured metadata:

```json
{
  "title": "Short concise title (<= 5 words)",
  "core_idea": "1-sentence summary of the main point",
  "details": "Concrete supporting details or verbatim speech",
  "transcript": "Full verbatim transcript",
  "concepts": ["Concept 1", "Concept 2"],
  "tags": ["tag1", "tag2"],
  "open_questions": ["Inquiry question based on topic?"],
  "candidate_relations": ["Related to: Concept 1"],
  "provenance": "voice-pipeline-v1.2-echo-real-local"
}
```

### Extraction Modes
1. **Remote LLM (`gpt-4o-mini`):** Used when `OPENAI_API_KEY` is configured. Employs a strict JSON schema prompt to extract fields.
2. **Local Linguistic Extractor:** Used by default without external dependencies.
   - Cleans conversational prefixes (*"I think that"*, *"So we are going to"*).
   - Extracts concepts using stopword filtering and title-case entity identification.
   - Categorizes heuristic tags (`software`, `research`, `ideas`, `pets`).
   - Discovers explicit question marks (`?`) or synthesizes contextual research questions.

---

## 4. Relationship Inference Engine

`ExtractionPipeline.connect_knowledge()` infers candidate relationships between a newly created knowledge item and all existing database items:

- **Concept Intersection:** Shared concepts produce edge `relation_type = "Supports"`.
- **Tag Intersection:** Shared tags produce edge `relation_type = "Related to"`.
- **Title Lexical Overlap:** Shared significant words (>3 chars) produce edge `relation_type = "Related to"`.
- Inferred relationships are saved to the backend database with `status = "suggested"`.

---

## 5. Semantic Recall Requirements vs. Current Implementation

### Mandatory Product Requirement
Echo requires **dense vector embedding search** in the MVP. Users must be able to query by meaning or natural language questions (e.g. *"What did I record about approximate nearest neighbor search?"*) and recall conceptually relevant items without exact keyword matches.

### Current Implementation Status: **Not Implemented (Critical Gap)**
- Actual implementation in `NoteRepository.searchNotes()` (`mobile/lib/data/repositories/note_repository.dart:61-81`):
  ```dart
  final likePattern = '%$query%';
  final results = await db.query(
    'notes',
    where: 'title LIKE ? OR originalContent LIKE ? OR transcript LIKE ? OR summary LIKE ?',
    whereArgs: [likePattern, likePattern, likePattern, likePattern],
    orderBy: 'createdAt DESC',
  );
  ```
- **Observed Deficiencies:**
  1. No embedding model (e.g. `text-embedding-3-small`, `all-MiniLM-L6-v2`, or ONNX/TFLite) is integrated.
  2. No vector column or vector extension (such as SQLite-VSS or sqlite-vec) is present in `echo_notes.db`.
  3. No vector similarity calculation (cosine similarity / dot product) or ranking exists.
  4. Search fails completely for paraphrases or synonyms.

---

## 6. Evaluation Workflow & Audio Retention Gaps

### Product Requirements
1. **Evaluation Consent:** Must be a separate, explicit opt-in toggle, disabled by default.
2. **Audio Retention:** Server must delete audio files after processing unless the user explicitly granted evaluation consent.

### Current Implementation & Observed Gaps
1. **Backend Endpoints:**
   - `POST /api/eval/record`: Rejects records where `consent_given=False`. Accepts and stores records in `model_eval_records` when `consent_given=True`.
   - `GET /api/eval/export`: Successfully exports evaluation JSON records filtered by `consent_given = 1`.
2. **Mobile Client Missing Opt-In Toggle:**
   - In `SettingsScreen` (`settings_screen.dart`), only `Keep original audio` (local mobile setting) and `Process on Wi-Fi only` exist.
   - There is **no toggle** for evaluation participation or telemetry consent.
3. **Server Audio Storage Unpurged:**
   - During `upload_capture()` in `server/app/main.py:47-56`, audio is written to `server/uploads/{capture_id}.m4a`.
   - Inspection of `server/uploads/` shows 21 audio files totaling >2MB retained indefinitely.
   - No post-processing deletion hook exists to remove audio files when consent is absent.
