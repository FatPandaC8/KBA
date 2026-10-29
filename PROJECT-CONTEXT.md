# PROJECT-CONTEXT

Provider decision (D2): Groq is the only LLM provider for extraction and Q&A. STT stays local faster-whisper. Groq receives transcript/subgraph text only, never audio. OpenRouter and Gemini are out; Cloudflare may be revisited later as an explicitly selected second provider, never a silent fallback. Key in GROQ_API_KEY server env var only.

Consent versioned; re-prompt on named-provider or model change. Groq trains_on_data=False.

Deterministic fake LLM port with scripted 429, malformed JSON, timeout to be added alongside real adapter. Budget tokens per call against free TPM/TPD. Specific "daily quota reached" message. Never fall back silently.
