package auth_test

import (
	"context"
	"os"
	"testing"

	"gusby/internal/auth"
)

func TestSeedDevUsers_Disabled(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()

	os.Setenv("E2E_SEED_ENABLED", "false")
	err := auth.SeedDevUsers(context.Background(), s)
	if err != nil {
		t.Fatalf("expected nil error when seeding is disabled, got %v", err)
	}
}

func TestSeedDevUsers_Enabled(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()

	testEmail := "seed-test-unit@example.test"
	testPassword := "SeedPassword123!"

	os.Setenv("E2E_SEED_ENABLED", "true")
	os.Setenv("E2E_USER_3_EMAIL", testEmail)
	os.Setenv("E2E_USER_3_PASSWORD", testPassword)
	defer func() {
		os.Unsetenv("E2E_SEED_ENABLED")
		os.Unsetenv("E2E_USER_3_EMAIL")
		os.Unsetenv("E2E_USER_3_PASSWORD")
		_, _ = s.Pool().Exec(context.Background(), "DELETE FROM gusby.users WHERE email = $1", testEmail)
	}()

	ctx := context.Background()
	err := auth.SeedDevUsers(ctx, s)
	if err != nil {
		t.Fatalf("SeedDevUsers failed: %v", err)
	}

	user, err := s.GetUserByEmail(ctx, testEmail)
	if err != nil {
		t.Fatalf("GetUserByEmail failed: %v", err)
	}
	if user == nil {
		t.Fatalf("expected user %s to be created by SeedDevUsers, got nil", testEmail)
	}

	// Verify password matches
	match, err := auth.VerifyPassword(testPassword, user.PasswordHash)
	if err != nil || !match {
		t.Fatalf("expected verified password for seed user, got match=%v err=%v", match, err)
	}

	// Test synchronization on password change
	updatedPassword := "NewSeedPassword456!"
	os.Setenv("E2E_USER_3_PASSWORD", updatedPassword)

	err = auth.SeedDevUsers(ctx, s)
	if err != nil {
		t.Fatalf("SeedDevUsers re-run failed: %v", err)
	}

	updatedUser, err := s.GetUserByEmail(ctx, testEmail)
	if err != nil {
		t.Fatalf("GetUserByEmail failed: %v", err)
	}
	matchUpdated, err := auth.VerifyPassword(updatedPassword, updatedUser.PasswordHash)
	if err != nil || !matchUpdated {
		t.Fatalf("expected updated password to match, got match=%v err=%v", matchUpdated, err)
	}
}
