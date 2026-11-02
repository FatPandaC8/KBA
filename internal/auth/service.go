package auth

import (
	"context"
	"errors"
	"net/mail"
	"sync"
	"time"

	"github.com/google/uuid"

	"gusby/internal/store"
)

var (
	ErrInvalidEmail       = errors.New("invalid email address")
	ErrEmailAlreadyExists = errors.New("email is already registered")
	ErrInvalidCredentials = errors.New("invalid email or password")
	ErrRateLimitExceeded  = errors.New("too many requests, please try again later")
)

type Service struct {
	store       *store.Store
	rateLimiter *AuthRateLimiter
}

func NewService(s *store.Store) *Service {
	return &Service{
		store:       s,
		rateLimiter: NewAuthRateLimiter(10, 1*time.Minute), // 10 attempts per minute per key
	}
}

func (s *Service) SignUp(ctx context.Context, email, password string, clientKey string) (*store.User, string, error) {
	if !s.rateLimiter.Allow(clientKey) {
		return nil, "", ErrRateLimitExceeded
	}

	addr, err := mail.ParseAddress(email)
	if err != nil || addr.Address == "" {
		return nil, "", ErrInvalidEmail
	}

	existing, err := s.store.GetUserByEmail(ctx, addr.Address)
	if err != nil {
		return nil, "", err
	}
	if existing != nil {
		return nil, "", ErrEmailAlreadyExists
	}

	passwordHash, err := HashPassword(password)
	if err != nil {
		return nil, "", err
	}

	user, err := s.store.CreateUser(ctx, addr.Address, passwordHash)
	if err != nil {
		return nil, "", err
	}

	token, err := GenerateSessionToken()
	if err != nil {
		return nil, "", err
	}

	_, err = s.store.CreateSession(ctx, user.ID, token, SessionDuration)
	if err != nil {
		return nil, "", err
	}

	return user, token, nil
}

func (s *Service) Login(ctx context.Context, email, password string, clientKey string) (*store.User, string, error) {
	if !s.rateLimiter.Allow(clientKey) {
		return nil, "", ErrRateLimitExceeded
	}

	user, err := s.store.GetUserByEmail(ctx, email)
	if err != nil || user == nil {
		// Generic error to prevent email enumeration
		return nil, "", ErrInvalidCredentials
	}

	valid, err := VerifyPassword(password, user.PasswordHash)
	if err != nil || !valid {
		return nil, "", ErrInvalidCredentials
	}

	token, err := GenerateSessionToken()
	if err != nil {
		return nil, "", err
	}

	_, err = s.store.CreateSession(ctx, user.ID, token, SessionDuration)
	if err != nil {
		return nil, "", err
	}

	return user, token, nil
}

func (s *Service) Logout(ctx context.Context, token string) error {
	if token == "" {
		return nil
	}
	return s.store.DeleteSession(ctx, token)
}

func (s *Service) AuthenticateSession(ctx context.Context, token string) (*store.User, error) {
	if token == "" {
		return nil, errors.New("no session token provided")
	}

	sess, err := s.store.GetSessionByToken(ctx, token)
	if err != nil || sess == nil {
		return nil, errors.New("invalid or expired session")
	}

	user, err := s.store.GetUserByID(ctx, sess.UserID)
	if err != nil || user == nil {
		return nil, errors.New("user not found")
	}

	return user, nil
}

func (s *Service) ChangePassword(ctx context.Context, userID uuid.UUID, oldPassword, newPassword string) error {
	user, err := s.store.GetUserByID(ctx, userID)
	if err != nil || user == nil {
		return errors.New("user not found")
	}

	valid, err := VerifyPassword(oldPassword, user.PasswordHash)
	if err != nil || !valid {
		return ErrInvalidCredentials
	}

	if len(newPassword) < 8 {
		return ErrPasswordTooShort
	}

	newHash, err := HashPassword(newPassword)
	if err != nil {
		return err
	}

	return s.store.UpdateUserPassword(ctx, userID, newHash)
}

// -----------------------------------------------------------------------------
// Rate Limiter
// -----------------------------------------------------------------------------

type AuthRateLimiter struct {
	mu       sync.Mutex
	limit    int
	window   time.Duration
	attempts map[string][]time.Time
}

func NewAuthRateLimiter(limit int, window time.Duration) *AuthRateLimiter {
	rl := &AuthRateLimiter{
		limit:    limit,
		window:   window,
		attempts: make(map[string][]time.Time),
	}
	// Background cleanup of expired entries
	go func() {
		ticker := time.NewTicker(2 * time.Minute)
		for range ticker.C {
			rl.cleanup()
		}
	}()
	return rl
}

func (rl *AuthRateLimiter) Allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-rl.window)

	var valid []time.Time
	for _, t := range rl.attempts[key] {
		if t.After(cutoff) {
			valid = append(valid, t)
		}
	}

	if len(valid) >= rl.limit {
		rl.attempts[key] = valid
		return false
	}

	rl.attempts[key] = append(valid, now)
	return true
}

func (rl *AuthRateLimiter) cleanup() {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-rl.window)
	for k, timestamps := range rl.attempts {
		var valid []time.Time
		for _, t := range timestamps {
			if t.After(cutoff) {
				valid = append(valid, t)
			}
		}
		if len(valid) == 0 {
			delete(rl.attempts, k)
		} else {
			rl.attempts[k] = valid
		}
	}
}

// Helper context keys
type contextKey string

const (
	UserContextKey   contextKey = "gusby_user"
	UserIDContextKey contextKey = "gusby_user_id"
)

func UserFromContext(ctx context.Context) *store.User {
	if u, ok := ctx.Value(UserContextKey).(*store.User); ok {
		return u
	}
	return nil
}

func UserIDFromContext(ctx context.Context) (uuid.UUID, bool) {
	if id, ok := ctx.Value(UserIDContextKey).(uuid.UUID); ok {
		return id, true
	}
	return uuid.Nil, false
}
