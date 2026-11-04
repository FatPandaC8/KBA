package config

import (
	"bufio"
	"errors"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
)

var (
	AppVersion = "1.0.0"
	GitCommit  = "unknown"
	BuildTime  = "unknown"
)

type Config struct {
	Version              string
	CommitSHA            string
	BuildTime            string
	DatabaseURL          string
	Host                 string
	Port                 int
	Env                  string
	GroqAPIKey           string
	GroqModel            string
	GroqBaseURL          string
	GroqRPM              int
	GroqTPM              int
	DailyUserTokenBudget int
	SessionSecret        string
	CORSAllowedOrigins   []string
}

func LoadConfig() *Config {
	loadDotEnv(".env")

	host := getEnvOrDefault("GUSBY_HOST", getEnvOrDefault("HOST", "127.0.0.1"))

	port := 8081
	if p := os.Getenv("GUSBY_PORT"); p != "" {
		if val, err := strconv.Atoi(p); err == nil {
			port = val
		}
	} else if p := os.Getenv("PORT"); p != "" {
		if val, err := strconv.Atoi(p); err == nil {
			port = val
		}
	}

	rpm := 30
	if r := os.Getenv("GROQ_RPM"); r != "" {
		if val, err := strconv.Atoi(r); err == nil {
			rpm = val
		}
	} else if r := os.Getenv("ECHO_GROQ_RPM"); r != "" {
		if val, err := strconv.Atoi(r); err == nil {
			rpm = val
		}
	}

	tpm := 8000
	if t := os.Getenv("GROQ_TPM"); t != "" {
		if val, err := strconv.Atoi(t); err == nil {
			tpm = val
		}
	} else if t := os.Getenv("ECHO_GROQ_TPM"); t != "" {
		if val, err := strconv.Atoi(t); err == nil {
			tpm = val
		}
	}

	budget := 40000
	if b := os.Getenv("GUSBY_DAILY_USER_TOKEN_BUDGET"); b != "" {
		if val, err := strconv.Atoi(b); err == nil {
			budget = val
		}
	}

	dbURL := os.Getenv("GUSBY_DATABASE_URL")
	if dbURL == "" {
		dbURL = os.Getenv("DATABASE_URL")
	}
	if dbURL == "" && getEnvOrDefault("GUSBY_ENV", "development") != "production" {
		dbURL = "postgresql://echo:echo_dev_password@127.0.0.1:5432/echo_kb"
	}

	groqModel := os.Getenv("GROQ_MODEL")
	if groqModel == "" {
		groqModel = "openai/gpt-oss-120b"
	}

	groqBaseURL := os.Getenv("GROQ_BASE_URL")
	if groqBaseURL == "" {
		groqBaseURL = "https://api.groq.com/openai/v1"
	}

	corsOriginsRaw := os.Getenv("GUSBY_CORS_ALLOWED_ORIGINS")
	var corsOrigins []string
	if corsOriginsRaw != "" {
		for _, o := range strings.Split(corsOriginsRaw, ",") {
			o = strings.TrimSpace(o)
			if o != "" {
				corsOrigins = append(corsOrigins, o)
			}
		}
	}
	if len(corsOrigins) == 0 {
		corsOrigins = []string{
			"http://127.0.0.1:3000",
			"http://localhost:3000",
			"http://127.0.0.1:8080",
			"http://localhost:8080",
			"http://127.0.0.1:8081",
			"http://localhost:8081",
		}
	}

	return &Config{
		Version:              AppVersion,
		CommitSHA:            GitCommit,
		BuildTime:            BuildTime,
		DatabaseURL:          dbURL,
		Host:                 host,
		Port:                 port,
		Env:                  getEnvOrDefault("GUSBY_ENV", "development"),
		GroqAPIKey:           os.Getenv("GROQ_API_KEY"),
		GroqModel:            groqModel,
		GroqBaseURL:          strings.TrimRight(groqBaseURL, "/"),
		GroqRPM:              rpm,
		GroqTPM:              tpm,
		DailyUserTokenBudget: budget,
		SessionSecret:        getEnvOrDefault("GUSBY_SESSION_SECRET", "gusby-default-insecure-secret-key-change-in-prod"),
		CORSAllowedOrigins:   corsOrigins,
	}
}

// SanitizedDatabaseURL returns the DatabaseURL with credentials masked for safe logging
func (c *Config) SanitizedDatabaseURL() string {
	if c.DatabaseURL == "" {
		return "<empty>"
	}
	parsed, err := url.Parse(c.DatabaseURL)
	if err != nil {
		return "postgresql://<unparseable-url>"
	}
	if parsed.User != nil {
		username := parsed.User.Username()
		parsed.User = url.UserPassword(username, "REDACTED")
	}
	return parsed.String()
}

// Validate checks configuration sanity for both development and production modes
func (c *Config) Validate() error {
	if c.Port < 1 || c.Port > 65535 {
		return fmt.Errorf("invalid port %d: must be between 1 and 65535", c.Port)
	}
	if strings.TrimSpace(c.Host) == "" {
		return errors.New("host cannot be empty")
	}

	if strings.Contains(c.DatabaseURL, "/server_lab") {
		return errors.New("critical safety violation: target database is 'server_lab'; Gusby is strictly prohibited from connecting to 'server_lab'")
	}

	if c.Env == "production" {
		if c.DatabaseURL == "" {
			return errors.New("GUSBY_DATABASE_URL (or DATABASE_URL) is required in production mode")
		}
		if strings.Contains(c.DatabaseURL, "echo:echo_dev_password") {
			return errors.New("insecure default development database credentials detected; configure dedicated GUSBY_DATABASE_URL for production")
		}
		if c.SessionSecret == "" || c.SessionSecret == "gusby-default-insecure-secret-key-change-in-prod" {
			return errors.New("insecure default GUSBY_SESSION_SECRET detected; production requires a unique, secure secret")
		}
		if len(c.SessionSecret) < 32 {
			return fmt.Errorf("GUSBY_SESSION_SECRET too short (%d chars); minimum length is 32 characters in production", len(c.SessionSecret))
		}
		if strings.TrimSpace(c.GroqAPIKey) == "" {
			return errors.New("GROQ_API_KEY is required in production mode")
		}
	}

	return nil
}

func getEnvOrDefault(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func loadDotEnv(filepath string) {
	if custom := os.Getenv("GUSBY_ENV_FILE"); custom != "" {
		if f, err := os.Open(custom); err == nil {
			defer f.Close()
			parseEnvScanner(f)
			return
		}
	}

	paths := []string{filepath, "../" + filepath, "../../" + filepath}
	for _, p := range paths {
		if f, err := os.Open(p); err == nil {
			defer f.Close()
			parseEnvScanner(f)
			return
		}
	}
}

func parseEnvScanner(file *os.File) {
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			k := strings.TrimSpace(parts[0])
			v := strings.TrimSpace(parts[1])
			v = strings.Trim(v, `"'`)
			if os.Getenv(k) == "" {
				os.Setenv(k, v)
			}
		}
	}
}
