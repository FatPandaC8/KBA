package api_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/api"
	"gusby/internal/config"
	"gusby/internal/store"
)

func setupTestServer(t *testing.T) (*api.Server, *store.Store, http.Handler) {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping API test", err)
	}

	server := api.NewServer(cfg, s)
	return server, s, server.Routes()
}

func TestAPI_Health(t *testing.T) {
	_, s, handler := setupTestServer(t)
	defer s.Close()

	// 1. Liveness endpoint /api/health
	req := httptest.NewRequest("GET", "/api/health", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 OK, got %d", rr.Code)
	}

	var resp map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to parse JSON: %v", err)
	}
	if resp["service"] != "gusby" || resp["status"] != "ok" {
		t.Errorf("unexpected health response: %v", resp)
	}

	// 2. Liveness alias /api/health/live
	reqLive := httptest.NewRequest("GET", "/api/health/live", nil)
	rrLive := httptest.NewRecorder()
	handler.ServeHTTP(rrLive, reqLive)
	if rrLive.Code != http.StatusOK {
		t.Fatalf("expected 200 OK for /api/health/live, got %d", rrLive.Code)
	}

	// 3. Readiness endpoint /api/health/ready
	reqReady := httptest.NewRequest("GET", "/api/health/ready", nil)
	rrReady := httptest.NewRecorder()
	handler.ServeHTTP(rrReady, reqReady)
	if rrReady.Code != http.StatusOK {
		t.Fatalf("expected 200 OK for /api/health/ready, got %d: %s", rrReady.Code, rrReady.Body.String())
	}
	var readyResp map[string]any
	if err := json.Unmarshal(rrReady.Body.Bytes(), &readyResp); err != nil {
		t.Fatalf("failed to parse ready JSON: %v", err)
	}
	if readyResp["status"] != "ready" || readyResp["database"] != "connected" {
		t.Errorf("unexpected readiness response: %v", readyResp)
	}
}

