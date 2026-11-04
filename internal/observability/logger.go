package observability

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
	"time"
)

type contextKey string

const (
	RequestIDKey contextKey = "request_id"
	UserIDKey    contextKey = "user_id"
)

// SensitiveKeyWords defines keys whose values must be masked in logs
var sensitiveKeyWords = []string{
	"password", "token", "secret", "api_key", "apikey", "authorization",
	"cookie", "session", "access_token", "refresh_token", "db_url",
}

// RedactSensitiveValue checks if a key is sensitive and masks its value
func RedactSensitiveValue(key string, val any) any {
	lower := strings.ToLower(key)
	for _, word := range sensitiveKeyWords {
		if strings.Contains(lower, word) {
			return "[REDACTED]"
		}
	}
	// Redact string values that resemble Bearer tokens or database credentials
	if str, ok := val.(string); ok {
		if strings.HasPrefix(strings.ToLower(str), "bearer ") {
			return "Bearer [REDACTED]"
		}
		if strings.HasPrefix(str, "postgresql://") || strings.HasPrefix(str, "postgres://") {
			return "[REDACTED_DB_URL]"
		}
	}
	return val
}

// sensitiveReplaceAttr is a slog.HandlerOptions ReplaceAttr function that masks secrets
func sensitiveReplaceAttr(groups []string, a slog.Attr) slog.Attr {
	// Format time in RFC3339
	if a.Key == slog.TimeKey {
		if t, ok := a.Value.Any().(time.Time); ok {
			return slog.String(slog.TimeKey, t.UTC().Format(time.RFC3339))
		}
	}

	a.Value = slog.AnyValue(RedactSensitiveValue(a.Key, a.Value.Any()))
	return a
}

// InitLogger initializes and sets the global structured logger
func InitLogger(env, serviceName string, out ...io.Writer) *slog.Logger {
	var writer io.Writer = os.Stdout
	if len(out) > 0 && out[0] != nil {
		writer = out[0]
	}

	level := slog.LevelInfo
	if env == "development" || env == "test" {
		level = slog.LevelDebug
	}

	opts := &slog.HandlerOptions{
		Level:       level,
		ReplaceAttr: sensitiveReplaceAttr,
	}

	var handler slog.Handler
	if env == "production" {
		handler = slog.NewJSONHandler(writer, opts)
	} else {
		handler = slog.NewTextHandler(writer, opts)
	}

	logger := slog.New(handler).With(
		slog.String("service", serviceName),
		slog.String("env", env),
	)

	slog.SetDefault(logger)
	return logger
}

// FromContext extracts request context attributes (request_id, user_id) and returns an enriched logger
func FromContext(ctx context.Context) *slog.Logger {
	logger := slog.Default()
	if ctx == nil {
		return logger
	}

	if reqID, ok := ctx.Value(RequestIDKey).(string); ok && reqID != "" {
		logger = logger.With(slog.String("request_id", reqID))
	}
	if uID, ok := ctx.Value(UserIDKey).(string); ok && uID != "" {
		logger = logger.With(slog.String("user_id", uID))
	}

	return logger
}
