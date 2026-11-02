package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	ErrEmptyAPIKey      = errors.New("GROQ_API_KEY is not configured")
	ErrQuotaExceeded    = errors.New("groq rate limit or quota exceeded")
	ErrMalformedResponse = errors.New("groq returned an invalid or empty JSON response")
)

type GroqClient struct {
	apiKey      string
	model       string
	baseURL     string
	httpClient  *http.Client
	rateLimiter *RateLimiter
}

func NewGroqClient(apiKey, model, baseURL string, rpm, tpm int) (*GroqClient, error) {
	if apiKey == "" {
		return nil, ErrEmptyAPIKey
	}
	if model == "" {
		model = "openai/gpt-oss-120b"
	}
	if baseURL == "" {
		baseURL = "https://api.groq.com/openai/v1"
	}

	return &GroqClient{
		apiKey:  apiKey,
		model:   model,
		baseURL: strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{
			Timeout: 45 * time.Second,
		},
		rateLimiter: NewRateLimiter(rpm, tpm),
	}, nil
}

func (g *GroqClient) ModelName() string {
	return g.model
}

type chatRequest struct {
	Model          string          `json:"model"`
	Messages       []chatMessage   `json:"messages"`
	ResponseFormat *responseFormat `json:"response_format,omitempty"`
	MaxTokens      int             `json:"max_tokens,omitempty"`
	Temperature    float64         `json:"temperature"`
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type responseFormat struct {
	Type string `json:"type"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
	Error *struct {
		Message string `json:"message"`
		Type    string `json:"type"`
		Code    string `json:"code"`
	} `json:"error,omitempty"`
}

func (g *GroqClient) CompleteJSON(ctx context.Context, system, user string, maxTokens int, temperature float64) (string, int, int, error) {
	if err := g.rateLimiter.Wait(ctx, 1, 500); err != nil {
		return "", 0, 0, err
	}

	payload := chatRequest{
		Model: g.model,
		Messages: []chatMessage{
			{Role: "system", Content: system},
			{Role: "user", Content: user},
		},
		ResponseFormat: &responseFormat{Type: "json_object"},
		MaxTokens:      maxTokens,
		Temperature:    temperature,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return "", 0, 0, err
	}

	maxRetries := 3
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.baseURL+"/chat/completions", bytes.NewReader(payloadBytes))
		if err != nil {
			return "", 0, 0, err
		}

		req.Header.Set("Authorization", "Bearer "+g.apiKey)
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json")
		req.Header.Set("User-Agent", "Gusby/1.0 (+https://github.com/gusby-kg)")

		resp, err := g.httpClient.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(backoffWithJitter(attempt, 5*time.Second))
			continue
		}

		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			lastErr = err
			continue
		}

		// Handle Rate Limit 429 or Server Errors 5xx
		if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
			retryAfter := parseRetryAfter(resp.Header.Get("Retry-After"))
			lastErr = fmt.Errorf("groq returned status %d: %s", resp.StatusCode, string(body))
			if attempt < maxRetries {
				sleepDuration := retryAfter
				if sleepDuration <= 0 {
					sleepDuration = backoffWithJitter(attempt, 8*time.Second)
				}
				select {
				case <-time.After(sleepDuration):
					continue
				case <-ctx.Done():
					return "", 0, 0, ctx.Err()
				}
			}
			return "", 0, 0, ErrQuotaExceeded
		}

		if resp.StatusCode != http.StatusOK {
			return "", 0, 0, fmt.Errorf("groq API error %d: %s", resp.StatusCode, string(body))
		}

		var chatResp chatResponse
		if err := json.Unmarshal(body, &chatResp); err != nil {
			return "", 0, 0, fmt.Errorf("%w: %v", ErrMalformedResponse, err)
		}

		if chatResp.Error != nil {
			return "", 0, 0, fmt.Errorf("groq returned error: %s", chatResp.Error.Message)
		}

		if len(chatResp.Choices) == 0 || chatResp.Choices[0].Message.Content == "" {
			return "", 0, 0, ErrMalformedResponse
		}

		content := strings.TrimSpace(chatResp.Choices[0].Message.Content)
		return content, chatResp.Usage.PromptTokens, chatResp.Usage.CompletionTokens, nil
	}

	return "", 0, 0, fmt.Errorf("exhausted retries: %w", lastErr)
}

func parseRetryAfter(val string) time.Duration {
	if val == "" {
		return 0
	}
	if seconds, err := strconv.Atoi(val); err == nil && seconds > 0 {
		return time.Duration(seconds) * time.Second
	}
	return 0
}

func backoffWithJitter(attempt int, maxWait time.Duration) time.Duration {
	base := 1 * time.Second
	wait := base * time.Duration(1<<attempt)
	jitter := time.Duration(rand.Intn(500)) * time.Millisecond
	total := wait + jitter
	if total > maxWait {
		return maxWait
	}
	return total
}

// -----------------------------------------------------------------------------
// Token-Bucket Rate Limiter
// -----------------------------------------------------------------------------

type RateLimiter struct {
	mu          sync.Mutex
	rpmLimit    int
	tpmLimit    int
	requests    []time.Time
	tokens      []tokenRecord
}

type tokenRecord struct {
	timestamp time.Time
	count     int
}

func NewRateLimiter(rpm, tpm int) *RateLimiter {
	return &RateLimiter{
		rpmLimit: rpm,
		tpmLimit: tpm,
	}
}

func (rl *RateLimiter) Wait(ctx context.Context, estRequests, estTokens int) error {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-1 * time.Minute)

	// Clean requests
	var validReqs []time.Time
	for _, t := range rl.requests {
		if t.After(cutoff) {
			validReqs = append(validReqs, t)
		}
	}
	rl.requests = validReqs

	// Clean tokens
	var validTokens []tokenRecord
	currentTokens := 0
	for _, r := range rl.tokens {
		if r.timestamp.After(cutoff) {
			validTokens = append(validTokens, r)
			currentTokens += r.count
		}
	}
	rl.tokens = validTokens

	if len(rl.requests)+estRequests > rl.rpmLimit || currentTokens+estTokens > rl.tpmLimit {
		// Need to wait until oldest item rolls off
		var waitDur time.Duration = 2 * time.Second
		if len(rl.requests) > 0 {
			waitDur = rl.requests[0].Sub(cutoff)
		}
		if waitDur > 0 {
			time.Sleep(waitDur)
		}
	}

	rl.requests = append(rl.requests, time.Now())
	rl.tokens = append(rl.tokens, tokenRecord{timestamp: time.Now(), count: estTokens})
	return nil
}
