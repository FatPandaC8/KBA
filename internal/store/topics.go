package store

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func (s *Store) UpsertTopic(ctx context.Context, userID uuid.UUID, name, description string, colorIndex int, centroidX, centroidY float64) (*Topic, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.topics (user_id, name, description, color_index, centroid_x, centroid_y)
		VALUES ($1, $2, $3, $4, $5, $6)
		ON CONFLICT (user_id, name) DO UPDATE
		SET updated_at = now()
		RETURNING id, user_id, name, description, color_index, centroid_x, centroid_y, created_at, updated_at
	`, userID, strings.TrimSpace(name), description, colorIndex, centroidX, centroidY)

	t := &Topic{}
	if err := row.Scan(&t.ID, &t.UserID, &t.Name, &t.Description, &t.ColorIndex, &t.CentroidX, &t.CentroidY, &t.CreatedAt, &t.UpdatedAt); err != nil {
		return nil, err
	}
	return t, nil
}

func (s *Store) AssignTopicMembership(ctx context.Context, userID, topicID, conceptID uuid.UUID, affinity float64) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.topic_memberships (user_id, topic_id, concept_id, affinity_score)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (topic_id, concept_id) DO UPDATE
		SET affinity_score = $4
	`, userID, topicID, conceptID, affinity)
	return err
}

func (s *Store) ListTopics(ctx context.Context, userID uuid.UUID) ([]*Topic, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, name, description, color_index, centroid_x, centroid_y, created_at, updated_at
		FROM gusby.topics
		WHERE user_id = $1
		ORDER BY name ASC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var topics []*Topic
	for rows.Next() {
		t := &Topic{}
		if err := rows.Scan(&t.ID, &t.UserID, &t.Name, &t.Description, &t.ColorIndex, &t.CentroidX, &t.CentroidY, &t.CreatedAt, &t.UpdatedAt); err != nil {
			return nil, err
		}
		topics = append(topics, t)
	}
	return topics, nil
}

func (s *Store) GetTopicByID(ctx context.Context, userID, topicID uuid.UUID) (*Topic, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, name, description, color_index, centroid_x, centroid_y, created_at, updated_at
		FROM gusby.topics
		WHERE user_id = $1 AND id = $2
	`, userID, topicID)

	t := &Topic{}
	if err := row.Scan(&t.ID, &t.UserID, &t.Name, &t.Description, &t.ColorIndex, &t.CentroidX, &t.CentroidY, &t.CreatedAt, &t.UpdatedAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return t, nil
}

func (s *Store) GetConceptsForTopic(ctx context.Context, userID, topicID uuid.UUID, limit int) ([]*Concept, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT c.id, c.user_id, c.name, c.name_normalized, c.description, c.degree, c.needs_review, c.created_at, c.updated_at
		FROM gusby.topic_memberships tm
		JOIN gusby.concepts c ON tm.concept_id = c.id
		WHERE tm.user_id = $1 AND tm.topic_id = $2
		ORDER BY c.degree DESC
		LIMIT $3
	`, userID, topicID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var concepts []*Concept
	for rows.Next() {
		c := &Concept{}
		if err := rows.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		concepts = append(concepts, c)
	}
	return concepts, nil
}
