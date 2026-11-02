package llm

import "context"

type LLMClient interface {
	CompleteJSON(ctx context.Context, system, user string, maxTokens int, temperature float64) (string, int, int, error)
	ModelName() string
}
