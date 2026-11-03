package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"gusby/internal/api"
	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/llm"
	"gusby/internal/queue"
	"gusby/internal/store"
)

func main() {
	cfg := config.LoadConfig()

	log.Printf("[Gusby] Starting server (env: %s, port: %d, model: %s)...", cfg.Env, cfg.Port, cfg.GroqModel)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 1. Initialize Database Store
	dbStore, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("[Gusby] Fatal: failed to connect to PostgreSQL: %v", err)
	}
	defer dbStore.Close()
	log.Printf("[Gusby] Connected to PostgreSQL at %s", cfg.DatabaseURL)

	// Seed development accounts if configured
	if err := auth.SeedDevUsers(ctx, dbStore); err != nil {
		log.Printf("[Gusby] Warning: failed to seed development accounts: %v", err)
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
	server := api.NewServer(cfg, dbStore)
	httpServer := &http.Server{
		Addr:         fmt.Sprintf("127.0.0.1:%d", cfg.Port),
		Handler:      server.Routes(),
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 45 * time.Second,
		IdleTimeout:  60 * time.Second,
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
	log.Println("[Gusby] Shutting down gracefully...")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	cancel() // Stop background workers
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("[Gusby] Shutdown error: %v", err)
	}
	log.Println("[Gusby] Server stopped.")
}
