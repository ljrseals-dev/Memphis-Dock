"""
Brute Genius — exhaustive combinatorial planner for dock scheduling.

Enumerates the Cartesian product of feasible (barge -> berth, crane-set,
haul-route) options, prunes hard-infeasible combinations, scores every
surviving combination against a named objective, and returns the top-K
ranked candidates. Cost-governed and killable.
"""
from __future__ import annotations

import heapq
import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Callable

from dockcore.models import (
    BargeAssignment,
    PlanCandidate,
    PlanRequest,
)

TOP_K = 20
MOORING_BASE_S = 420.0        # 7 minutes fixed per barge
MOORING_PER_M_S = 0.8
PRICE_PER_MILLION = 0.02      # USD per 1M scored combinations
NODE_FLOOR_USD = 0.50
KILL_CHECK_EVERY = 5000


class InfeasibleError(Exception):
    pass


class KilledError(Exception):
    pass


class _Kill:
    def __init__(self) -> None:
        self._ids: set[str] = set()
        self._all = False

    def kill(self, plan_id: str) -> None:
        self._ids.add(plan_id)

    def kill_all(self) -> None:
        self._all = True

    def clear(self) -> None:
        self._ids.clear()
        self._all = False

    def is_killed(self, plan_id: str) -> bool:
        return self._all or plan_id in self._ids


KILL = _Kill()


@dataclass
class Option:
    berth_id: str
    crane_ids: list[str]
    haul_route_id: str
    capacity_tph: float
    haul_time_s: float


@dataclass
class _Candidate:
    assignments: list[BargeAssignment]
    score: float
    breakdown: dict[str, float]
    violations: list[str] = field(default_factory=list)


def _mooring_sequence(berth_id: str, length_m: float) -> list[str]:
    n = max(2, math.ceil(length_m / 30.0))
    return [f"{berth_id}-bollard-{i + 1}" for i in range(n)]


def _domains(state, req: PlanRequest) -> list[tuple]:
    domains: list[tuple] = []
    for barge in sorted(state.barges, key=lambda x: (x.priority, x.id)):
        opts: list[Option] = []
        for berth in state.berths:
            if berth.length_m < barge.length_m * 1.1:
                continue
            if berth.max_draft_m < barge.draft_m + 0.3:
                continue
            cranes = [
                c for c in state.cranes
                if c.berth_id == berth.id and c.status == "ONLINE"
            ]
            if not cranes:
                continue
            routes = [r for r in state.haul_routes if r.berth_id == berth.id]
            if not routes:
                continue
            for k in range(1, min(2, len(cranes)) + 1):
                for cset in itertools.combinations(cranes, k):
                    cap = sum(c.capacity_tph for c in cset)
                    for r in routes:
                        opts.append(Option(
                            berth_id=berth.id,
                            crane_ids=[c.id for c in cset],
                            haul_route_id=r.id,
                            capacity_tph=cap,
                            haul_time_s=r.travel_time_s,
                        ))
        if not opts:
            raise InfeasibleError(f"barge '{barge.id}' has no feasible berth")
        domains.append((barge, opts))
    if not domains:
        raise InfeasibleError("no barges in queue")
    return domains


def estimate(state, req: PlanRequest) -> tuple[int, float]:
    domains = _domains(state, req)
    n = 1
    for _, opts in domains:
        n *= len(opts)
    usd = NODE_FLOOR_USD + PRICE_PER_MILLION * (n / 1_000_000.0)
    return n, round(usd, 4)


