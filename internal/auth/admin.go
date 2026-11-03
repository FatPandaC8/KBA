package auth

import (
	"context"
	"errors"
	"net/http"

	"github.com/google/uuid"
	"gusby/internal/store"
)

var (
	ErrSelfActionForbidden = errors.New("admin cannot perform this action on themselves")
	ErrLastAdminProtection = errors.New("cannot demote or delete the last remaining admin")
)

// RequireAdmin protects administrative endpoints.
// Per Gusby security specification, non-admins and unauthorized callers receive HTTP 404
// so they cannot discover that administrative endpoints exist.
func RequireAdmin(svc *Service) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := GetSessionTokenFromRequest(r)
			if token == "" {
				renderError(w, http.StatusNotFound, "NOT_FOUND", "Endpoint not found")
				return
			}

			user, err := svc.AuthenticateSession(r.Context(), token)
			if err != nil || user == nil {
				renderError(w, http.StatusNotFound, "NOT_FOUND", "Endpoint not found")
				return
			}

			// Must be active
			if user.Status != "active" {
				renderError(w, http.StatusNotFound, "NOT_FOUND", "Endpoint not found")
				return
			}

			// Must be admin
			if !user.IsAdmin {
				renderError(w, http.StatusNotFound, "NOT_FOUND", "Endpoint not found")
				return
			}

			ctx := context.WithValue(r.Context(), UserContextKey, user)
			ctx = context.WithValue(ctx, UserIDContextKey, user.ID)

			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// ValidateUserSelfAction verifies that an admin is not attempting to suspend, unsuspend, or delete themselves.
func ValidateUserSelfAction(adminID, targetUserID uuid.UUID) error {
	if adminID == targetUserID {
		return ErrSelfActionForbidden
	}
	return nil
}

// ValidateAdminDemotion prevents deleting or demoting the last remaining active admin in the system.
func ValidateAdminDemotion(ctx context.Context, s *store.Store, targetUserID uuid.UUID) error {
	targetUser, err := s.GetUserByID(ctx, targetUserID)
	if err != nil {
		return err
	}
	if targetUser == nil {
		return errors.New("user not found")
	}

	if targetUser.IsAdmin {
		count, err := s.CountAdmins(ctx)
		if err != nil {
			return err
		}
		if count <= 1 {
			return ErrLastAdminProtection
		}
	}
	return nil
}

// EnsureOwnerAdmin ensures that the configured owner account is granted admin privileges.
func EnsureOwnerAdmin(ctx context.Context, s *store.Store, ownerEmail string) error {
	if ownerEmail == "" {
		return nil
	}
	user, err := s.GetUserByEmail(ctx, ownerEmail)
	if err != nil {
		return err
	}
	if user != nil && !user.IsAdmin {
		return s.SetUserAdmin(ctx, user.ID, true)
	}
	return nil
}
