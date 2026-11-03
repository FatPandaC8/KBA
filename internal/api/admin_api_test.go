package api_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/auth"
	"gusby/internal/store"
)

func createTestUserWithSession(t *testing.T, s *store.Store, isAdmin bool) (*store.User, string) {
	t.Helper()
	ctx := context.Background()
	nonce := time.Now().UnixNano()
	email := fmt.Sprintf("test-%d@gusby.local", nonce)
	pw := "SecureP@ssw0rd123!"
	pwHash, _ := auth.HashPassword(pw)

	user, err := s.CreateUser(ctx, email, pwHash)
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}

	if isAdmin {
		if err := s.SetUserAdmin(ctx, user.ID, true); err != nil {
			t.Fatalf("failed to set admin: %v", err)
		}
		user.IsAdmin = true
	}

	token, _ := auth.GenerateSessionToken()
	_, err = s.CreateSession(ctx, user.ID, token, 1*time.Hour)
	if err != nil {
		t.Fatalf("failed to create session: %v", err)
	}

	return user, token
}

func executeRequest(handler http.Handler, method, target, token string, body any) *httptest.ResponseRecorder {
	var bodyReader *bytes.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		bodyReader = bytes.NewReader(b)
	} else {
		bodyReader = bytes.NewReader([]byte{})
	}

	req := httptest.NewRequest(method, target, bodyReader)
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.AddCookie(&http.Cookie{
			Name:  "gusby_session",
			Value: token,
		})
	}
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	return rr
}

func TestAdminAPI_AccessControl(t *testing.T) {
	_, s, handler := setupTestServer(t)
	defer s.Close()
	ctx := context.Background()

	regUser, regToken := createTestUserWithSession(t, s, false)
	defer s.DeleteUserAndAllData(ctx, regUser.ID)

	adminUser, adminToken := createTestUserWithSession(t, s, true)
	defer s.DeleteUserAndAllData(ctx, adminUser.ID)

	// 1. Anonymous request to /api/admin/overview -> 404
	rr := executeRequest(handler, "GET", "/api/admin/overview", "", nil)
	if rr.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for anonymous request, got %d", rr.Code)
	}

	// 2. Regular user to /api/admin/overview -> 404
	rr = executeRequest(handler, "GET", "/api/admin/overview", regToken, nil)
	if rr.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for non-admin request, got %d", rr.Code)
	}

	// 3. Admin user to /api/admin/overview -> 200
	rr = executeRequest(handler, "GET", "/api/admin/overview", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 for admin request, got %d (body: %s)", rr.Code, rr.Body.String())
	}

	var overview map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &overview)
	if overview["metrics"] == nil || overview["ai_provider"] == nil || overview["ai_gate"] == nil {
		t.Errorf("missing expected fields in overview: %+v", overview)
	}
}

func TestAdminAPI_MonitoringAndAI(t *testing.T) {
	_, s, handler := setupTestServer(t)
	defer s.Close()
	ctx := context.Background()

	adminUser, adminToken := createTestUserWithSession(t, s, true)
	defer s.DeleteUserAndAllData(ctx, adminUser.ID)

	// 1. Pipeline Metrics
	rr := executeRequest(handler, "GET", "/api/admin/pipeline", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from pipeline endpoint, got %d", rr.Code)
	}

	// 2. AI Health
	rr = executeRequest(handler, "GET", "/api/admin/ai/health", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from AI health, got %d", rr.Code)
	}
	var healthResp map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &healthResp)
	if healthResp["status"] == nil || healthResp["provider"] == nil || healthResp["gate"] == nil {
		t.Errorf("AI health missing required fields: %+v", healthResp)
	}

	// 3. AI Metrics
	rr = executeRequest(handler, "GET", "/api/admin/ai/metrics?window=24h", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from AI metrics, got %d", rr.Code)
	}

	// 4. AI Probe
	rr = executeRequest(handler, "POST", "/api/admin/ai/probe", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from AI probe, got %d", rr.Code)
	}

	// 5. Gate Pause / Resume / Reset
	rr = executeRequest(handler, "POST", "/api/admin/ai/gate/pause", adminToken, map[string]string{
		"reason": "Test maintenance",
	})
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from gate pause, got %d", rr.Code)
	}

	rr = executeRequest(handler, "POST", "/api/admin/ai/gate/resume", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from gate resume, got %d", rr.Code)
	}

	rr = executeRequest(handler, "POST", "/api/admin/ai/gate/reset-breaker", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from gate reset-breaker, got %d", rr.Code)
	}

	// 6. Audit Log List
	rr = executeRequest(handler, "GET", "/api/admin/audit", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 from audit log list, got %d", rr.Code)
	}
	var auditResp map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &auditResp)
	if auditResp["audit_logs"] == nil {
		t.Errorf("expected audit_logs key in response")
	}
}

