# Future Model Swap & Fine-Tuned Model Integration Checklist

**Version:** 1.0  
**Status:** Decided  
**Reference:** CR-001, TRD v1.1 Section 4, Schema/API v1.1

This checklist guides engineering teams on how to swap, upgrade, or connect a fine-tuned or self-hosted LLM (e.g., Llama 3 on vLLM, DeepSeek, Mistral, Ollama) to Gusby **without requiring any database schema migrations or frontend admin UI changes**.

---

## 1. Architectural Philosophy (Zero-UI-Change Design)

Gusby decouples the AI model implementation from both the database and the administrative monitoring dashboard:
1. **Generic Provider Contract (`internal/llm/interface.go`)**: Every provider implements `Describe()` and `Health()`.
2. **Schema-Free Telemetry (`details map[string]any`)**: Any provider-specific telemetry (GPU VRAM, temperature, kv-cache hit rate, prompt tokens/sec, LoRA adapter ID, quantized weight precision) is packaged inside the generic `details` key-value map.
3. **Admin UI Compatibility**: The Admin AI Observability screen (`/admin/ai`) dynamically renders whatever key-value pairs are returned in `details`.

---

## 2. Step-by-Step Swap Procedure

### Step 1: Implement the Go Provider Contract
Create `internal/llm/<provider_name>.go` implementing the `LLMClient` interface:

```go
type LLMClient interface {
    CompleteJSON(ctx context.Context, system, user string, maxTokens int, temperature float64) (string, int, int, error)
    ModelName() string
    Describe() ProviderDescription
    Health(ctx context.Context) (ProviderHealth, error)
}
```

#### Contract Expectations:
- `Describe()`: Return kind (`vllm`, `ollama`, `openai`, `custom`), model name, version, rate limits, and capability list (`["chat", "json_mode"]`).
- `Health(ctx)`: Execute a minimal health ping (`user: "ping"`). Return:
  - `Status`: `"healthy"`, `"degraded"`, `"down"`, or `"paused"`.
  - `LatencyMs`: Roundtrip time in milliseconds.
  - `Details`: Populate custom model metrics (GPU memory, batch size, engine type, LoRA version).
- `CompleteJSON(...)`: Enforce JSON output. Always return `(rawJSON, promptTokens, completionTokens, error)`.

---

### Step 2: Configure Environment Variables
In `.env` (or Kubernetes ConfigMap/Secrets), configure provider parameters:

```env
# Example Custom vLLM / Self-Hosted Model
LLM_PROVIDER=vllm
LLM_BASE_URL=http://vllm-service.internal:8000/v1
LLM_MODEL=meta-llama/Meta-Llama-3.1-70B-Instruct-Gusby-v1
LLM_API_KEY=optional_internal_token
LLM_RPM=600
LLM_TPM=1000000
```

---

### Step 3: Register in Factory / Main Startup
In `cmd/gusby/main.go`, instantiate your new client based on `cfg.LLMProvider`:

```go
var llmClient llm.LLMClient
switch cfg.LLMProvider {
case "vllm", "custom":
    llmClient = llm.NewCustomClient(cfg.LLMBaseURL, cfg.LLMModel, cfg.LLMAPIKey, cfg.LLMRPM, cfg.LLMTPM)
default:
    llmClient = llm.NewGroqClient(cfg.GroqAPIKey, cfg.GroqModel, cfg.GroqBaseURL, cfg.GroqRPM, cfg.GroqTPM)
}
```

---

### Step 4: Run the Standard Eval Benchmark Suite
Before directing user traffic to the new model, run the offline gold evaluation benchmark:

```bash
go test -v ./eval/gusby -run TestRunGoldEvaluation -timeout 30m
```

The eval suite tests precision, recall, and hallucination defense against curated ground truth datasets and automatically writes the benchmark scorecard into `gusby.eval_runs`.

---

### Step 5: Execute Canary Active Probe via Admin UI or CLI
Before resuming the AI processing gate, run a harmless synthetic probe to verify end-to-end connectivity:

- **Via Admin UI:** Navigate to `http://localhost:3000/admin/ai` and click **Run Active Probe**.
- **Via API:**
  ```bash
  curl -X POST http://127.0.0.1:8080/api/admin/ai/probe \
    -H "Cookie: gusby_session=<admin_token>"
  ```
- **Verification:** Ensure `status: "success"` and `http_status: 200` are returned.

---

### Step 6: Reset Circuit Breaker and Resume Gate
1. Navigate to `/admin/ai`.
2. Click **Reset Breaker** (or **Resume AI Gate**).
3. The queue worker will immediately begin consuming `waiting_for_ai` and `queued` ingestion jobs.

---

## 3. Backward Compatibility Verification Table

| Check Item | Requirement | Verification Method |
|---|---|---|
| **Deterministic Evidence** | Verbatim quotes must match text spans exactly | `TestDeterministicEvidenceValidation` |
| **No Schema Migrations** | DB tables remain untouched | All tables query `details map[string]any` |
| **Per-Call Privacy** | Never log raw prompt text or source text | Query `SELECT prompt_text FROM gusby.ai_call_log` -> Column does not exist |
| **Circuit Breaker** | Trips automatically on consecutive 429/5xx errors | `TestAIGate_LifecycleAndBreaker` |
| **Admin UI Render** | Displays model name, provider, and custom metrics | Open `/admin/ai` in browser |
