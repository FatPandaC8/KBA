package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"gusby/internal/auth"
	"gusby/internal/llm"
	"gusby/internal/store"
)

func getAdminUser(r *http.Request) *store.User {
	if u, ok := r.Context().Value(auth.UserContextKey).(*store.User); ok {
		return u
	}
	return nil
}

// -----------------------------------------------------------------------------
// Phase 4: Monitoring & AI Observability Handlers
// -----------------------------------------------------------------------------

func (s *Server) HandleAdminOverview(w http.ResponseWriter, r *http.Request) {
	metrics, err := s.store.GetAdminOverviewMetrics(r.Context())
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to retrieve overview metrics: "+err.Error())
		return
	}

	gateState, _ := s.gate.GetState(r.Context())
	desc := s.llmClient.Describe()

	resp := map[string]any{
		"metrics": metrics,
		"ai_provider": map[string]any{
			"kind":         desc.Kind,
			"model":        desc.Model,
			"is_configured": desc.IsConfigured,
		},
		"ai_gate": gateState,
	}

	s.renderJSON(w, http.StatusOK, resp)
}

func (s *Server) HandleAdminPipeline(w http.ResponseWriter, r *http.Request) {
	stage := r.URL.Query().Get("stage")
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	metrics, err := s.store.GetPipelineMetrics(r.Context())
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to fetch pipeline metrics: "+err.Error())
		return
	}

	jobs, total, err := s.store.ListAdminJobs(r.Context(), stage, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list pipeline jobs: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"metrics": metrics,
		"jobs":    jobs,
		"total":   total,
		"limit":   limit,
		"offset":  offset,
	})
}

func (s *Server) HandleAdminRetryJob(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	jobID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid job UUID")
		return
	}

	if err := s.store.RetryJob(r.Context(), jobID); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to retry job: "+err.Error())
		return
	}

	admin := getAdminUser(r)
	if admin != nil {
		_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
			ID:         uuid.New(),
			AdminID:    admin.ID,
			ActionType: "pipeline_retry",
			TargetType: "job",
			TargetID:   &jobID,
			Reason:     strPtr("Manual job retry by administrator"),
			CreatedAt:  time.Now(),
		})
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":  "queued",
		"job_id":  jobID,
		"message": "Job re-queued successfully",
	})
}

func (s *Server) HandleAdminAIHealth(w http.ResponseWriter, r *http.Request) {
	desc := s.llmClient.Describe()
	health, err := s.llmClient.Health(r.Context())
	if err != nil {
		health = llm.ProviderHealth{
			Status:    "degraded",
			Reason:    "Health probe execution failed: " + err.Error(),
			LatencyMs: 0,
			Details:   map[string]any{},
		}
	}

	gateState, err := s.gate.GetState(r.Context())
	if err != nil {
		gateState = &store.AIGateState{
			State:     "unknown",
			Reason:    "Failed to retrieve gate state: " + err.Error(),
			UpdatedAt: time.Now(),
		}
	}

	// Overall status derivation
	overallStatus := health.Status
	overallReason := health.Reason
	if gateState.State == "paused" {
		overallStatus = "paused"
		overallReason = "AI Gate is manually paused by administrator"
	} else if gateState.State == "circuit_open" {
		overallStatus = "down"
		overallReason = "Circuit breaker tripped due to consecutive failures"
	}

	resp := map[string]any{
		"status":     overallStatus,
		"reason":     overallReason,
		"latency_ms": health.LatencyMs,
		"provider":   desc,
		"gate": map[string]any{
			"state":                gateState.State,
			"reason":               gateState.Reason,
			"consecutive_failures": gateState.ConsecutiveFailures,
			"updated_at":           gateState.UpdatedAt,
		},
		"details": health.Details,
	}

	s.renderJSON(w, http.StatusOK, resp)
}

func (s *Server) HandleAdminAIMetrics(w http.ResponseWriter, r *http.Request) {
	window := r.URL.Query().Get("window")
	if window != "1h" && window != "7d" {
		window = "24h"
	}

	metrics, err := s.store.GetAIMetrics(r.Context(), window)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to retrieve AI metrics: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, metrics)
}

func (s *Server) HandleAdminAIEvalRuns(w http.ResponseWriter, r *http.Request) {
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 20
	}

	runs, err := s.store.ListEvalRuns(r.Context(), limit)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list eval runs: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"eval_runs": runs,
	})
}

