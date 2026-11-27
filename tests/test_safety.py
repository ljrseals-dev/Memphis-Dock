from console import safety
from console.seed import seed
from dockcore.models import BargeAssignment, NodeStatus, PlanCandidate


def _cand(barge_id="B-101", berth_id="MCK-1", cranes=("MCK-C1",)):
    return PlanCandidate(
        assignments=[BargeAssignment(
            barge_id=barge_id, berth_id=berth_id, crane_ids=list(cranes),
            haul_route_id="H-MCK-1-rail", mooring_sequence=["b1", "b2"],
            est_cycle_s=3000, haul_time_s=900,
        )],
        score=50.0,
    )


def test_clean_plan_passes():
    st = seed()
    assert safety.check(_cand(), st) == []


def test_double_booking_caught():
    st = seed()
    c = _cand()
    c.assignments.append(c.assignments[0].model_copy())
    v = safety.check(c, st)
    assert any("double_booked" in x for x in v)


def test_crane_offline_caught():
    st = seed()
    for cr in st.cranes:
        if cr.id == "MCK-C1":
            cr.status = NodeStatus.OFFLINE
    assert any("crane_not_online" in x for x in safety.check(_cand(), st))


def test_personnel_hazard_caught():
    st = seed()
    st.edge_nodes["fusion-McKellar"].metrics["personnel_in_hazard"] = True
    assert any("personnel_in_hazard" in x for x in safety.check(_cand(), st))


def test_heartbeat_loss_caught():
    st = seed()
    st.heartbeat_ok = False
    assert any("heartbeat" in x for x in safety.check(_cand(), st))
