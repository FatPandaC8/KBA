package api

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/graph"
	"gusby/internal/ingest"
	"gusby/internal/llm"
	"gusby/internal/store"
)

type Server struct {
	cfg         *config.Config
	store       *store.Store
	authService *auth.Service
	llmClient   llm.LLMClient
	gate        *llm.AIGate
}

func NewServer(cfg *config.Config, s *store.Store, client ...llm.LLMClient) *Server {
	var c llm.LLMClient
	if len(client) > 0 && client[0] != nil {
		c = client[0]
	} else {
		c = llm.NewMockClient("{}")
	}
	gate := llm.NewAIGate(s, c, 3)

	return &Server{
		cfg:         cfg,
		store:       s,
		authService: auth.NewService(s),
		llmClient:   c,
		gate:        gate,
	}
}

// -----------------------------------------------------------------------------
// Response Helpers
// -----------------------------------------------------------------------------

func (s *Server) renderJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

func (s *Server) renderError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"error": map[string]string{
			"code":    code,
			"message": message,
		},
	})
}

// -----------------------------------------------------------------------------
// Health
// -----------------------------------------------------------------------------

func (s *Server) HandleHealth(w http.ResponseWriter, r *http.Request) {
	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "gusby",
		"version": "1.0.0",
	})
}

// -----------------------------------------------------------------------------
// Auth Handlers
// -----------------------------------------------------------------------------

type authRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (s *Server) HandleSignUp(w http.ResponseWriter, r *http.Request) {
	var req authRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	clientIP := r.RemoteAddr
	user, token, err := s.authService.SignUp(r.Context(), req.Email, req.Password, clientIP)
	if err != nil {
		if err == auth.ErrEmailAlreadyExists {
			s.renderError(w, http.StatusConflict, "EMAIL_EXISTS", err.Error())
			return
		}
		if err == auth.ErrPasswordTooShort || err == auth.ErrInvalidEmail {
			s.renderError(w, http.StatusBadRequest, "VALIDATION_FAILED", err.Error())
			return
		}
		if err == auth.ErrRateLimitExceeded {
			s.renderError(w, http.StatusTooManyRequests, "RATE_LIMITED", err.Error())
			return
		}
		s.renderError(w, http.StatusInternalServerError, "SERVER_ERROR", err.Error())
		return
	}

	auth.SetSessionCookie(w, token, s.cfg.Env == "production")
	s.renderJSON(w, http.StatusCreated, map[string]any{
		"user": map[string]any{
			"id":    user.ID,
			"email": user.Email,
		},
	})
}

func (s *Server) HandleLogin(w http.ResponseWriter, r *http.Request) {
	var req authRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	clientIP := r.RemoteAddr
	user, token, err := s.authService.Login(r.Context(), req.Email, req.Password, clientIP)
	if err != nil {
		if err == auth.ErrInvalidCredentials {
			s.renderError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS", "Invalid email or password")
			return
		}
		if err == auth.ErrRateLimitExceeded {
			s.renderError(w, http.StatusTooManyRequests, "RATE_LIMITED", err.Error())
			return
		}
		s.renderError(w, http.StatusInternalServerError, "SERVER_ERROR", err.Error())
		return
	}

	auth.SetSessionCookie(w, token, s.cfg.Env == "production")
	s.renderJSON(w, http.StatusOK, map[string]any{
		"user": map[string]any{
			"id":    user.ID,
			"email": user.Email,
		},
	})
}

func (s *Server) HandleLogout(w http.ResponseWriter, r *http.Request) {
	token := auth.GetSessionTokenFromRequest(r)
	_ = s.authService.Logout(r.Context(), token)
	auth.ClearSessionCookie(w, s.cfg.Env == "production")
	s.renderJSON(w, http.StatusOK, map[string]any{"success": true})
}

func (s *Server) HandleMe(w http.ResponseWriter, r *http.Request) {
	user := auth.UserFromContext(r.Context())
	if user == nil {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Not signed in")
		return
	}
	s.renderJSON(w, http.StatusOK, map[string]any{
		"user": map[string]any{
			"id":    user.ID,
			"email": user.Email,
		},
	})
}

type changePasswordRequest struct {
	CurrentPassword string `json:"current_password"`
	NewPassword     string `json:"new_password"`
}