func (s *Server) HandleAdminAIProbe(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	adminEmail := "system"
	if admin != nil {
		adminEmail = admin.Email
	}

	probeRes, err := s.gate.RunProbe(r.Context(), adminEmail)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to run AI probe: "+err.Error())
		return
	}

	if admin != nil {
		_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
			ID:         uuid.New(),
			AdminID:    admin.ID,
			ActionType: "ai_probe",
			TargetType: "ai_provider",
			Reason:     strPtr(fmt.Sprintf("Probe result: %s (latency: %dms)", probeRes.Status, probeRes.LatencyMs)),
			CreatedAt:  time.Now(),
		})
	}

	s.renderJSON(w, http.StatusOK, probeRes)
}

func (s *Server) HandleAdminAIGetGate(w http.ResponseWriter, r *http.Request) {
	state, err := s.gate.GetState(r.Context())
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to get gate state: "+err.Error())
		return
	}
	s.renderJSON(w, http.StatusOK, state)
}

func (s *Server) HandleAdminAIPauseGate(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Reason == "" {
		body.Reason = "Manual administrator pause"
	}

	admin := getAdminUser(r)
	adminEmail := "admin"
	if admin != nil {
		adminEmail = admin.Email
	}

	if err := s.gate.Pause(r.Context(), body.Reason, adminEmail); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to pause AI gate: "+err.Error())
		return
	}

	if admin != nil {
		_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
			ID:         uuid.New(),
			AdminID:    admin.ID,
			ActionType: "ai_gate_pause",
			TargetType: "ai_gate",
			Reason:     &body.Reason,
			CreatedAt:  time.Now(),
		})
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"state": "paused", "reason": body.Reason})
}

func (s *Server) HandleAdminAIResumeGate(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	adminEmail := "admin"
	if admin != nil {
		adminEmail = admin.Email
	}

	if err := s.gate.Resume(r.Context(), adminEmail); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to resume AI gate: "+err.Error())
		return
	}

	if admin != nil {
		_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
			ID:         uuid.New(),
			AdminID:    admin.ID,
			ActionType: "ai_gate_resume",
			TargetType: "ai_gate",
			Reason:     strPtr("Resumed by administrator"),
			CreatedAt:  time.Now(),
		})
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"state": "enabled", "reason": "Resumed by administrator"})
}

func (s *Server) HandleAdminAIResetBreaker(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	adminEmail := "admin"
	if admin != nil {
		adminEmail = admin.Email
	}

	if err := s.gate.ResetBreaker(r.Context(), adminEmail); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to reset circuit breaker: "+err.Error())
		return
	}

	if admin != nil {
		_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
			ID:         uuid.New(),
			AdminID:    admin.ID,
			ActionType: "ai_circuit_reset",
			TargetType: "ai_gate",
			Reason:     strPtr("Circuit breaker manually reset"),
			CreatedAt:  time.Now(),
		})
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"state": "enabled", "reason": "Circuit breaker reset to enabled"})
}

// -----------------------------------------------------------------------------
// Phase 5: User & Document Management Handlers
// -----------------------------------------------------------------------------

func (s *Server) HandleAdminListUsers(w http.ResponseWriter, r *http.Request) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	status := strings.TrimSpace(r.URL.Query().Get("status"))
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	users, total, err := s.store.ListUsers(r.Context(), q, status, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list users: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"users":  users,
		"total":  total,
		"limit":  limit,
		"offset": offset,
	})
}

func (s *Server) HandleAdminGetUser(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	targetID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid user ID")
		return
	}

	user, err := s.store.GetUserByID(r.Context(), targetID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to get user: "+err.Error())
		return
	}
	if user == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "User not found")
		return
	}

	s.renderJSON(w, http.StatusOK, user)
}

func (s *Server) HandleAdminSuspendUser(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	targetID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid user ID")
		return
	}

	if err := auth.ValidateUserSelfAction(admin.ID, targetID); err != nil {
		s.renderError(w, http.StatusBadRequest, "SELF_ACTION_FORBIDDEN", err.Error())
		return
	}

	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Reason == "" {
		body.Reason = "Suspended by administrator"
	}

	if err := s.store.SetUserStatus(r.Context(), targetID, "suspended"); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to suspend user: "+err.Error())
		return
	}
	_ = s.store.RevokeUserSessions(r.Context(), targetID)

	_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
		ID:           uuid.New(),
		AdminID:      admin.ID,
		ActionType:   "user_suspend",
		TargetType:   "user",
		TargetID:     &targetID,
		TargetUserID: &targetID,
		Reason:       &body.Reason,
		CreatedAt:    time.Now(),
	})

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "suspended", "user_id": targetID})
}

