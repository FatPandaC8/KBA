package graph

import (
	"context"
	"math"
	"math/rand"

	"github.com/google/uuid"

	"gusby/internal/store"
)

// AutoClusterTopics organizes concepts into spatial topic islands
func AutoClusterTopics(ctx context.Context, s *store.Store, userID uuid.UUID, docTitle string, conceptIDs []uuid.UUID) error {
	if len(conceptIDs) == 0 {
		return nil
	}

	existingTopics, err := s.ListTopics(ctx, userID)
	if err != nil {
		return err
	}

	var targetTopic *store.Topic
	if len(existingTopics) > 0 {
		// Use most recent or first topic if available
		targetTopic = existingTopics[0]
	} else {
		// Create initial topic from document title
		topicName := docTitle
		if len(topicName) > 40 {
			topicName = topicName[:40]
		}
		if topicName == "" {
			topicName = "General Knowledge"
		}

		angle := rand.Float64() * 2 * math.Pi
		distance := 200.0 + rand.Float64()*100.0
		cx := math.Cos(angle) * distance
		cy := math.Sin(angle) * distance

		targetTopic, err = s.UpsertTopic(ctx, userID, topicName, "Automatically generated topic island", 0, cx, cy)
		if err != nil {
			return err
		}
	}

	for _, cid := range conceptIDs {
		_ = s.AssignTopicMembership(ctx, userID, targetTopic.ID, cid, 1.0)
	}

	return nil
}
