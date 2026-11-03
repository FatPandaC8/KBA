package admin_test

import (
	"bytes"
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/api"
	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/store"
)

func createTestActor(t *testing.T, s *store.Store, role string) (*store.User, string) {
	t.Helper()
	ctx := context.Background()
	nonce := time.Now().UnixNano()
	email := fmt.Sprintf("%s-%d@gusby.local", role, nonce)
	pw := "SecureP@ssw0rd123!"
	pwHash, _ := auth.HashPassword(pw)

	user, err := s.CreateUser(ctx, email, pwHash)
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}

	if role == "admin" || role == "suspended_admin" {
		if err := s.SetUserAdmin(ctx, user.ID, true); err != nil {
			t.Fatalf("failed to grant admin: %v", err)
		}
		user.IsAdmin = true
	}

	if role == "suspended_admin" {
		if err := s.SetUserStatus(ctx, user.ID, "suspended"); err != nil {
			t.Fatalf("failed to suspend admin: %v", err)
		}
		user.Status = "suspended"
	}

	token, _ := auth.GenerateSessionToken()
	_, err = s.CreateSession(ctx, user.ID, token, 1*time.Hour)
	if err != nil {
		t.Fatalf("failed to create session: %v", err)
	}

	return user, token
}

func TestAuthorizationMatrix_AllAdminEndpoints(t *testing.T) {
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping auth matrix test", err)
	}
	defer s.Close()

	server := api.NewServer(cfg, s)
	handler := server.Routes()

	// Actors
	regUser, regToken := createTestActor(t, s, "regular")
	defer s.DeleteUserAndAllData(context.Background(), regUser.ID)

	suspUser, suspToken := createTestActor(t, s, "suspended_admin")
	defer s.DeleteUserAndAllData(context.Background(), suspUser.ID)

	adminUser, adminToken := createTestActor(t, s, "admin")
	defer s.DeleteUserAndAllData(context.Background(), adminUser.ID)

	testDoc, err := s.CreateDocument(context.Background(), &store.Document{
		UserID:      adminUser.ID,
		Title:       "Auth Matrix Doc",
		SourceType:  "text",
		ContentHash: "auth-matrix-hash-" + uuid.NewString()[:8],
		RawContent:  []byte("Auth matrix document content"),
		SourceText:  "Auth matrix document content",
		CharCount:   len("Auth matrix document content"),
		Status:      "completed",
	})
	if err != nil {
		t.Fatalf("failed to create test doc: %v", err)
	}

	dummyID := uuid.New().String()
	realUserID := adminUser.ID.String()
	realDocID := testDoc.ID.String()

	endpoints := []struct {
		method string
		path   string
	}{
		// Overview & Pipeline
		{"GET", "/api/admin/overview"},
		{"GET", "/api/admin/pipeline"},
		{"POST", fmt.Sprintf("/api/admin/pipeline/jobs/%s/retry", dummyID)},

		// AI Observability & Controls
		{"GET", "/api/admin/ai/health"},
		{"GET", "/api/admin/ai/metrics"},
		{"GET", "/api/admin/ai/eval-runs"},
		{"POST", "/api/admin/ai/probe"},
		{"GET", "/api/admin/ai/gate"},
		{"POST", "/api/admin/ai/gate/pause"},
		{"POST", "/api/admin/ai/gate/resume"},
		{"POST", "/api/admin/ai/gate/reset-breaker"},

		// User Management
		{"GET", "/api/admin/users"},
		{"GET", fmt.Sprintf("/api/admin/users/%s", realUserID)},
		{"POST", fmt.Sprintf("/api/admin/users/%s/suspend", dummyID)},
		{"POST", fmt.Sprintf("/api/admin/users/%s/unsuspend", dummyID)},
		{"POST", fmt.Sprintf("/api/admin/users/%s/reset-limits", dummyID)},
		{"DELETE", fmt.Sprintf("/api/admin/users/%s", dummyID)},

		// Document Management
		{"GET", "/api/admin/documents"},
		{"GET", fmt.Sprintf("/api/admin/documents/%s", realDocID)},
		{"POST", fmt.Sprintf("/api/admin/documents/%s/reprocess", realDocID)},
		{"DELETE", fmt.Sprintf("/api/admin/documents/%s", realDocID)},

		// Graph Data Administration
		{"GET", "/api/admin/graph/concepts"},
		{"POST", "/api/admin/graph/concepts/merge"},
		{"PUT", fmt.Sprintf("/api/admin/graph/concepts/%s", dummyID)},
		{"DELETE", fmt.Sprintf("/api/admin/graph/concepts/%s", dummyID)},
		{"GET", "/api/admin/graph/propositions"},
		{"POST", "/api/admin/graph/propositions"},
		{"POST", fmt.Sprintf("/api/admin/graph/propositions/%s/retract", dummyID)},
		{"POST", fmt.Sprintf("/api/admin/graph/propositions/%s/restore", dummyID)},
		{"GET", "/api/admin/graph/topics"},
		{"PUT", fmt.Sprintf("/api/admin/graph/topics/%s", dummyID)},
		{"GET", "/api/admin/graph/conflicts"},
		{"POST", fmt.Sprintf("/api/admin/graph/conflicts/%s/resolve", dummyID)},

		// Audit Log
		{"GET", "/api/admin/audit"},
	}

	actors := []struct {
		name        string
		token       string
		expectMatch func(code int) bool
	}{
		{
			name:        "Anonymous Caller",
			token:       "",
			expectMatch: func(c int) bool { return c == http.StatusNotFound },
		},
		{
			name:        "Regular Authenticated User",
			token:       regToken,
			expectMatch: func(c int) bool { return c == http.StatusNotFound },
		},
		{
			name:        "Suspended Admin",
			token:       suspToken,
			expectMatch: func(c int) bool { return c == http.StatusNotFound },
		},
		{
			name:        "Active Admin User",
			token:       adminToken,
			expectMatch: func(c int) bool { return c != http.StatusNotFound }, // Allowed through, never 404!
		},
	}

	for _, actor := range actors {
		t.Run(actor.name, func(t *testing.T) {
			for _, ep := range endpoints {
				req := httptest.NewRequest(ep.method, ep.path, bytes.NewReader([]byte("{}")))
				req.Header.Set("Content-Type", "application/json")
				if actor.token != "" {
					req.AddCookie(&http.Cookie{
						Name:  "gusby_session",
						Value: actor.token,
					})
				}
				rec := httptest.NewRecorder()
				handler.ServeHTTP(rec, req)

				if !actor.expectMatch(rec.Code) {
					t.Errorf("[%s] %s %s returned HTTP %d, failed security matrix assertion",
						actor.name, ep.method, ep.path, rec.Code)
				}
			}
		})
	}
}