def _evaluate(combo, domains, barges, harbors, forbidden, weights) -> _Candidate | None:
    berths_used: set[str] = set()
    cranes_used: set[str] = set()
    assignments: list[BargeAssignment] = []

    for (barge, _opts), opt in zip(domains, combo):
        if opt.berth_id in berths_used:
            return None
        if cranes_used & set(opt.crane_ids):
            return None
        berths_used.add(opt.berth_id)
        cranes_used.update(opt.crane_ids)

        cargo_time = barge.cargo_tonnes / max(opt.capacity_tph, 1.0) * 3600.0
        moor_time = MOORING_BASE_S + MOORING_PER_M_S * barge.length_m
        cycle = cargo_time + opt.haul_time_s + moor_time
        assignments.append(BargeAssignment(
            barge_id=barge.id,
            berth_id=opt.berth_id,
            crane_ids=opt.crane_ids,
            haul_route_id=opt.haul_route_id,
            mooring_sequence=_mooring_sequence(opt.berth_id, barge.length_m),
            est_cycle_s=round(cycle, 1),
            haul_time_s=round(opt.haul_time_s, 1),
        ))

    total_turn = sum(
        a.est_cycle_s * (1.0 + 0.25 * (barges[a.barge_id].priority - 1))
        for a in assignments
    )

    crane_hours: dict[str, float] = {}
    for a in assignments:
        for c in a.crane_ids:
            crane_hours[c] = crane_hours.get(c, 0.0) + a.est_cycle_s
    makespan = max(crane_hours.values())
    util = sum(crane_hours.values()) / (len(crane_hours) * makespan) if makespan else 0.0

    haul_sum = sum(a.haul_time_s for a in assignments)

    violations: list[str] = []
    for i in range(len(assignments)):
        for j in range(i + 1, len(assignments)):
            a1, a2 = assignments[i], assignments[j]
            pair = tuple(sorted((barges[a1.barge_id].cargo_type,
                                 barges[a2.barge_id].cargo_type)))
            if pair in forbidden and harbors[a1.berth_id] == harbors[a2.berth_id]:
                violations.append(f"cargo_adjacency:{pair[0]}+{pair[1]}")
    risk = 0.05 * len(violations)

    w_turn = weights.get("turnaround", 0.5)
    w_crane = weights.get("crane", 0.3)
    w_haul = weights.get("haul", 0.2)

    penalty = (
        w_turn * (total_turn / 36000.0)
        + w_crane * (1.0 - util)
        + w_haul * (haul_sum / 3600.0)
        + risk
    )
    score = round(100.0 / (1.0 + penalty), 4)

    return _Candidate(
        assignments=assignments,
        score=score,
        breakdown={
            "total_turnaround_s": round(total_turn, 1),
            "crane_utilization": round(util, 4),
            "haul_time_s": round(haul_sum, 1),
            "risk": round(risk, 4),
            "penalty": round(penalty, 4),
        },
        violations=violations,
    )


def plan(
    state,
    req: PlanRequest,
    plan_id: str,
    progress: Callable[[int, int], None] | None = None,
    top_k: int = TOP_K,
) -> list[_Candidate]:
    domains = _domains(state, req)

    total = 1
    for _, opts in domains:
        total *= len(opts)
    if total > req.constraints.max_combinations:
        raise InfeasibleError(
            f"{total} combinations exceeds cap {req.constraints.max_combinations}"
        )

    barges = {b.id: b for b, _ in domains}
    harbors = {b.id: b.harbor for b in state.berths}
    forbidden = {tuple(sorted(p)) for p in req.constraints.forbidden_cargo_adjacency}
    weights = req.weights

    heap: list[tuple[float, int, _Candidate]] = []
    counter = 0
    scored = 0

    for combo in itertools.product(*[opts for _, opts in domains]):
        if scored % KILL_CHECK_EVERY == 0:
            if KILL.is_killed(plan_id):
                raise KilledError(plan_id)
            if progress:
                progress(scored, total)
        scored += 1

        cand = _evaluate(combo, domains, barges, harbors, forbidden, weights)
        if cand is None:
            continue

        counter += 1
        if len(heap) < top_k:
            heapq.heappush(heap, (cand.score, counter, cand))
        elif cand.score > heap[0][0]:
            heapq.heapreplace(heap, (cand.score, counter, cand))

    if progress:
        progress(scored, total)

    if KILL.is_killed(plan_id):
        raise KilledError(plan_id)

    ranked = sorted(heap, key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in ranked]


def to_candidate_models(cands: list[_Candidate]) -> list[PlanCandidate]:
    return [
        PlanCandidate(
            assignments=c.assignments,
            score=c.score,
            breakdown=c.breakdown,
            violations=c.violations,
        )
        for c in cands
    ]
