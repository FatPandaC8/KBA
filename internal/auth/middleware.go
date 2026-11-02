package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
)

func RequireAuth(svc *Service) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := GetSessionTokenFromRequest(r)
			if token == "" {
				renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Authentication required")
				return
			}

			user, err := svc.AuthenticateSession(r.Context(), token)
			if err != nil || user == nil {
				renderError(w, http.StatusUnauthorized, "UNAUTHORIZED", "Invalid or expired session")
				return
			}

			ctx := context.WithValue(r.Context(), UserContextKey, user)
			ctx = context.WithValue(ctx, UserIDContextKey, user.ID)

			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func CSRFProtection() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method == http.MethodPost || r.Method == http.MethodPut || r.Method == http.MethodDelete || r.Method == http.MethodPatch {
				origin := r.Header.Get("Origin")
				if origin != "" {
					host := r.Host
					origin = strings.TrimPrefix(origin, "http://")
					origin = strings.TrimPrefix(origin, "https://")
					if !strings.HasPrefix(origin, host) && !strings.Contains(origin, "127.0.0.1") && !strings.Contains(origin, "localhost") {
						renderError(w, http.StatusForbidden, "CSRF_FORBIDDEN", "Cross-site request forgery protection triggered")
						return
					}
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}

func renderError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"error": map[string]string{
			"code":    code,
			"message": message,
		},
	})
}
