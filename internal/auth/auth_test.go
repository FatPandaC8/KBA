package auth_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping auth test", err)
	}
	return s
}

func TestPassword_Argon2id(t *testing.T) {
	pw := "SecureP@ssw0rd123"

	// Short password rejected
	_, err := auth.HashPassword("short")
	if err != auth.ErrPasswordTooShort {
		t.Errorf("expected ErrPasswordTooShort, got %v", err)
	}

	hash, err := auth.HashPassword(pw)
	if err != nil {
		t.Fatalf("failed to hash password: %v", err)
	}

	valid, err := auth.VerifyPassword(pw, hash)
	if err != nil || !valid {
		t.Errorf("expected valid password verification, got valid=%v, err=%v", valid, err)
	}

	wrong, err := auth.VerifyPassword("WrongPassword!", hash)
	if err != nil || wrong {
		t.Errorf("expected false for wrong password, got valid=%v, err=%v", wrong, err)
	}
}

func TestAuthService_SignUp_Login_Logout(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	svc := auth.NewService(s)
	ctx := context.Background()

	email := "auth-" + uuid.NewString()[:8] + "@example.com"
	password := "SecretP@ss999"

	// 1. Sign Up
	user, token, err := svc.SignUp(ctx, email, password, "ip-1")
	if err != nil {
		t.Fatalf("sign up failed: %v", err)
	}
	if user.Email != email {
		t.Errorf("expected email %s, got %s", email, user.Email)
	}
	if token == "" {
		t.Errorf("expected non-empty token")
	}

	// 2. Duplicate Sign Up
	_, _, err = svc.SignUp(ctx, email, password, "ip-1")
	if err != auth.ErrEmailAlreadyExists {
		t.Errorf("expected ErrEmailAlreadyExists, got %v", err)
	}

	// 3. Login with correct password
	loginUser, loginToken, err := svc.Login(ctx, email, password, "ip-1")
	if err != nil {
		t.Fatalf("login failed: %v", err)
	}
	if loginUser.ID != user.ID {
		t.Errorf("expected user ID %v, got %v", user.ID, loginUser.ID)
	}

	// 4. Login with wrong password returns generic error
	_, _, err = svc.Login(ctx, email, "WrongPassword", "ip-1")
	if err != auth.ErrInvalidCredentials {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}

	// 5. Login with non-existent user returns generic error
	_, _, err = svc.Login(ctx, "nonexistent@example.com", "SomePassword", "ip-1")
	if err != auth.ErrInvalidCredentials {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}

	// 6. Authenticate valid token
	authUser, err := svc.AuthenticateSession(ctx, loginToken)
	if err != nil || authUser == nil {
		t.Fatalf("session authentication failed: %v", err)
	}
	if authUser.ID != user.ID {
		t.Errorf("expected user %v, got %v", user.ID, authUser.ID)
	}

	// 7. Logout revokes token
	if err := svc.Logout(ctx, loginToken); err != nil {
		t.Fatalf("logout failed: %v", err)
	}

	_, err = svc.AuthenticateSession(ctx, loginToken)
	if err == nil {
		t.Errorf("expected error for revoked token, but got nil")
	}
}

func TestAuthMiddleware_Protection(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	svc := auth.NewService(s)
	ctx := context.Background()

	email := "middleware-" + uuid.NewString()[:8] + "@example.com"
	user, token, err := svc.SignUp(ctx, email, "SuperSecure123", "ip-2")
	if err != nil {
		t.Fatalf("failed to sign up: %v", err)
	}

	handlerCalled := false
	protectedHandler := auth.RequireAuth(svc)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handlerCalled = true
		u := auth.UserFromContext(r.Context())
		if u == nil || u.ID != user.ID {
			t.Errorf("expected user in context %v, got %v", user.ID, u)
		}
		w.WriteHeader(http.StatusOK)
	}))

	// Case A: Unauthenticated request should return 401
	reqUnauth := httptest.NewRequest("GET", "/api/protected", nil)
	rrUnauth := httptest.NewRecorder()
	protectedHandler.ServeHTTP(rrUnauth, reqUnauth)

	if rrUnauth.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 Unauthorized, got %d", rrUnauth.Code)
	}
	if handlerCalled {
		t.Errorf("handler should not have been called without auth")
	}

	// Case B: Authenticated via Cookie
	handlerCalled = false
	reqAuth := httptest.NewRequest("GET", "/api/protected", nil)
	reqAuth.AddCookie(&http.Cookie{
		Name:  auth.SessionCookieName,
		Value: token,
	})
	rrAuth := httptest.NewRecorder()
	protectedHandler.ServeHTTP(rrAuth, reqAuth)

	if rrAuth.Code != http.StatusOK {
		t.Errorf("expected 200 OK, got %d", rrAuth.Code)
	}
	if !handlerCalled {
		t.Errorf("expected protected handler to be executed")
	}
}

