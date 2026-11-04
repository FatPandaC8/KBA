package config_test

import (
	"os"
	"testing"

	"gusby/internal/config"
)

func TestConfig_Defaults(t *testing.T) {
	os.Clearenv()
	cfg := config.LoadConfig()

	if cfg.Port != 8081 {
		t.Errorf("expected default port 8081, got %d", cfg.Port)
	}
	if cfg.Host != "127.0.0.1" {
		t.Errorf("expected default host 127.0.0.1, got %s", cfg.Host)
	}
	if cfg.Env != "development" {
		t.Errorf("expected default env development, got %s", cfg.Env)
	}
	if len(cfg.CORSAllowedOrigins) == 0 {
		t.Errorf("expected non-empty default CORSAllowedOrigins")
	}

	sanitized := cfg.SanitizedDatabaseURL()
	if sanitized == "" || sanitized == "<empty>" {
		t.Errorf("expected sanitized db url, got %s", sanitized)
	}
}

func TestConfig_CustomPortAndHost(t *testing.T) {
	os.Clearenv()
	os.Setenv("GUSBY_HOST", "0.0.0.0")
	os.Setenv("GUSBY_PORT", "9090")
	os.Setenv("GUSBY_CORS_ALLOWED_ORIGINS", "https://example.com, https://sub.example.com")

	cfg := config.LoadConfig()
	if cfg.Host != "0.0.0.0" {
		t.Errorf("expected host 0.0.0.0, got %s", cfg.Host)
	}
	if cfg.Port != 9090 {
		t.Errorf("expected port 9090, got %d", cfg.Port)
	}
	if len(cfg.CORSAllowedOrigins) != 2 || cfg.CORSAllowedOrigins[0] != "https://example.com" {
		t.Errorf("unexpected CORS origins: %v", cfg.CORSAllowedOrigins)
	}
}

func TestConfig_ValidateProduction(t *testing.T) {
	tests := []struct {
		name      string
		modify    func(c *config.Config)
		wantError bool
	}{
		{
			name: "valid production config",
			modify: func(c *config.Config) {
				c.Env = "production"
				c.DatabaseURL = "postgresql://gusby_user:super_secure_pw@127.0.0.1:5432/gusby_db"
				c.SessionSecret = "this-is-a-very-long-production-secret-key-32-chars-long"
				c.GroqAPIKey = "gsk_valid_key"
			},
			wantError: false,
		},
		{
			name: "reject default dev database in production",
			modify: func(c *config.Config) {
				c.Env = "production"
				c.DatabaseURL = "postgresql://echo:echo_dev_password@127.0.0.1:5432/echo_kb"
				c.SessionSecret = "this-is-a-very-long-production-secret-key-32-chars-long"
				c.GroqAPIKey = "gsk_valid_key"
			},
			wantError: true,
		},
		{
			name: "reject insecure default session secret in production",
			modify: func(c *config.Config) {
				c.Env = "production"
				c.DatabaseURL = "postgresql://gusby_user:super_secure_pw@127.0.0.1:5432/gusby_db"
				c.SessionSecret = "gusby-default-insecure-secret-key-change-in-prod"
				c.GroqAPIKey = "gsk_valid_key"
			},
			wantError: true,
		},
		{
			name: "reject short session secret in production",
			modify: func(c *config.Config) {
				c.Env = "production"
				c.DatabaseURL = "postgresql://gusby_user:super_secure_pw@127.0.0.1:5432/gusby_db"
				c.SessionSecret = "short-secret"
				c.GroqAPIKey = "gsk_valid_key"
			},
			wantError: true,
		},
		{
			name: "reject missing groq key in production",
			modify: func(c *config.Config) {
				c.Env = "production"
				c.DatabaseURL = "postgresql://gusby_user:super_secure_pw@127.0.0.1:5432/gusby_db"
				c.SessionSecret = "this-is-a-very-long-production-secret-key-32-chars-long"
				c.GroqAPIKey = ""
			},
			wantError: true,
		},
		{
			name: "reject invalid port",
			modify: func(c *config.Config) {
				c.Port = 99999
			},
			wantError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := config.LoadConfig()
			tt.modify(cfg)
			err := cfg.Validate()
			if (err != nil) != tt.wantError {
				t.Errorf("Validate() error = %v, wantError %v", err, tt.wantError)
			}
		})
	}
}
