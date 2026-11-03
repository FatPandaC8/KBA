package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"

	"gusby/internal/auth"
)

func (s *Server) Routes() http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	// CORS configuration for desktop frontend
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"http://127.0.0.1:3000", "http://localhost:3000"},
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-CSRF-Token"},
		ExposedHeaders:   []string{"Link", "Set-Cookie"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	r.Use(auth.CSRFProtection())

	// Public APIs
	r.Get("/api/health", s.HandleHealth)
	r.Post("/api/auth/signup", s.HandleSignUp)
	r.Post("/api/auth/login", s.HandleLogin)
	r.Post("/api/auth/logout", s.HandleLogout)

	// Protected APIs
	r.Group(func(protected chi.Router) {
		protected.Use(auth.RequireAuth(s.authService))

		protected.Get("/api/auth/me", s.HandleMe)
		protected.Post("/api/auth/password", s.HandleChangePassword)

		// Document Ingestion
		protected.Post("/api/documents/text", s.HandleIngestText)
		protected.Post("/api/documents/url", s.HandleIngestURL)
		protected.Post("/api/documents/file", s.HandleIngestFile)
		protected.Get("/api/documents", s.HandleListDocuments)
		protected.Get("/api/documents/{id}", s.HandleGetDocument)

		// Knowledge Graph
		protected.Get("/api/graph", s.HandleGetGraph)
		protected.Get("/api/graph/concept/{id}", s.HandleGetConcept)
		protected.Get("/api/graph/proposition/{id}", s.HandleGetProposition)
		protected.Get("/api/graph/search", s.HandleSearchGraph)

		// Review & Conflicts
		protected.Get("/api/review/proposals", s.HandleListProposals)
		protected.Post("/api/review/proposals/{id}/resolve", s.HandleResolveProposal)
		protected.Get("/api/review/conflicts", s.HandleListConflicts)
		protected.Post("/api/review/conflicts/{id}/resolve", s.HandleResolveConflict)
	})

	// Admin APIs (Protected by RequireAdmin - returns HTTP 404 for unauthorized callers)
	r.Group(func(admin chi.Router) {
		admin.Use(auth.RequireAdmin(s.authService))

		// Monitoring & Overview
		admin.Get("/api/admin/overview", s.HandleAdminOverview)
		admin.Get("/api/admin/pipeline", s.HandleAdminPipeline)
		admin.Post("/api/admin/pipeline/jobs/{id}/retry", s.HandleAdminRetryJob)

		// AI Observability & Control
		admin.Get("/api/admin/ai/health", s.HandleAdminAIHealth)
		admin.Get("/api/admin/ai/metrics", s.HandleAdminAIMetrics)
		admin.Get("/api/admin/ai/eval-runs", s.HandleAdminAIEvalRuns)
		admin.Post("/api/admin/ai/probe", s.HandleAdminAIProbe)
		admin.Get("/api/admin/ai/gate", s.HandleAdminAIGetGate)
		admin.Post("/api/admin/ai/gate/pause", s.HandleAdminAIPauseGate)
		admin.Post("/api/admin/ai/gate/resume", s.HandleAdminAIResumeGate)
		admin.Post("/api/admin/ai/gate/reset-breaker", s.HandleAdminAIResetBreaker)

		// User Management
		admin.Get("/api/admin/users", s.HandleAdminListUsers)
		admin.Get("/api/admin/users/{id}", s.HandleAdminGetUser)
		admin.Post("/api/admin/users/{id}/suspend", s.HandleAdminSuspendUser)
		admin.Post("/api/admin/users/{id}/unsuspend", s.HandleAdminUnsuspendUser)
		admin.Post("/api/admin/users/{id}/reset-limits", s.HandleAdminResetUserLimits)
		admin.Delete("/api/admin/users/{id}", s.HandleAdminDeleteUser)

		// Document Management
		admin.Get("/api/admin/documents", s.HandleAdminListDocuments)
		admin.Get("/api/admin/documents/{id}", s.HandleAdminGetDocument)
		admin.Post("/api/admin/documents/{id}/reprocess", s.HandleAdminReprocessDocument)
		admin.Delete("/api/admin/documents/{id}", s.HandleAdminDeleteDocument)

		// Graph Data Administration
		admin.Get("/api/admin/graph/concepts", s.HandleAdminListConcepts)
		admin.Post("/api/admin/graph/concepts/merge", s.HandleAdminMergeConcepts)
		admin.Put("/api/admin/graph/concepts/{id}", s.HandleAdminUpdateConcept)
		admin.Delete("/api/admin/graph/concepts/{id}", s.HandleAdminDeleteConcept)

		admin.Get("/api/admin/graph/propositions", s.HandleAdminListPropositions)
		admin.Post("/api/admin/graph/propositions", s.HandleAdminCreateProposition)
		admin.Post("/api/admin/graph/propositions/{id}/retract", s.HandleAdminRetractProposition)
		admin.Post("/api/admin/graph/propositions/{id}/restore", s.HandleAdminRestoreProposition)

		admin.Get("/api/admin/graph/topics", s.HandleAdminListTopics)
		admin.Put("/api/admin/graph/topics/{id}", s.HandleAdminUpdateTopic)

		admin.Get("/api/admin/graph/conflicts", s.HandleAdminListConflicts)
		admin.Post("/api/admin/graph/conflicts/{id}/resolve", s.HandleAdminResolveConflict)

		// Audit Log
		admin.Get("/api/admin/audit", s.HandleAdminListAuditLogs)
	})

	return r
}
