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


def _ent(eid, is_self=False):
    from server.app.domain.entities import ExtractedEntity

    return ExtractedEntity(
        id=eid, user_id="u", capture_id="c", name=eid,
        entity_type="self" if is_self else "tool",
        is_self=is_self,
    )


def test_plan_normalize_collapses_multiple_self_placeholders():
    from server.app.application.use_cases.ingest import plan_normalize_first_person

    entities = [_ent("a", is_self=True), _ent("b", True), _ent("c")]
    collapsed, dropped = plan_normalize_first_person(entities)
    assert [e.id for e in collapsed] == ["a", "c"], collapsed
    assert dropped == {"b": "a"}


# Bug #2 regression: the single KEPT self placeholder (the common case for a
# first-person transcript) must also be remapped to the canonical self id.
def test_single_self_placeholder_relation_maps_to_canonical():
    from server.app.domain.entities import RelationshipEntity
    from server.app.application.use_cases.ingest import (
        collect_self_placeholders,
        plan_rewrite_self_endpoints,
    )

    placeholder = _ent("ph", is_self=True)
    anna = _ent("anna")
    rel = RelationshipEntity(
        id="r1", user_id="u", from_id="ph", to_id="anna",
        relation_type="Met", status="suggested",
    )
    out = plan_rewrite_self_endpoints(
        [rel], collect_self_placeholders([placeholder, anna]), "self-canonical"
    )
    assert [(r.from_id, r.to_id) for r in out] == [("self-canonical", "anna")]


def test_collapsed_self_placeholders_map_to_canonical():
    from server.app.domain.entities import RelationshipEntity
    from server.app.application.use_cases.ingest import (
        collect_self_placeholders,
        plan_rewrite_self_endpoints,
    )

    # Two placeholders: "a" kept, "b" dropped onto "a" by the collapse.
    kept, dropped_ph, anna, ben = _ent("a", True), _ent("b", True), _ent("anna"), _ent("ben")
    rels = [
        RelationshipEntity(id="r1", user_id="u", from_id="a", to_id="anna",
                           relation_type="Met", status="suggested"),
        RelationshipEntity(id="r2", user_id="u", from_id="ben", to_id="b",
                           relation_type="Works with", status="suggested"),
    ]
    out = plan_rewrite_self_endpoints(
        rels, collect_self_placeholders([kept, dropped_ph, anna, ben]), "self-canonical"
    )
    assert [(r.from_id, r.to_id) for r in out] == [
        ("self-canonical", "anna"), ("ben", "self-canonical"),
    ]


def test_reverse_direction_and_non_self_links_untouched():
    from server.app.domain.entities import RelationshipEntity
    from server.app.application.use_cases.ingest import (
        collect_self_placeholders,
        plan_rewrite_self_endpoints,
    )

    placeholder, anna, eco = _ent("ph", True), _ent("anna"), _ent("eco")
    rels = [
        RelationshipEntity(id="r1", user_id="u", from_id="anna", to_id="ph",
                           relation_type="Met", status="suggested"),
        RelationshipEntity(id="r2", user_id="u", from_id="anna", to_id="eco",
                           relation_type="Related to", status="suggested"),
    ]
    out = plan_rewrite_self_endpoints(
        rels, collect_self_placeholders([placeholder, anna, eco]), "self-canonical"
    )
    assert [(r.from_id, r.to_id) for r in out] == [
        ("anna", "self-canonical"), ("anna", "eco"),
    ]



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
