package llm

import "context"

type ProviderDescription struct {
	Kind         string   `json:"kind"`
	Model        string   `json:"model"`
	Version      string   `json:"version"`
	IsConfigured bool     `json:"is_configured"`
	Capabilities []string `json:"capabilities"`
	RPMLimit     int      `json:"rpm_limit,omitempty"`
	TPMLimit     int      `json:"tpm_limit,omitempty"`
}

type ProviderHealth struct {
	Status    string         `json:"status"` // healthy, degraded, down, paused, unknown
	Reason    string         `json:"reason"`
	LatencyMs int            `json:"latency_ms"`
	Details   map[string]any `json:"details"`
}

type CallMetadata struct {
	PromptTokens     int    `json:"prompt_tokens"`
	CompletionTokens int    `json:"completion_tokens"`
	TotalTokens      int    `json:"total_tokens"`
	LatencyMs        int    `json:"latency_ms"`
	StatusCode       int    `json:"status_code"`
	ErrorClass       string `json:"error_class,omitempty"`
}

type LLMClient interface {
	CompleteJSON(ctx context.Context, system, user string, maxTokens int, temperature float64) (string, int, int, error)
	ModelName() string
	Describe() ProviderDescription
	Health(ctx context.Context) (ProviderHealth, error)
}
