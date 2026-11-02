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

	return r
}