func (s *Server) HandleChangePassword(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	var req changePasswordRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	if err := s.authService.ChangePassword(r.Context(), userID, req.CurrentPassword, req.NewPassword); err != nil {
		if err == auth.ErrInvalidCredentials {
			s.renderError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS", "Incorrect current password")
			return
		}
		if err == auth.ErrPasswordTooShort {
			s.renderError(w, http.StatusBadRequest, "PASSWORD_TOO_SHORT", "New password must be at least 8 characters")
			return
		}
		s.renderError(w, http.StatusInternalServerError, "SERVER_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"success": true})
}

// -----------------------------------------------------------------------------
// Ingestion Handlers
// -----------------------------------------------------------------------------

type textIngestRequest struct {
	Title   string `json:"title"`
	Content string `json:"content"`
}

func (s *Server) HandleIngestText(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	var req textIngestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	extDoc, err := ingest.ExtractFromPlainText(req.Title, req.Content)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "EXTRACTION_FAILED", err.Error())
		return
	}

	// Check if already ingested by this user
	existing, err := s.store.GetDocumentByHash(r.Context(), userID, extDoc.ContentHash)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}
	if existing != nil {
		s.renderJSON(w, http.StatusOK, map[string]any{
			"document_id": existing.ID,
			"status":      existing.Status,
			"title":       existing.Title,
			"duplicate":   true,
		})
		return
	}

	doc := &store.Document{
		UserID:      userID,
		Title:       extDoc.Title,
		SourceType:  extDoc.SourceType,
		ContentHash: extDoc.ContentHash,
		RawContent:  extDoc.RawContent,
		SourceText:  extDoc.SourceText,
		CharCount:   extDoc.CharCount,
		Status:      "uploading",
	}

	savedDoc, err := s.store.CreateDocument(r.Context(), doc)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	// Enqueue async processing job
	job, err := s.store.EnqueueJob(r.Context(), userID, savedDoc.ID, "queued", 10)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "JOB_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusAccepted, map[string]any{
		"document_id": savedDoc.ID,
		"status":      "processing",
		"title":       savedDoc.Title,
		"job_id":      job.ID,
	})
}

type urlIngestRequest struct {
	URL string `json:"url"`
}

func (s *Server) HandleIngestURL(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	var req urlIngestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	rawHTML, _, err := ingest.FetchSafeURL(r.Context(), req.URL)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "FETCH_FAILED", err.Error())
		return
	}

	extDoc, err := ingest.ExtractFromHTML(rawHTML, req.URL)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "EXTRACTION_FAILED", err.Error())
		return
	}

	existing, err := s.store.GetDocumentByHash(r.Context(), userID, extDoc.ContentHash)
	if err == nil && existing != nil {
		s.renderJSON(w, http.StatusOK, map[string]any{
			"document_id": existing.ID,
			"status":      existing.Status,
			"title":       existing.Title,
			"duplicate":   true,
		})
		return
	}

	doc := &store.Document{
		UserID:      userID,
		Title:       extDoc.Title,
		SourceType:  "url",
		SourceURL:   extDoc.SourceURL,
		ContentHash: extDoc.ContentHash,
		RawContent:  extDoc.RawContent,
		SourceText:  extDoc.SourceText,
		CharCount:   extDoc.CharCount,
		Status:      "uploading",
	}

	savedDoc, err := s.store.CreateDocument(r.Context(), doc)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	job, err := s.store.EnqueueJob(r.Context(), userID, savedDoc.ID, "queued", 10)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "JOB_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusAccepted, map[string]any{
		"document_id": savedDoc.ID,
		"status":      "processing",
		"title":       savedDoc.Title,
		"job_id":      job.ID,
	})
}

func (s *Server) HandleIngestFile(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	// 10 MB limit
	if err := r.ParseMultipartForm(10 * 1024 * 1024); err != nil {
		s.renderError(w, http.StatusBadRequest, "FILE_TOO_LARGE", "File exceeds 10MB limit")
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "FILE_MISSING", "No file uploaded in form field 'file'")
		return
	}
	defer file.Close()

	fileBytes, err := io.ReadAll(file)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "READ_ERROR", "Failed to read file")
		return
	}

	filename := header.Filename
	title := r.FormValue("title")
	if title == "" {
		title = filename
	}

	var extDoc *ingest.ExtractedDocument
	lowerName := strings.ToLower(filename)

	if strings.HasSuffix(lowerName, ".pdf") {
		extDoc, err = ingest.ExtractFromPDF(fileBytes, title)
	} else if strings.HasSuffix(lowerName, ".docx") {
		extDoc, err = ingest.ExtractFromDOCX(fileBytes, title)
	} else if strings.HasSuffix(lowerName, ".txt") {
		extDoc, err = ingest.ExtractFromPlainText(title, string(fileBytes))
	} else {
		s.renderError(w, http.StatusBadRequest, "UNSUPPORTED_TYPE", "Supported formats: .pdf, .docx, .txt")
		return
	}

	if err != nil {
		s.renderError(w, http.StatusBadRequest, "EXTRACTION_FAILED", err.Error())
		return
	}

	existing, err := s.store.GetDocumentByHash(r.Context(), userID, extDoc.ContentHash)
	if err == nil && existing != nil {
		s.renderJSON(w, http.StatusOK, map[string]any{
			"document_id": existing.ID,
			"status":      existing.Status,
			"title":       existing.Title,
			"duplicate":   true,
		})
		return
	}

	doc := &store.Document{
		UserID:      userID,
		Title:       extDoc.Title,
		SourceType:  extDoc.SourceType,
		ContentHash: extDoc.ContentHash,
		RawContent:  extDoc.RawContent,
		SourceText:  extDoc.SourceText,
		CharCount:   extDoc.CharCount,
		Status:      "uploading",
	}

	savedDoc, err := s.store.CreateDocument(r.Context(), doc)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	job, err := s.store.EnqueueJob(r.Context(), userID, savedDoc.ID, "queued", 10)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "JOB_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusAccepted, map[string]any{
		"document_id": savedDoc.ID,
		"status":      "processing",
		"title":       savedDoc.Title,
		"job_id":      job.ID,
	})
}