func (s *Server) HandleAdminUnsuspendUser(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	targetID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid user ID")
		return
	}

	if err := s.store.SetUserStatus(r.Context(), targetID, "active"); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to unsuspend user: "+err.Error())
		return
	}

	_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
		ID:           uuid.New(),
		AdminID:      admin.ID,
		ActionType:   "user_unsuspend",
		TargetType:   "user",
		TargetID:     &targetID,
		TargetUserID: &targetID,
		Reason:       strPtr("Unsuspended by administrator"),
		CreatedAt:    time.Now(),
	})

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "active", "user_id": targetID})
}

func (s *Server) HandleAdminResetUserLimits(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	targetID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid user ID")
		return
	}

	if err := s.store.ResetUserLimits(r.Context(), targetID); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to reset limits: "+err.Error())
		return
	}

	_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
		ID:           uuid.New(),
		AdminID:      admin.ID,
		ActionType:   "user_reset_limits",
		TargetType:   "user",
		TargetID:     &targetID,
		TargetUserID: &targetID,
		Reason:       strPtr("Token usage limits reset by administrator"),
		CreatedAt:    time.Now(),
	})

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "reset", "user_id": targetID})
}

func (s *Server) HandleAdminDeleteUser(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	targetID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid user ID")
		return
	}

	if err := auth.ValidateUserSelfAction(admin.ID, targetID); err != nil {
		s.renderError(w, http.StatusBadRequest, "SELF_ACTION_FORBIDDEN", err.Error())
		return
	}

	if err := auth.ValidateAdminDemotion(r.Context(), s.store, targetID); err != nil {
		s.renderError(w, http.StatusBadRequest, "LAST_ADMIN_PROTECTED", err.Error())
		return
	}

	targetUser, err := s.store.GetUserByID(r.Context(), targetID)
	if err != nil || targetUser == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "User not found")
		return
	}

	var body struct {
		ConfirmEmail string `json:"confirm_email"`
		Reason       string `json:"reason"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || strings.TrimSpace(body.ConfirmEmail) != targetUser.Email {
		s.renderError(w, http.StatusBadRequest, "CONFIRMATION_MISMATCH", "Exact user email confirmation required")
		return
	}

	counts, err := s.store.DeleteUserAndAllData(r.Context(), targetID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to delete user: "+err.Error())
		return
	}

	beforeState := map[string]any{
		"deleted_email": targetUser.Email,
		"purged_counts": counts,
	}

	_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
		ID:           uuid.New(),
		AdminID:      admin.ID,
		ActionType:   "user_delete",
		TargetType:   "user",
		TargetID:     &targetID,
		TargetUserID: &targetID,
		TargetEmail:  targetUser.Email,
		Reason:       strPtr(body.Reason),
		BeforeState:  beforeState,
		CreatedAt:    time.Now(),
	})

	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":        "deleted",
		"deleted_email": targetUser.Email,
		"purged":        counts,
	})
}

func (s *Server) HandleAdminListDocuments(w http.ResponseWriter, r *http.Request) {
	status := strings.TrimSpace(r.URL.Query().Get("status"))
	var targetUserID *uuid.UUID
	if uStr := strings.TrimSpace(r.URL.Query().Get("user_id")); uStr != "" {
		if uID, err := uuid.Parse(uStr); err == nil {
			targetUserID = &uID
		}
	}

	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	docs, total, err := s.store.ListAdminDocuments(r.Context(), targetUserID, status, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list documents: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"documents": docs,
		"total":     total,
		"limit":     limit,
		"offset":    offset,
	})
}

func (s *Server) HandleAdminGetDocument(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	docID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid document ID")
		return
	}

	details, err := s.store.GetAdminDocumentDetails(r.Context(), docID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to get document: "+err.Error())
		return
	}
	if details == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "Document not found")
		return
	}

	s.renderJSON(w, http.StatusOK, details)
}

func (s *Server) HandleAdminReprocessDocument(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	docID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid document ID")
		return
	}

	doc, err := s.store.GetAdminDocumentDetails(r.Context(), docID)
	if err != nil || doc == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "Document not found")
		return
	}

	var userID uuid.UUID
	if uid, ok := doc["user_id"].(uuid.UUID); ok {
		userID = uid
	} else if uidStr, ok := doc["user_id"].(string); ok {
		userID, _ = uuid.Parse(uidStr)
	}

	// Create new queued job for reprocess
	job, err := s.store.EnqueueJob(r.Context(), userID, docID, "queued", 1)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to create processing job: "+err.Error())
		return
	}

	_ = s.store.UpdateDocumentStatus(r.Context(), userID, docID, "queued", nil)

	_ = s.store.CreateAdminAuditLog(r.Context(), &store.AdminAuditLog{
		ID:           uuid.New(),
		AdminID:      admin.ID,
		ActionType:   "document_reprocess",
		TargetType:   "document",
		TargetID:     &docID,
		TargetUserID: &userID,
		Reason:       strPtr("Manual reprocess triggered by administrator"),
		CreatedAt:    time.Now(),
	})

	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":  "queued",
		"job_id":  job.ID,
		"message": "Document re-processing queued successfully",
	})
}

func (s *Server) HandleAdminDeleteDocument(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	docID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid document ID")
		return
	}

	doc, err := s.store.GetAdminDocumentDetails(r.Context(), docID)
	if err != nil || doc == nil {
		s.renderError(w, http.StatusNotFound, "NOT_FOUND", "Document not found")
		return
	}

	title, _ := doc["title"].(string)

	var body struct {
		ConfirmTitle string `json:"confirm_title"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || strings.TrimSpace(body.ConfirmTitle) != title {
		s.renderError(w, http.StatusBadRequest, "CONFIRMATION_MISMATCH", "Exact document title confirmation required")
		return
	}

	retractedProps, orphanedConcepts, err := s.store.DeleteDocumentWithCascadeRetraction(r.Context(), admin.ID, docID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to delete document: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":            "deleted",
		"document_id":       docID,
		"retracted_props":   retractedProps,
		"orphaned_concepts": orphanedConcepts,
	})
}

