"""Safety predicate registry. Every candidate plan is checked before execution."""
from __future__ import annotations

from typing import Callable

from dockcore.models import NodeKind, PlanCandidate, DockState

Predicate = Callable[[PlanCandidate, DockState], "str | None"]
PREDICATES: list[Predicate] = []


def predicate(fn: Predicate) -> Predicate:
    PREDICATES.append(fn)
    return fn


@predicate
def berth_geometry(c: PlanCandidate, s: DockState) -> str | None:
    berths = {b.id: b for b in s.berths}
    barges = {b.id: b for b in s.barges}
    for a in c.assignments:
        b = berths.get(a.berth_id)
        if b is None:
            return f"unknown_berth:{a.berth_id}"
        v = barges.get(a.barge_id)
        if v is None:
            return f"unknown_barge:{a.barge_id}"
        if b.length_m < v.length_m * 1.1:
            return f"berth_too_short:{a.berth_id}/{a.barge_id}"
        if b.max_draft_m < v.draft_m + 0.3:
            return f"draft_breach:{a.berth_id}/{a.barge_id}"
    return None


@predicate
def cranes_online(c: PlanCandidate, s: DockState) -> str | None:
    online = {cr.id for cr in s.cranes if cr.status == "ONLINE"}
    for a in c.assignments:
        for cid in a.crane_ids:
            if cid not in online:
                return f"crane_not_online:{cid}"
    return None


@predicate
def no_double_booking(c: PlanCandidate, s: DockState) -> str | None:
    berths: set[str] = set()
    cranes: set[str] = set()
    for a in c.assignments:
        if a.berth_id in berths:
            return f"berth_double_booked:{a.berth_id}"
        berths.add(a.berth_id)
        for cid in a.crane_ids:
            if cid in cranes:
                return f"crane_double_booked:{cid}"
            cranes.add(cid)
    return None


@predicate
def hazard_zone_clear(c: PlanCandidate, s: DockState) -> str | None:
    for node in s.edge_nodes.values():
        if node.kind == NodeKind.SENSOR_FUSION:
            if node.metrics.get("personnel_in_hazard"):
                return f"personnel_in_hazard:{node.id}"
    return None


@predicate
def heartbeat_ok(c: PlanCandidate, s: DockState) -> str | None:
    if not s.heartbeat_ok:
        return "console_heartbeat_lost"
    plc = s.edge_nodes.get("safety-plc")
    if plc and plc.status == "SAFE_STOP":
        return "safety_plc_safe_stop"
    return None


def check(c: PlanCandidate, s: DockState) -> list[str]:
    out: list[str] = []
    for fn in PREDICATES:
        r = fn(c, s)
        if r:
            out.append(r)
    return out
