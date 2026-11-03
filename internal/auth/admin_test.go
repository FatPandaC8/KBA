package auth_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/auth"
)

func TestRequireAdmin_AccessControl(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	svc := auth.NewService(s)
	ctx := context.Background()

	// 1. Setup test users: regular user, admin user, suspended admin user
	nonce := time.Now().UnixNano()
	regEmail := fmt.Sprintf("reg-%d@gusby.local", nonce)
	adminEmail := fmt.Sprintf("admin-%d@gusby.local", nonce)
	suspAdminEmail := fmt.Sprintf("susp-admin-%d@gusby.local", nonce)

	pw := "SecretPassword123!"
	pwHash, _ := auth.HashPassword(pw)

	regUser, err := s.CreateUser(ctx, regEmail, pwHash)
	if err != nil {
		t.Fatalf("failed to create reg user: %v", err)
	}
	defer s.DeleteUserAndAllData(ctx, regUser.ID)

	adminUser, err := s.CreateUser(ctx, adminEmail, pwHash)
	if err != nil {
		t.Fatalf("failed to create admin user: %v", err)
	}
	defer s.DeleteUserAndAllData(ctx, adminUser.ID)
	if err := s.SetUserAdmin(ctx, adminUser.ID, true); err != nil {
		t.Fatalf("failed to make admin user: %v", err)
	}

	suspAdminUser, err := s.CreateUser(ctx, suspAdminEmail, pwHash)
	if err != nil {
		t.Fatalf("failed to create susp admin user: %v", err)
	}
	defer s.DeleteUserAndAllData(ctx, suspAdminUser.ID)
	if err := s.SetUserAdmin(ctx, suspAdminUser.ID, true); err != nil {
		t.Fatalf("failed to make susp admin: %v", err)
	}
	if err := s.SetUserStatus(ctx, suspAdminUser.ID, "suspended"); err != nil {
		t.Fatalf("failed to suspend admin: %v", err)
	}

	// Login sessions
	_, regToken, err := svc.Login(ctx, regEmail, pw, "test-client")
	if err != nil {
		t.Fatalf("failed to login reg session: %v", err)
	}
	_, adminToken, err := svc.Login(ctx, adminEmail, pw, "test-client")
	if err != nil {
		t.Fatalf("failed to login admin session: %v", err)
	}
	_, suspToken, err := svc.Login(ctx, suspAdminEmail, pw, "test-client")
	if err != nil {
		t.Fatalf("failed to login susp session: %v", err)
	}

	// Test handler protected by RequireAdmin
	protectedHandler := auth.RequireAdmin(svc)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ADMIN_GRANTED"))
	}))

	tests := []struct {
		name           string
		token          string
		expectedStatus int
	}{
		{
			name:           "Anonymous / No Token -> 404 Not Found",
			token:          "",
			expectedStatus: http.StatusNotFound,
		},
		{
			name:           "Invalid Token -> 404 Not Found",
			token:          "invalid-random-token",
			expectedStatus: http.StatusNotFound,
		},
		{
			name:           "Regular Non-Admin User -> 404 Not Found",
			token:          regToken,
			expectedStatus: http.StatusNotFound,
		},
		{
			name:           "Suspended Admin User -> 404 Not Found",
			token:          suspToken,
			expectedStatus: http.StatusNotFound,
		},
		{
			name:           "Active Admin User -> 200 OK",
			token:          adminToken,
			expectedStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/admin/overview", nil)
			if tt.token != "" {
				req.AddCookie(&http.Cookie{
					Name:  "gusby_session",
					Value: tt.token,
				})
			}
			rec := httptest.NewRecorder()
			protectedHandler.ServeHTTP(rec, req)

			if rec.Code != tt.expectedStatus {
				t.Fatalf("expected HTTP %d, got %d (body: %s)", tt.expectedStatus, rec.Code, rec.Body.String())
			}
		})
	}
}

func TestAdminSafeguards(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	adminID := uuid.New()
	targetID := uuid.New()

	// 1. Self action
	if err := auth.ValidateUserSelfAction(adminID, adminID); err != auth.ErrSelfActionForbidden {
		t.Errorf("expected ErrSelfActionForbidden for self action, got %v", err)
	}
	if err := auth.ValidateUserSelfAction(adminID, targetID); err != nil {
		t.Errorf("expected nil for other user action, got %v", err)
	}

	// 2. EnsureOwnerAdmin
	nonce := time.Now().UnixNano()
	ownerEmail := fmt.Sprintf("owner-%d@gusby.local", nonce)
	pwHash, _ := auth.HashPassword("OwnerP@ss123!")
	user, err := s.CreateUser(ctx, ownerEmail, pwHash)
	if err != nil {
		t.Fatalf("failed to create owner user: %v", err)
	}
	defer s.DeleteUserAndAllData(ctx, user.ID)

	if user.IsAdmin {
		t.Errorf("expected newly created user to not be admin initially")
	}

	if err := auth.EnsureOwnerAdmin(ctx, s, ownerEmail); err != nil {
		t.Fatalf("EnsureOwnerAdmin failed: %v", err)
	}

	refreshed, err := s.GetUserByID(ctx, user.ID)
	if err != nil || refreshed == nil {
		t.Fatalf("failed to get refreshed user: %v", err)
	}
	if !refreshed.IsAdmin {
		t.Errorf("expected refreshed user to have IsAdmin=true")
	}

	// 3. Last Admin Demotion
	// Currently refreshed is the only newly created admin in this test scope (or along with existing seeds)
	// Let's test ValidateAdminDemotion when admin count is 1
	// If count > 1, ValidateAdminDemotion allows demotion; if count <= 1, it protects.
	adminCount, _ := s.CountAdmins(ctx)
	if adminCount == 1 {
		err := auth.ValidateAdminDemotion(ctx, s, user.ID)
		if err != auth.ErrLastAdminProtection {
			t.Errorf("expected ErrLastAdminProtection when adminCount is 1, got %v", err)
		}
	}
}