func TestAPI_EndToEndFlow(t *testing.T) {
	_, s, handler := setupTestServer(t)
	defer s.Close()

	email := "e2e-" + uuid.NewString()[:8] + "@example.com"
	password := "Secret123456"

	// 1. Sign Up
	signupBody, _ := json.Marshal(map[string]string{
		"email":    email,
		"password": password,
	})
	reqSignup := httptest.NewRequest("POST", "/api/auth/signup", bytes.NewReader(signupBody))
	reqSignup.Header.Set("Content-Type", "application/json")
	rrSignup := httptest.NewRecorder()
	handler.ServeHTTP(rrSignup, reqSignup)

	if rrSignup.Code != http.StatusCreated {
		t.Fatalf("signup failed with status %d: %s", rrSignup.Code, rrSignup.Body.String())
	}

	cookies := rrSignup.Result().Cookies()
	var sessionCookie *http.Cookie
	for _, c := range cookies {
		if c.Name == "gusby_session" {
			sessionCookie = c
			break
		}
	}
	if sessionCookie == nil {
		t.Fatalf("expected gusby_session cookie in signup response")
	}

	// 2. Auth Me
	reqMe := httptest.NewRequest("GET", "/api/auth/me", nil)
	reqMe.AddCookie(sessionCookie)
	rrMe := httptest.NewRecorder()
	handler.ServeHTTP(rrMe, reqMe)

	if rrMe.Code != http.StatusOK {
		t.Fatalf("auth/me failed with status %d: %s", rrMe.Code, rrMe.Body.String())
	}

	// 3. Ingest Plain Text
	textBody, _ := json.Marshal(map[string]string{
		"title":   "Quantum Computing Basics",
		"content": "Quantum computers use qubits to perform calculations exponentially faster than classical computers.",
	})
	reqIngest := httptest.NewRequest("POST", "/api/documents/text", bytes.NewReader(textBody))
	reqIngest.Header.Set("Content-Type", "application/json")
	reqIngest.AddCookie(sessionCookie)
	rrIngest := httptest.NewRecorder()
	handler.ServeHTTP(rrIngest, reqIngest)

	if rrIngest.Code != http.StatusAccepted {
		t.Fatalf("ingest text failed with status %d: %s", rrIngest.Code, rrIngest.Body.String())
	}

	var ingestResp map[string]any
	_ = json.Unmarshal(rrIngest.Body.Bytes(), &ingestResp)
	if ingestResp["status"] != "processing" {
		t.Errorf("expected status processing, got %v", ingestResp["status"])
	}

	// 4. Duplicate Ingest returns 200 with duplicate flag
	reqDup := httptest.NewRequest("POST", "/api/documents/text", bytes.NewReader(textBody))
	reqDup.Header.Set("Content-Type", "application/json")
	reqDup.AddCookie(sessionCookie)
	rrDup := httptest.NewRecorder()
	handler.ServeHTTP(rrDup, reqDup)

	if rrDup.Code != http.StatusOK {
		t.Errorf("expected 200 for duplicate, got %d", rrDup.Code)
	}

	// 5. Ingest URL with SSRF protection (loopback blocked)
	urlBody, _ := json.Marshal(map[string]string{
		"url": "http://127.0.0.1:8080/internal-admin",
	})
	reqSSRF := httptest.NewRequest("POST", "/api/documents/url", bytes.NewReader(urlBody))
	reqSSRF.Header.Set("Content-Type", "application/json")
	reqSSRF.AddCookie(sessionCookie)
	rrSSRF := httptest.NewRecorder()
	handler.ServeHTTP(rrSSRF, reqSSRF)

	if rrSSRF.Code != http.StatusBadRequest {
		t.Errorf("expected 400 Bad Request for SSRF attack, got %d", rrSSRF.Code)
	}

	// 6. List Documents
	reqList := httptest.NewRequest("GET", "/api/documents", nil)
	reqList.AddCookie(sessionCookie)
	rrList := httptest.NewRecorder()
	handler.ServeHTTP(rrList, reqList)

	if rrList.Code != http.StatusOK {
		t.Fatalf("list documents failed: %d", rrList.Code)
	}

	// 7. Graph Projection (LOD)
	reqGraph := httptest.NewRequest("GET", "/api/graph?zoom=deep", nil)
	reqGraph.AddCookie(sessionCookie)
	rrGraph := httptest.NewRecorder()
	handler.ServeHTTP(rrGraph, reqGraph)

	if rrGraph.Code != http.StatusOK {
		t.Fatalf("get graph failed: %d", rrGraph.Code)
	}

	// 8. Search Graph
	reqSearch := httptest.NewRequest("GET", "/api/graph/search?q=quantum", nil)
	reqSearch.AddCookie(sessionCookie)
	rrSearch := httptest.NewRecorder()
	handler.ServeHTTP(rrSearch, reqSearch)

	if rrSearch.Code != http.StatusOK {
		t.Fatalf("search graph failed: %d", rrSearch.Code)
	}

	// 9. Review Endpoints
	reqProposals := httptest.NewRequest("GET", "/api/review/proposals", nil)
	reqProposals.AddCookie(sessionCookie)
	rrProposals := httptest.NewRecorder()
	handler.ServeHTTP(rrProposals, reqProposals)

	if rrProposals.Code != http.StatusOK {
		t.Fatalf("list proposals failed: %d", rrProposals.Code)
	}

	reqConflicts := httptest.NewRequest("GET", "/api/review/conflicts", nil)
	reqConflicts.AddCookie(sessionCookie)
	rrConflicts := httptest.NewRecorder()
	handler.ServeHTTP(rrConflicts, reqConflicts)

	if rrConflicts.Code != http.StatusOK {
		t.Fatalf("list conflicts failed: %d", rrConflicts.Code)
	}
}