func TestAdminAPI_UserAndDocumentManagement(t *testing.T) {
	_, s, handler := setupTestServer(t)
	defer s.Close()
	ctx := context.Background()

	adminUser, adminToken := createTestUserWithSession(t, s, true)
	defer s.DeleteUserAndAllData(ctx, adminUser.ID)

	targetUser, _ := createTestUserWithSession(t, s, false)
	defer s.DeleteUserAndAllData(ctx, targetUser.ID)

	// 1. List Users
	rr := executeRequest(handler, "GET", "/api/admin/users", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 listing users, got %d", rr.Code)
	}

	// 2. Suspend & Unsuspend
	rr = executeRequest(handler, "POST", fmt.Sprintf("/api/admin/users/%s/suspend", targetUser.ID), adminToken, map[string]string{
		"reason": "Abuse policy violation",
	})
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 suspending user, got %d", rr.Code)
	}

	rr = executeRequest(handler, "POST", fmt.Sprintf("/api/admin/users/%s/unsuspend", targetUser.ID), adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 unsuspending user, got %d", rr.Code)
	}

	// 3. Reset Limits
	rr = executeRequest(handler, "POST", fmt.Sprintf("/api/admin/users/%s/reset-limits", targetUser.ID), adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 resetting limits, got %d", rr.Code)
	}

	doc, err := s.CreateDocument(ctx, &store.Document{
		UserID:      targetUser.ID,
		Title:       "Admin Test Doc",
		SourceType:  "text",
		ContentHash: "admin-hash-" + uuid.NewString()[:8],
		RawContent:  []byte("Hello world evidence document for admin testing"),
		SourceText:  "Hello world evidence document for admin testing",
		CharCount:   len("Hello world evidence document for admin testing"),
		Status:      "completed",
	})
	if err != nil {
		t.Fatalf("failed to create document: %v", err)
	}

	rr = executeRequest(handler, "GET", "/api/admin/documents", adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 listing documents, got %d", rr.Code)
	}

	rr = executeRequest(handler, "GET", fmt.Sprintf("/api/admin/documents/%s", doc.ID), adminToken, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 getting document details, got %d", rr.Code)
	}

	// 5. Delete Document with Typed Confirmation
	// Confirmation mismatch
	rr = executeRequest(handler, "DELETE", fmt.Sprintf("/api/admin/documents/%s", doc.ID), adminToken, map[string]string{
		"confirm_title": "Wrong Title",
	})
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for title mismatch, got %d", rr.Code)
	}

	// Confirmation match
	rr = executeRequest(handler, "DELETE", fmt.Sprintf("/api/admin/documents/%s", doc.ID), adminToken, map[string]string{
		"confirm_title": "Admin Test Doc",
	})
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 for matching title delete, got %d", rr.Code)
	}

	// 6. Delete User with Typed Confirmation
	rr = executeRequest(handler, "DELETE", fmt.Sprintf("/api/admin/users/%s", targetUser.ID), adminToken, map[string]string{
		"confirm_email": targetUser.Email,
		"reason":        "GDPR erasure request",
	})
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 deleting user with matching email, got %d", rr.Code)
	}
}
