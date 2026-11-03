package auth

import (
	"context"
	"log"
	"os"
	"strings"

	"gusby/internal/store"
)

// SeedDevUsers checks environment variables and automatically seeds or synchronizes
// development accounts into gusby.users when E2E_SEED_ENABLED is true or 1.
func SeedDevUsers(ctx context.Context, s *store.Store) error {
	enabled := strings.ToLower(strings.TrimSpace(os.Getenv("E2E_SEED_ENABLED")))
	if enabled != "true" && enabled != "1" {
		return nil
	}

	type seedAccount struct {
		name     string
		email    string
		password string
	}

	accounts := []seedAccount{
		{
			name:     "admin",
			email:    strings.TrimSpace(os.Getenv("E2E_ADMIN_EMAIL")),
			password: os.Getenv("E2E_ADMIN_PASSWORD"),
		},
		{
			name:     "user1",
			email:    strings.TrimSpace(os.Getenv("E2E_USER_1_EMAIL")),
			password: os.Getenv("E2E_USER_1_PASSWORD"),
		},
		{
			name:     "user2",
			email:    strings.TrimSpace(os.Getenv("E2E_USER_2_EMAIL")),
			password: os.Getenv("E2E_USER_2_PASSWORD"),
		},
		{
			name:     "user3",
			email:    strings.TrimSpace(os.Getenv("E2E_USER_3_EMAIL")),
			password: os.Getenv("E2E_USER_3_PASSWORD"),
		},
	}

	seededCount := 0
	for _, acc := range accounts {
		if acc.email == "" || acc.password == "" {
			continue
		}

		existing, err := s.GetUserByEmail(ctx, acc.email)
		if err != nil {
			log.Printf("[Gusby Auth] Error checking existing seed user %s: %v", acc.email, err)
			continue
		}

		if existing == nil {
			hash, err := HashPassword(acc.password)
			if err != nil {
				log.Printf("[Gusby Auth] Error hashing password for seed user %s: %v", acc.email, err)
				continue
			}
			user, err := s.CreateUser(ctx, acc.email, hash)
			if err != nil {
				log.Printf("[Gusby Auth] Error creating seed user %s: %v", acc.email, err)
				continue
			}
			log.Printf("[Gusby Auth] Seeded user %s (%s, id: %s)", acc.name, user.Email, user.ID)
			seededCount++
		} else {
			// Synchronize password if changed in .env
			match, err := VerifyPassword(acc.password, existing.PasswordHash)
			if err != nil || !match {
				newHash, err := HashPassword(acc.password)
				if err != nil {
					log.Printf("[Gusby Auth] Error hashing updated password for %s: %v", acc.email, err)
					continue
				}
				if err := s.UpdateUserPassword(ctx, existing.ID, newHash); err != nil {
					log.Printf("[Gusby Auth] Error updating seed user password for %s: %v", acc.email, err)
					continue
				}
				log.Printf("[Gusby Auth] Synchronized seed password for %s (%s)", acc.name, existing.Email)
				seededCount++
			}
		}
	}

	if seededCount > 0 {
		log.Printf("[Gusby Auth] Seed initialization complete (%d accounts processed)", seededCount)
	}

	return nil
}
