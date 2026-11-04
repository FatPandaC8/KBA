package graph

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"gusby/internal/store"
)

type GraphNode struct {
	ID          string  `json:"id"`
	Label       string  `json:"label"`
	Type        string  `json:"type"` // "topic" or "concept"
	X           float64 `json:"x"`
	Y           float64 `json:"y"`
	Degree      int     `json:"degree,omitempty"`
	NeedsReview bool    `json:"needs_review"`
	ColorIndex  int     `json:"color_index,omitempty"`
}

type GraphEdge struct {
	ID          string  `json:"id"`
	Source      string  `json:"source"`
	Target      string  `json:"target"`
	Label       string  `json:"label"`
	Weight      float64 `json:"weight,omitempty"`
	HasConflict bool    `json:"has_conflict"`
}

type GraphProjectionResponse struct {
	Zoom  string      `json:"zoom"`
	Nodes []GraphNode `json:"nodes"`
	Edges []GraphEdge `json:"edges"`
	Total int         `json:"total"`
}

const (
	MaxNodesFar    = 50
	MaxNodesMedium = 150
	MaxNodesDeep   = 500
)

// GetProjection returns level-of-detail projections with enforced node limits
func GetProjection(ctx context.Context, s *store.Store, userID uuid.UUID, zoom string, topicID *uuid.UUID, filterNeedsReview bool) (*GraphProjectionResponse, error) {
	resp := &GraphProjectionResponse{Zoom: zoom}

	switch zoom {
	case "far":
		// Far Zoom: Topic Islands
		topics, err := s.ListTopics(ctx, userID)
		if err != nil {
			return nil, err
		}

		for _, t := range topics {
			resp.Nodes = append(resp.Nodes, GraphNode{
				ID:         t.ID.String(),
				Label:      t.Name,
				Type:       "topic",
				X:          t.CentroidX,
				Y:          t.CentroidY,
				ColorIndex: t.ColorIndex,
			})
		}
		resp.Total = len(resp.Nodes)
		return resp, nil

	case "medium":
		// Medium Zoom: Top concepts per topic
		query := `
			SELECT c.id, c.name, c.degree, c.needs_review
			FROM gusby.concepts c
			WHERE c.user_id = $1
		`
		args := []any{userID}
		if topicID != nil {
			query += ` AND c.id IN (SELECT concept_id FROM gusby.topic_memberships WHERE user_id = $1 AND topic_id = $2)`
			args = append(args, *topicID)
		}
		if filterNeedsReview {
			query += ` AND c.needs_review = true`
		}
		query += fmt.Sprintf(` ORDER BY c.degree DESC LIMIT %d`, MaxNodesMedium)

		rows, err := s.Pool().Query(ctx, query, args...)
		if err != nil {
			return nil, err
		}
		defer rows.Close()

		for rows.Next() {
			var id uuid.UUID
			var name string
			var degree int
			var needsReview bool
			if err := rows.Scan(&id, &name, &degree, &needsReview); err != nil {
				return nil, err
			}
			resp.Nodes = append(resp.Nodes, GraphNode{
				ID:          id.String(),
				Label:       name,
				Type:        "concept",
				Degree:      degree,
				NeedsReview: needsReview,
			})
		}
		resp.Total = len(resp.Nodes)
		return resp, nil

	case "deep":
		fallthrough
	default:
		// Deep Zoom: Concepts and Proposition Edges
		cQuery := `
			SELECT c.id, c.name, c.degree, c.needs_review
			FROM gusby.concepts c
			WHERE c.user_id = $1
		`
		args := []any{userID}
		if filterNeedsReview {
			cQuery += ` AND c.needs_review = true`
		}
		cQuery += fmt.Sprintf(` ORDER BY c.degree DESC LIMIT %d`, MaxNodesDeep)

		cRows, err := s.Pool().Query(ctx, cQuery, args...)
		if err != nil {
			return nil, err
		}
		defer cRows.Close()

		nodeSet := make(map[uuid.UUID]bool)
		for cRows.Next() {
			var id uuid.UUID
			var name string
			var degree int
			var needsReview bool
			if err := cRows.Scan(&id, &name, &degree, &needsReview); err != nil {
				return nil, err
			}
			nodeSet[id] = true
			resp.Nodes = append(resp.Nodes, GraphNode{
				ID:          id.String(),
				Label:       name,
				Type:        "concept",
				Degree:      degree,
				NeedsReview: needsReview,
			})
		}

		if len(nodeSet) > 0 {
			eQuery := `
				SELECT id, subject_concept_id, predicate, object_concept_id, has_conflict
				FROM gusby.propositions
				WHERE user_id = $1 AND is_canonical = true
				LIMIT 1000
			`
			eRows, err := s.Pool().Query(ctx, eQuery, userID)
			if err == nil {
				defer eRows.Close()
				for eRows.Next() {
					var id, sID, oID uuid.UUID
					var pred string
					var hasConflict bool
					if err := eRows.Scan(&id, &sID, &pred, &oID, &hasConflict); err == nil {
						if nodeSet[sID] || nodeSet[oID] {
							resp.Edges = append(resp.Edges, GraphEdge{
								ID:          id.String(),
								Source:      sID.String(),
								Target:      oID.String(),
								Label:       pred,
								HasConflict: hasConflict,
							})
						}
					}
				}
			}
		}
		resp.Total = len(resp.Nodes)
		return resp, nil
	}
}
