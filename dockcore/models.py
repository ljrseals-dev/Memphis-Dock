from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Mode(str, Enum):
    AUTONOMOUS = "AUTONOMOUS"
    SUPERVISED = "SUPERVISED"
    MANUAL_SAFE = "MANUAL_SAFE"


class NodeKind(str, Enum):
    MOORING = "MOORING"
    CRANE = "CRANE"
    SENSOR_FUSION = "SENSOR_FUSION"
    SAFETY_PLC = "SAFETY_PLC"
    HAUL = "HAUL"


class NodeStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    SAFE_STOP = "SAFE_STOP"
    BUSY = "BUSY"


class Berth(BaseModel):
    id: str
    harbor: str
    length_m: float
    max_draft_m: float
    crane_ids: list[str] = Field(default_factory=list)


class Crane(BaseModel):
    id: str
    berth_id: str
    capacity_tph: float
    status: NodeStatus = NodeStatus.ONLINE


class Barge(BaseModel):
    id: str
    length_m: float
    draft_m: float
    cargo_type: str
    cargo_tonnes: float
    priority: int = 1          # 1 = highest
    eta_s: float = 0.0


class HaulRoute(BaseModel):
    id: str
    berth_id: str
    dest: str
    travel_time_s: float
    capacity_tph: float


class EdgeNode(BaseModel):
    id: str
    kind: NodeKind
    status: NodeStatus = NodeStatus.ONLINE
    last_heartbeat: float = Field(default_factory=time.time)
    arch: str = "aarch64"
    metrics: dict = Field(default_factory=dict)


class DockState(BaseModel):
    ts: float = Field(default_factory=time.time)
    barges: list[Barge] = Field(default_factory=list)
    berths: list[Berth] = Field(default_factory=list)
    cranes: list[Crane] = Field(default_factory=list)
    haul_routes: list[HaulRoute] = Field(default_factory=list)
    edge_nodes: dict[str, EdgeNode] = Field(default_factory=dict)
    heartbeat_ok: bool = True


# ---------- planning ----------

class Objective(str, Enum):
    MIN_BARGE_TURNAROUND = "minimize_barge_turnaround"
    MAX_CRANE_UTILIZATION = "maximize_crane_utilization"
    MIN_HAUL_TIME = "minimize_haul_time"
    MIN_RISK = "minimize_risk"


class Constraints(BaseModel):
    max_crane_utilization: float = 0.90
    forbidden_cargo_adjacency: list[tuple[str, str]] = Field(
        default_factory=lambda: [("ammonia", "grain")]
    )
    max_combinations: int = 1_000_000_000
    max_cost_usd: float = 25.0


class PlanRequest(BaseModel):
    objective: Objective = Objective.MIN_BARGE_TURNAROUND
    constraints: Constraints = Field(default_factory=Constraints)
    weights: dict[str, float] = Field(
        default_factory=lambda: {"turnaround": 0.5, "crane": 0.3, "haul": 0.2}
    )


class BargeAssignment(BaseModel):
    barge_id: str
    berth_id: str
    crane_ids: list[str]
    haul_route_id: str
    mooring_sequence: list[str]
    est_cycle_s: float
    haul_time_s: float


class PlanCandidate(BaseModel):
    assignments: list[BargeAssignment]
    score: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)


class PlanJob(BaseModel):
    plan_id: str
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED", "KILLED"] = "QUEUED"
    submitted_at: float = Field(default_factory=time.time)
    objective: Objective = Objective.MIN_BARGE_TURNAROUND
    constraints: Constraints = Field(default_factory=Constraints)
    progress: float = 0.0
    combos_total: int = 0
    combos_scored: int = 0
    est_cost_usd: float = 0.0
    error: str | None = None
    candidates: list[PlanCandidate] = Field(default_factory=list)
    committed: bool = False
    committed_index: int | None = None


# ---------- execution ----------

class ExecuteRequest(BaseModel):
    plan_id: str
    candidate_index: int = 0
    supervisor_token: str


class ExecutionReceipt(BaseModel):
    node_id: str
    action: str
    accepted: bool
    detail: str = ""


class ExecuteResponse(BaseModel):
    plan_id: str
    candidate_index: int
    receipts: list[ExecutionReceipt]
    trajectory_token: str


class ModeRequest(BaseModel):
    mode: Mode


class CommandRequest(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)
    token: str = ""


class ApproachRequest(BaseModel):
    vessel_id: str
    berth_id: str
    current_knots: float = 0.5
    wind_knots: float = 5.0


class ApproachResponse(BaseModel):
    approved: bool
    corridor: list[dict] = Field(default_factory=list)
    reason: str = ""
    trajectory_token: str = ""


class HeartbeatBody(BaseModel):
    plan_id: str | None = None
    seq: int = 0