func (s *Server) HandleListDocuments(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	status := r.URL.Query().Get("status")
	limit := 50
	if l := r.URL.Query().Get("limit"); l != "" {
		if val, err := strconv.Atoi(l); err == nil && val > 0 && val <= 100 {
			limit = val
		}
	}
	offset := 0
	if o := r.URL.Query().Get("offset"); o != "" {
		if val, err := strconv.Atoi(o); err == nil && val >= 0 {
			offset = val
		}
	}

	docs, total, err := s.store.ListDocuments(r.Context(), userID, status, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"documents": docs,
		"total":     total,
	})
}

func (s *Server) HandleGetDocument(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	docIDStr := chi.URLParam(r, "id")
	docID, err := uuid.Parse(docIDStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid document UUID")
		return
	}

	doc, err := s.store.GetDocumentByID(r.Context(), userID, docID)
	if err != nil || doc == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "Document not found")
		return
	}

	chunks, _ := s.store.GetChunksByDocumentID(r.Context(), userID, docID)
	s.renderJSON(w, http.StatusOK, map[string]any{
		"document": doc,
		"chunks":   chunks,
	})
}

// -----------------------------------------------------------------------------
// Graph Handlers
// -----------------------------------------------------------------------------

func (s *Server) HandleGetGraph(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	zoom := r.URL.Query().Get("zoom")
	if zoom == "" {
		zoom = "deep"
	}

	var topicID *uuid.UUID
	if t := r.URL.Query().Get("topic_id"); t != "" {
		if parsed, err := uuid.Parse(t); err == nil {
			topicID = &parsed
		}
	}

	filterReview := r.URL.Query().Get("needs_review") == "true"

	projection, err := graph.GetProjection(r.Context(), s.store, userID, zoom, topicID, filterReview)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "GRAPH_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, projection)
}

func (s *Server) HandleGetConcept(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	idStr := chi.URLParam(r, "id")
	cid, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid concept UUID")
		return
	}

	concept, err := s.store.GetConceptByID(r.Context(), userID, cid)
	if err != nil || concept == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "Concept not found")
		return
	}

	props, _ := s.store.FindPropositionBySubjectAndPredicate(r.Context(), userID, cid, "")

	s.renderJSON(w, http.StatusOK, map[string]any{
		"concept":      concept,
		"propositions": props,
	})
}

func (s *Server) HandleGetProposition(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	idStr := chi.URLParam(r, "id")
	pid, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid proposition UUID")
		return
	}

	evList, err := s.store.GetEvidenceForProposition(r.Context(), userID, pid)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"proposition_id": pid,
		"evidence":       evList,
	})
}

func (s *Server) HandleSearchGraph(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	query := r.URL.Query().Get("q")
	if query == "" {
		s.renderJSON(w, http.StatusOK, map[string]any{"results": []any{}})
		return
	}

	concepts, _, err := s.store.FindConceptsByTrigram(r.Context(), userID, query, 0.30, 20)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"results": concepts,
	})
}

// -----------------------------------------------------------------------------
// Review Handlers
// -----------------------------------------------------------------------------

func (s *Server) HandleListProposals(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	proposals, err := s.store.ListPendingProposals(r.Context(), userID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"proposals": proposals,
	})
}

type resolveProposalRequest struct {
	Action string `json:"action"` // approve or reject
	Notes  string `json:"notes"`
}

func (s *Server) HandleResolveProposal(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	idStr := chi.URLParam(r, "id")
	pid, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid proposal UUID")
		return
	}

	var req resolveProposalRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	if req.Action != "approve" && req.Action != "reject" {
		s.renderError(w, http.StatusBadRequest, "INVALID_ACTION", "Action must be 'approve' or 'reject'")
		return
	}

	if err := s.store.ResolveProposal(r.Context(), userID, pid, req.Action, "user", req.Notes); err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"success": true, "proposal_id": pid})
}

func (s *Server) HandleListConflicts(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	conflicts, err := s.store.ListOpenConflicts(r.Context(), userID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"conflicts": conflicts,
	})
}

type resolveConflictRequest struct {
	ResolutionChoice string `json:"resolution_choice"`
	Reason           string `json:"reason"`
}

func (s *Server) HandleResolveConflict(w http.ResponseWriter, r *http.Request) {
	userID, ok := auth.UserIDFromContext(r.Context())
	if !ok {
		s.renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Unauthorized")
		return
	}

	idStr := chi.URLParam(r, "id")
	cid, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid conflict UUID")
		return
	}

	var req resolveConflictRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_BODY", "Invalid JSON payload")
		return
	}

	if err := s.store.ResolveConflict(r.Context(), userID, cid, "user", req.ResolutionChoice, req.Reason); err != nil {
		s.renderError(w, http.StatusInternalServerError, "DATABASE_ERROR", err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"success": true, "conflict_id": cid})
}
