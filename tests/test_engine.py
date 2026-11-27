import pytest

import brutegenius
from brutegenius import KILL, InfeasibleError, KilledError
from console.seed import seed
from dockcore.models import PlanRequest


def test_estimate_and_plan_ranked():
    st = seed()
    req = PlanRequest()
    combos, usd = brutegenius.estimate(st, req)
    assert combos > 0
    assert usd > 0

    cands = brutegenius.plan(st, req, "pln_test")
    assert 1 <= len(cands) <= 20
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)

    for c in cands:
        berths = [a.berth_id for a in c.assignments]
        cranes = [cid for a in c.assignments for cid in a.crane_ids]
        assert len(berths) == len(set(berths))
        assert len(cranes) == len(set(cranes))


def test_kill_aborts_plan():
    KILL.clear()
    st = seed()
    KILL.kill("pln_kill")
    with pytest.raises(KilledError):
        brutegenius.plan(st, PlanRequest(), "pln_kill")
    KILL.clear()


def test_infeasible_when_no_berth():
    st = seed()
    st.berths = []
    with pytest.raises(InfeasibleError):
        brutegenius.estimate(st, PlanRequest())


def test_forbidden_adjacency_is_soft_penalty():
    st = seed()
    req = PlanRequest()
    req.constraints.forbidden_cargo_adjacency = [("ammonia", "grain")]
    cands = brutegenius.plan(st, req, "pln_adj", top_k=50)
    assert any("cargo_adjacency" in v for c in cands for v in c.violations)
