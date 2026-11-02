package llm

import (
	"context"
	"sync"
)

type MockClient struct {
	mu             sync.Mutex
	model          string
	responses      map[string]string
	defaultResp    string
	calls          []RecordedCall
	shouldFailWith error
}

type RecordedCall struct {
	System      string
	User        string
	MaxTokens   int
	Temperature float64
}

func NewMockClient(defaultResp string) *MockClient {
	return &MockClient{
		model:       "mock-groq-model",
		responses:   make(map[string]string),
		defaultResp: defaultResp,
	}
}

func (m *MockClient) ModelName() string {
	return m.model
}

func (m *MockClient) SetResponse(prefix, response string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.responses[prefix] = response
}

func (m *MockClient) SetFailure(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.shouldFailWith = err
}

func (m *MockClient) CompleteJSON(ctx context.Context, system, user string, maxTokens int, temperature float64) (string, int, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.calls = append(m.calls, RecordedCall{
		System:      system,
		User:        user,
		MaxTokens:   maxTokens,
		Temperature: temperature,
	})

	if m.shouldFailWith != nil {
		return "", 0, 0, m.shouldFailWith
	}

	for prefix, resp := range m.responses {
		if len(user) >= len(prefix) && user[:len(prefix)] == prefix {
			return resp, 100, 50, nil
		}
	}

	return m.defaultResp, 100, 50, nil
}

func (m *MockClient) CallCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.calls)
}

func (m *MockClient) Calls() []RecordedCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	copied := make([]RecordedCall, len(m.calls))
	copy(copied, m.calls)
	return copied
}
