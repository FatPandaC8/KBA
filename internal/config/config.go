package config

import (
	"bufio"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	DatabaseURL          string
	Port                 int
	Env                  string
	GroqAPIKey           string
	GroqModel            string
	GroqBaseURL          string
	GroqRPM              int
	GroqTPM              int
	DailyUserTokenBudget int
	SessionSecret        string
}

func LoadConfig() *Config {
	loadDotEnv(".env")

	port := 8080
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
	if dbURL == "" {
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

	return &Config{
		DatabaseURL:          dbURL,
		Port:                 port,
		Env:                  getEnvOrDefault("GUSBY_ENV", "development"),
		GroqAPIKey:           os.Getenv("GROQ_API_KEY"),
		GroqModel:            groqModel,
		GroqBaseURL:          strings.TrimRight(groqBaseURL, "/"),
		GroqRPM:              rpm,
		GroqTPM:              tpm,
		DailyUserTokenBudget: budget,
		SessionSecret:        getEnvOrDefault("GUSBY_SESSION_SECRET", "gusby-default-insecure-secret-key-change-in-prod"),
	}
}

func getEnvOrDefault(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func loadDotEnv(filepath string) {
	paths := []string{filepath, "../" + filepath, "../../" + filepath}
	var file *os.File
	var err error
	for _, p := range paths {
		file, err = os.Open(p)
		if err == nil {
			break
		}
	}
	if file == nil {
		return
	}
	defer file.Close()

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
