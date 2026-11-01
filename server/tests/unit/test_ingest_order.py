"""Unit tests pinning the ingest stage order (ADR R4)."""

from server.app.application.use_cases.ingest import STAGE_ORDER


def test_stage_order_is_defined_once_and_matches_the_adr():
    assert STAGE_ORDER == (
        "normalize_first_person",
        "resolve_entities",
        "link",
        "dedup",
        "embeddings",
        "prune_orphans",
    )


def test_plan_normalize_collapses_multiple_self_placeholders():
    from server.app.domain.entities import ExtractedEntity
    from server.app.application.use_cases.ingest import plan_normalize_first_person

    def ent(eid, is_self=False):
        return ExtractedEntity(
            id=eid, user_id="u", capture_id="c", name=eid,
            entity_type="self" if is_self else "tool",
            is_self=is_self,
        )

    entities = [ent("a", is_self=True), ent("b", True), ent("c")]
    collapsed, dropped = plan_normalize_first_person(entities)
    assert [e.id for e in collapsed] == ["a", "c"], collapsed
    assert dropped == {"b": "a"}


def test_plan_links_maps_endpoints_and_skips_partial_edges():
    from server.app.domain.entities import RelationshipEntity
    from server.app.application.use_cases.ingest import plan_links

    rel = RelationshipEntity(
        id="r1", user_id="u", from_id="x", to_id="y",
        relation_type="Depends on", status="suggested",
    )
    plan = plan_links([rel], {"x": "map-x", "y": "map-y"}, "u", "cap")
    assert [r.from_id for r in plan.relationships] == ["map-x"]
    assert plan.skipped_relationships == 0

    dangling = RelationshipEntity(
        id="r2", user_id="u", from_id="ghost", to_id="y",
        relation_type="Depends on", status="suggested",
    )
    plan2 = plan_links([dangling], {"y": "map-y"}, "u", "cap")
    assert plan2.relationships == [] and plan2.skipped_relationships == 1