// -----------------------------------------------------------------------------
// Phase 6: Graph Data Administration Handlers
// -----------------------------------------------------------------------------

func (s *Server) HandleAdminListConcepts(w http.ResponseWriter, r *http.Request) {
	userStr := r.URL.Query().Get("user_id")
	userID, err := uuid.Parse(userStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "USER_REQUIRED", "user_id is required to scope graph queries")
		return
	}

	q := strings.TrimSpace(r.URL.Query().Get("q"))
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	concepts, total, err := s.store.AdminListConcepts(r.Context(), userID, q, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list concepts: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"concepts": concepts,
		"total":    total,
		"limit":    limit,
		"offset":   offset,
	})
}

func (s *Server) HandleAdminMergeConcepts(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	var body struct {
		UserID   uuid.UUID `json:"user_id"`
		SourceID uuid.UUID `json:"source_concept_id"`
		TargetID uuid.UUID `json:"target_concept_id"`
		Reason   string    `json:"reason"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Invalid JSON payload")
		return
	}
	if body.SourceID == body.TargetID {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Source and target concept IDs must be distinct")
		return
	}

	rewired, err := s.store.AdminMergeConcepts(r.Context(), admin.ID, body.UserID, body.SourceID, body.TargetID, body.Reason)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to merge concepts: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"status":                 "merged",
		"rewired_propositions": rewired,
	})
}

func (s *Server) HandleAdminUpdateConcept(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	conceptID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid concept ID")
		return
	}

	var body struct {
		UserID      uuid.UUID `json:"user_id"`
		Name        string    `json:"name"`
		Description *string   `json:"description"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Concept name is required")
		return
	}

	if err := s.store.AdminUpdateConcept(r.Context(), body.UserID, conceptID, body.Name, body.Description); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to update concept: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "updated", "concept_id": conceptID})
}

func (s *Server) HandleAdminDeleteConcept(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	conceptID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid concept ID")
		return
	}

	var body struct {
		UserID uuid.UUID `json:"user_id"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	if err := s.store.AdminDeleteConcept(r.Context(), admin.ID, body.UserID, conceptID); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to archive concept: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "archived", "concept_id": conceptID})
}

func (s *Server) HandleAdminListPropositions(w http.ResponseWriter, r *http.Request) {
	userStr := r.URL.Query().Get("user_id")
	userID, err := uuid.Parse(userStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "USER_REQUIRED", "user_id is required to scope graph queries")
		return
	}

	status := strings.TrimSpace(r.URL.Query().Get("status"))
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	props, total, err := s.store.AdminListPropositions(r.Context(), userID, status, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list propositions: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"propositions": props,
		"total":        total,
		"limit":        limit,
		"offset":       offset,
	})
}

func (s *Server) HandleAdminCreateProposition(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	var body struct {
		UserID           uuid.UUID `json:"user_id"`
		SubjectConceptID uuid.UUID `json:"subject_concept_id"`
		ObjectConceptID  uuid.UUID `json:"object_concept_id"`
		DocumentID       uuid.UUID `json:"document_id"`
		Predicate        string    `json:"predicate"`
		Quote            string    `json:"quote"`
		ByteStart        int       `json:"byte_start"`
		ByteEnd          int       `json:"byte_end"`
		CharStart        int       `json:"char_start"`
		CharEnd          int       `json:"char_end"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Invalid JSON payload")
		return
	}

	if body.Quote == "" || body.Predicate == "" {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Predicate and verbatim quote evidence are mandatory")
		return
	}

	prop, err := s.store.AdminCreatePropositionWithEvidence(
		r.Context(), admin.ID, body.UserID, body.SubjectConceptID, body.ObjectConceptID,
		body.DocumentID, body.Predicate, body.Quote, body.ByteStart, body.ByteEnd, body.CharStart, body.CharEnd,
	)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "VALIDATION_FAILED", "Failed to create proposition with evidence: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusCreated, prop)
}

