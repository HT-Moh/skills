import pytest

import selection
from plan_schema import PlanError


def item(id, risk="safe", status="proposed", deps=(), phase=None):
    return {"id": id, "phase": phase if phase is not None else int(id[1]), "risk": risk, "status": status,
            "depends_on": list(deps), "title": id, "checks": [], "ops": [{"kind": "manual", "text": "x"}]
            if risk == "manual" else [{"kind": "json_set", "file": "~/.claude/settings.json", "path": ["a"], "value": 1}]}


def plan(*items):
    return {"schema": 2, "items": list(items)}


def test_group_tokens_exclude_rolled_back():
    p = plan(item("P1-01", status="rolled_back"), item("P1-02"))
    assert [i["id"] for i in selection.select(p, ["safe"])] == ["P1-02"]
    assert [i["id"] for i in selection.select(p, ["phase1"])] == ["P1-02"]
    assert [i["id"] for i in selection.select(p, ["all"])] == ["P1-02"]


def test_group_tokens_exclude_needs_user_failed_and_purged():
    p = plan(item("P1-01", status="needs_user"), item("P1-02", status="failed"),
             item("P1-03", status="applied-purged"), item("P1-04"))
    assert [i["id"] for i in selection.select(p, ["all"])] == ["P1-04"]


def test_explicit_id_selects_rolled_back():
    p = plan(item("P1-01", status="rolled_back"))
    assert [i["id"] for i in selection.select(p, ["P1-01"])] == ["P1-01"]


def test_empty_selection_raises():
    with pytest.raises(PlanError, match="no item"):
        selection.select(plan(item("P1-01", status="applied")), ["safe"])


def test_unknown_token_raises():
    with pytest.raises(PlanError, match="unknown"):
        selection.select(plan(item("P1-01")), ["banana"])


def test_selection_is_dependency_ordered():
    p = plan(item("P2-01", deps=["P5-01"]), item("P5-01"))
    assert [i["id"] for i in selection.select(p, ["all"])] == ["P5-01", "P2-01"]


def test_manual_dep_selected_is_still_blocker():
    manual = item("P0-01", risk="manual")
    dependent = item("P0-03", risk="review", deps=["P0-01"])
    p = plan(manual, dependent)
    assert selection.blockers(dependent, p, succeeded=set(), selected={"P0-01", "P0-03"}) == ["P0-01"]


def test_manual_dep_done_satisfies():
    manual = item("P0-01", risk="manual", status="done")
    dependent = item("P0-03", risk="review", deps=["P0-01"])
    assert selection.blockers(dependent, plan(manual, dependent), succeeded=set(), selected=set()) == []


def test_non_manual_dep_selected_counts_when_planning():
    # Dry-run: every selected non-manual dep is assumed to run first (topological order).
    dep = item("P1-01")
    dependent = item("P1-02", deps=["P1-01"])
    assert selection.blockers(dependent, plan(dep, dependent), succeeded=set(), selected={"P1-01"}) == []


def test_non_manual_dep_blocks_when_applying_and_not_succeeded():
    # Apply pass: the runner passes selected=set(); a dep that failed earlier is not in succeeded.
    dep = item("P1-01")
    dependent = item("P1-02", deps=["P1-01"])
    assert selection.blockers(dependent, plan(dep, dependent), succeeded=set(), selected=set()) == ["P1-01"]


def test_non_manual_dep_succeeded_satisfies():
    dep = item("P1-01")
    dependent = item("P1-02", deps=["P1-01"])
    assert selection.blockers(dependent, plan(dep, dependent), succeeded={"P1-01"}, selected={"P1-01"}) == []


def test_applied_dep_satisfies():
    dep = item("P1-01", status="applied")
    dependent = item("P1-02", deps=["P1-01"])
    assert selection.blockers(dependent, plan(dep, dependent), succeeded=set(), selected=set()) == []


def test_mark_done_refuses_review_item():
    p = plan(item("P1-01", risk="review"))
    with pytest.raises(PlanError, match="manual"):
        selection.mark_done(p, ["P1-01"])


def test_mark_done_sets_done_at_and_returns_unblocked():
    manual = item("P0-01", risk="manual")
    dependent = item("P0-03", risk="review", deps=["P0-01"])
    other = item("P0-04", risk="review", deps=["P0-01", "P0-02"])
    p = plan(manual, item("P0-02", risk="manual"), dependent, other)
    unblocked = selection.mark_done(p, ["P0-01"])
    assert manual["status"] == "done" and manual["done_at"]
    assert unblocked == ["P0-03"]


def test_mark_done_unknown_id_raises():
    with pytest.raises(PlanError, match="P9-99"):
        selection.mark_done(plan(item("P0-01", risk="manual")), ["P9-99"])


def test_mark_undone_resets_to_proposed():
    manual = item("P0-01", risk="manual", status="done")
    manual["done_at"] = "x"
    selection.mark_undone(plan(manual), ["P0-01"])
    assert manual["status"] == "proposed" and "done_at" not in manual


def test_mark_undone_refuses_non_done():
    with pytest.raises(PlanError):
        selection.mark_undone(plan(item("P0-01", risk="manual")), ["P0-01"])
