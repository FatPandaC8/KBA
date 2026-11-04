package main

import (
	"context"
	"fmt"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"gusby/internal/api"
	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/llm"
	"gusby/internal/observability"
	"gusby/internal/queue"
	"gusby/internal/store"
)

func main() {
	cfg := config.LoadConfig()
	if err := cfg.Validate(); err != nil {
		log.Fatalf("[Gusby] Configuration validation failed: %v", err)
	}

	// 0. Initialize Observability (Structured Logger, Prometheus Metrics, OpenTelemetry Tracer)
	logger := observability.InitLogger(cfg.Env, "gusby")
	metrics := observability.InitMetrics(cfg.Version, cfg.CommitSHA, runtime.Version())
	_, traceCleanup, err := observability.InitTracer("gusby", cfg.Env)
	if err != nil {
		logger.Warn("Failed to initialize OpenTelemetry tracer", slog.String("error", err.Error()))
	}

	logger.Info("Starting Gusby server",
		slog.String("version", cfg.Version),
		slog.String("commit", cfg.CommitSHA),
		slog.String("env", cfg.Env),
		slog.String("host", cfg.Host),
		slog.Int("port", cfg.Port),
		slog.String("model", cfg.GroqModel),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 1. Initialize Database Store
	dbStore, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("Fatal: failed to connect to PostgreSQL", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer dbStore.Close()
	logger.Info("Connected to PostgreSQL", slog.String("database", cfg.SanitizedDatabaseURL()))

	// Periodic DB pool and uptime metrics updater
	go func() {
		ticker := time.NewTicker(15 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				stat := dbStore.Pool().Stat()
				metrics.UpdateDBPool(stat.TotalConns(), stat.IdleConns(), stat.AcquiredConns(), stat.MaxConns())
				metrics.UpdateUptime()
			}
		}
	}()

	// Handle admin CLI commands before normal server startup
	if len(os.Args) > 1 && os.Args[1] == "admin" {
		handleAdminCLI(ctx, dbStore, os.Args[2:])
		return
	}

	// Seed development accounts if configured
	if err := auth.SeedDevUsers(ctx, dbStore); err != nil {
		log.Printf("[Gusby] Warning: failed to seed development accounts: %v", err)
	}

	// Bootstrap owner admin account if configured
	ownerEmail := os.Getenv("GUSBY_OWNER_EMAIL")
	if ownerEmail == "" {
		ownerEmail = os.Getenv("E2E_ADMIN_EMAIL")
	}
	if ownerEmail != "" {
		if err := auth.EnsureOwnerAdmin(ctx, dbStore, ownerEmail); err != nil {
			log.Printf("[Gusby] Warning: failed to ensure owner admin for %s: %v", ownerEmail, err)
		}
	}

	// 2. Initialize Groq LLM Client
	var llmClient llm.LLMClient
	if cfg.GroqAPIKey != "" {
		groq, err := llm.NewGroqClient(cfg.GroqAPIKey, cfg.GroqModel, cfg.GroqBaseURL, cfg.GroqRPM, cfg.GroqTPM)
		if err != nil {
			log.Fatalf("[Gusby] Fatal: failed to initialize Groq client: %v", err)
		}
		llmClient = groq
		log.Printf("[Gusby] Groq LLM client initialized (model: %s)", cfg.GroqModel)
	} else {
		log.Printf("[Gusby] WARNING: GROQ_API_KEY is not configured; using fallback mock LLM client")
		llmClient = llm.NewMockClient("{}")
	}

	// 3. Initialize & Start Background Queue Worker
	worker := queue.NewWorker("worker-primary", dbStore, llmClient)
	worker.Start(ctx)
	log.Printf("[Gusby] Background queue worker started (SKIP LOCKED polling)")

	// 4. Initialize HTTP Server
	server := api.NewServer(cfg, dbStore, llmClient)
	httpServer := &http.Server{
		Addr:              fmt.Sprintf("%s:%d", cfg.Host, cfg.Port),
		Handler:           server.Routes(),
		ReadTimeout:       15 * time.Second,
		ReadHeaderTimeout: 5 * time.Second,
		WriteTimeout:      45 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	// Graceful shutdown channel
	shutdownChan := make(chan os.Signal, 1)
	signal.Notify(shutdownChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Printf("[Gusby] HTTP API listening on http://%s", httpServer.Addr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[Gusby] Server error: %v", err)
		}
	}()

	<-shutdownChan
	log.Println("[Gusby] Shutdown signal received, shutting down gracefully...")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	// 1. Drain HTTP server connections
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("[Gusby] HTTP server shutdown error: %v", err)
	}

	// 2. Wait for background worker to complete any in-flight job
	if err := worker.Stop(shutdownCtx); err != nil {
		logger.Warn("Queue worker shutdown warning", slog.String("error", err.Error()))
	}

	// 3. Flush and clean up tracer provider
	if traceCleanup != nil {
		_ = traceCleanup(shutdownCtx)
	}

	cancel() // Cancel context
	logger.Info("Server, tracer, and background worker stopped successfully.")
}

func handleAdminCLI(ctx context.Context, s *store.Store, args []string) {
	if len(args) == 0 {
		fmt.Println("Usage: gusby admin [grant|revoke|list] [--email <email>]")
		os.Exit(1)
	}

	sub := args[0]
	switch sub {
	case "grant":
		var email string
		for i := 1; i < len(args); i++ {
			if args[i] == "--email" && i+1 < len(args) {
				email = args[i+1]
				break
			}
		}
		if email == "" {
			fmt.Println("Error: --email is required for 'admin grant'")
			os.Exit(1)
		}
		user, err := s.GetUserByEmail(ctx, email)
		if err != nil {
			log.Fatalf("Error finding user: %v", err)
		}
		if user == nil {
			log.Fatalf("User with email %s not found", email)
		}
		if err := s.SetUserAdmin(ctx, user.ID, true); err != nil {
			log.Fatalf("Error granting admin: %v", err)
		}
		fmt.Printf("Granted admin privileges to user %s (%s)\n", email, user.ID)

	case "revoke":
		var email string
		for i := 1; i < len(args); i++ {
			if args[i] == "--email" && i+1 < len(args) {
				email = args[i+1]
				break
			}
		}
		if email == "" {
			fmt.Println("Error: --email is required for 'admin revoke'")
			os.Exit(1)
		}
		user, err := s.GetUserByEmail(ctx, email)
		if err != nil {
			log.Fatalf("Error finding user: %v", err)
		}
		if user == nil {
			log.Fatalf("User with email %s not found", email)
		}
		if err := auth.ValidateAdminDemotion(ctx, s, user.ID); err != nil {
			log.Fatalf("Cannot revoke admin: %v", err)
		}
		if err := s.SetUserAdmin(ctx, user.ID, false); err != nil {
			log.Fatalf("Error revoking admin: %v", err)
		}
		fmt.Printf("Revoked admin privileges from user %s (%s)\n", email, user.ID)

	case "list":
		users, _, err := s.ListUsers(ctx, "", "", 100, 0)
		if err != nil {
			log.Fatalf("Error listing users: %v", err)
		}
		fmt.Printf("%-36s | %-30s | %-8s | %-8s\n", "User ID", "Email", "Status", "Admin")
		fmt.Println("-------------------------------------------------------------------------------------")
		for _, u := range users {
			if u.IsAdmin {
				fmt.Printf("%-36s | %-30s | %-8s | %-8t\n", u.ID, u.Email, u.Status, u.IsAdmin)
			}
		}

	default:
		fmt.Printf("Unknown admin command: %s. Available: grant, revoke, list\n", sub)
		os.Exit(1)
	}
}