func (s *Server) HandleAdminRetractProposition(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	propID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid proposition ID")
		return
	}

	var body struct {
		UserID uuid.UUID `json:"user_id"`
		Reason string    `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Reason == "" {
		body.Reason = "Retracted by administrator"
	}

	if err := s.store.AdminRetractProposition(r.Context(), admin.ID, body.UserID, propID, body.Reason); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to retract proposition: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "retracted", "proposition_id": propID})
}

func (s *Server) HandleAdminRestoreProposition(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	propID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid proposition ID")
		return
	}

	var body struct {
		UserID uuid.UUID `json:"user_id"`
		Reason string    `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Reason == "" {
		body.Reason = "Restored by administrator"
	}

	if err := s.store.AdminRestoreProposition(r.Context(), admin.ID, body.UserID, propID, body.Reason); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to restore proposition: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "active", "proposition_id": propID})
}

func (s *Server) HandleAdminListTopics(w http.ResponseWriter, r *http.Request) {
	userStr := r.URL.Query().Get("user_id")
	userID, err := uuid.Parse(userStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "USER_REQUIRED", "user_id is required to scope graph queries")
		return
	}

	topics, err := s.store.AdminListTopics(r.Context(), userID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list topics: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"topics": topics})
}

func (s *Server) HandleAdminUpdateTopic(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	topicID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid topic ID")
		return
	}

	var body struct {
		UserID      uuid.UUID `json:"user_id"`
		Name        string    `json:"name"`
		Description *string   `json:"description"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Topic name is required")
		return
	}

	if err := s.store.AdminUpdateTopic(r.Context(), body.UserID, topicID, body.Name, body.Description); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to update topic: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "updated", "topic_id": topicID})
}

func (s *Server) HandleAdminListConflicts(w http.ResponseWriter, r *http.Request) {
	userStr := r.URL.Query().Get("user_id")
	userID, err := uuid.Parse(userStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "USER_REQUIRED", "user_id is required to scope graph queries")
		return
	}

	conflicts, err := s.store.AdminListConflicts(r.Context(), userID)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list conflicts: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"conflicts": conflicts})
}

func (s *Server) HandleAdminResolveConflict(w http.ResponseWriter, r *http.Request) {
	admin := getAdminUser(r)
	idStr := chi.URLParam(r, "id")
	conflictID, err := uuid.Parse(idStr)
	if err != nil {
		s.renderError(w, http.StatusBadRequest, "INVALID_ID", "Invalid conflict ID")
		return
	}

	var body struct {
		UserID        uuid.UUID `json:"user_id"`
		Decision      string    `json:"decision"`
		Justification string    `json:"justification"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Decision == "" {
		s.renderError(w, http.StatusBadRequest, "INVALID_PAYLOAD", "Decision and justification are required")
		return
	}

	if err := s.store.AdminResolveConflict(r.Context(), admin.ID, body.UserID, conflictID, body.Decision, body.Justification); err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to resolve conflict: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{"status": "resolved", "conflict_id": conflictID})
}

func (s *Server) HandleAdminListAuditLogs(w http.ResponseWriter, r *http.Request) {
	actionType := strings.TrimSpace(r.URL.Query().Get("action_type"))
	var targetUserID *uuid.UUID
	if uStr := strings.TrimSpace(r.URL.Query().Get("target_user_id")); uStr != "" {
		if uID, err := uuid.Parse(uStr); err == nil {
			targetUserID = &uID
		}
	}

	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 {
		offset = 0
	}

	logs, total, err := s.store.ListAdminAuditLogs(r.Context(), actionType, targetUserID, limit, offset)
	if err != nil {
		s.renderError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Failed to list audit logs: "+err.Error())
		return
	}

	s.renderJSON(w, http.StatusOK, map[string]any{
		"audit_logs": logs,
		"total":      total,
		"limit":      limit,
		"offset":     offset,
	})
}

// -----------------------------------------------------------------------------
// Internal Helpers
// -----------------------------------------------------------------------------

func strPtr(s string) *string {
	return &s
}