func TestMultiTenant_DataIsolation(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	svc := auth.NewService(s)
	ctx := context.Background()

	// Create User A and User B
	userA, _, err := svc.SignUp(ctx, "userA-"+uuid.NewString()[:8]+"@example.com", "PasswordUserA1", "ip-a")
	if err != nil {
		t.Fatalf("failed to create User A: %v", err)
	}

	userB, _, err := svc.SignUp(ctx, "userB-"+uuid.NewString()[:8]+"@example.com", "PasswordUserB1", "ip-b")
	if err != nil {
		t.Fatalf("failed to create User B: %v", err)
	}

	// User A creates a document, concept, proposition, and topic
	docA := &store.Document{
		UserID:      userA.ID,
		Title:       "User A Private Secrets",
		SourceType:  "text",
		ContentHash: "hash-priv-a-" + uuid.NewString(),
		SourceText:  "Top secret formula belonging to User A only.",
		CharCount:   44,
		Status:      "completed",
	}
	docA, err = s.CreateDocument(ctx, docA)
	if err != nil {
		t.Fatalf("failed to create docA: %v", err)
	}

	conceptA, err := s.UpsertConcept(ctx, userA.ID, "Quantum Secret A", "Private Concept of User A")
	if err != nil {
		t.Fatalf("failed to create conceptA: %v", err)
	}

	conceptA2, err := s.UpsertConcept(ctx, userA.ID, "Vault A", "Private Vault")
	if err != nil {
		t.Fatalf("failed to create conceptA2: %v", err)
	}

	propA := &store.Proposition{
		UserID:                userA.ID,
		SubjectConceptID:      conceptA.ID,
		Predicate:             "Stored In",
		ObjectConceptID:       conceptA2.ID,
		IsCanonical:           true,
		ConfidenceExtraction:  0.9,
		ConfidenceEvidence:    1.0,
		ConfidenceResolution:  0.9,
		ConfidenceProposition: 0.9,
	}
	propA, err = s.CreateProposition(ctx, propA)
	if err != nil {
		t.Fatalf("failed to create propA: %v", err)
	}

	topicA, err := s.UpsertTopic(ctx, userA.ID, "Project Alpha", "Top secret project", 1, 0.0, 0.0)
	if err != nil {
		t.Fatalf("failed to create topicA: %v", err)
	}

	// TEST TENANT ISOLATION: User B queries for User A's data
	// 1. User B tries to fetch User A's document
	fetchedDoc, err := s.GetDocumentByID(ctx, userB.ID, docA.ID)
	if err != nil {
		t.Fatalf("query failed: %v", err)
	}
	if fetchedDoc != nil {
		t.Errorf("SECURITY LEAK: User B was able to fetch User A's document: %v", fetchedDoc)
	}

	// 2. User B lists documents: must not include User A's documents
	docsB, totalB, err := s.ListDocuments(ctx, userB.ID, "", 50, 0)
	if err != nil {
		t.Fatalf("list docs failed: %v", err)
	}
	if totalB != 0 || len(docsB) != 0 {
		t.Errorf("SECURITY LEAK: User B listed documents belonging to another user: %d docs", totalB)
	}

	// 3. User B tries to fetch User A's concept
	fetchedConcept, err := s.GetConceptByID(ctx, userB.ID, conceptA.ID)
	if err != nil {
		t.Fatalf("query failed: %v", err)
	}
	if fetchedConcept != nil {
		t.Errorf("SECURITY LEAK: User B fetched User A's concept: %v", fetchedConcept)
	}

	// 4. User B performs trigram search for "Quantum Secret A"
	trigramResults, _, err := s.FindConceptsByTrigram(ctx, userB.ID, "Quantum Secret A", 0.5, 10)
	if err != nil {
		t.Fatalf("trigram search failed: %v", err)
	}
	if len(trigramResults) != 0 {
		t.Errorf("SECURITY LEAK: User B discovered User A's concept via trigram search: %d concepts", len(trigramResults))
	}

	// 5. User B queries propositions
	propsB, err := s.FindPropositionBySubjectAndPredicate(ctx, userB.ID, conceptA.ID, "Stored In")
	if err != nil {
		t.Fatalf("query props failed: %v", err)
	}
	if len(propsB) != 0 {
		t.Errorf("SECURITY LEAK: User B fetched User A's propositions: %d", len(propsB))
	}

	// 6. User B lists topics
	topicsB, err := s.ListTopics(ctx, userB.ID)
	if err != nil {
		t.Fatalf("query topics failed: %v", err)
	}
	if len(topicsB) != 0 {
		t.Errorf("SECURITY LEAK: User B listed User A's topics: %d", len(topicsB))
	}
	_ = topicA
	_ = propA
}
