from __future__ import annotations

import time
from dataclasses import dataclass, field

from dockcore.models import NodeKind, NodeStatus

HEARTBEAT_TIMEOUT_S = 6.0


@dataclass
class NodeRuntime:
    id: str
    kind: NodeKind
    status: NodeStatus = NodeStatus.ONLINE
    arch: str = "aarch64"
    last_hb: float = field(default_factory=time.time)
    trajectory: dict | None = None
    metrics: dict = field(default_factory=dict)

    def tick(self) -> None:
        now = time.time()
        if self.kind == NodeKind.SAFETY_PLC:
            if now - self.last_hb > HEARTBEAT_TIMEOUT_S and self.status != NodeStatus.SAFE_STOP:
                self.status = NodeStatus.SAFE_STOP
                self.metrics["reason"] = "heartbeat_lost"
        elif self.kind == NodeKind.CRANE and self.status == NodeStatus.BUSY:
            if self.trajectory and now > self.trajectory.get("ends_at", 0):
                self.status = NodeStatus.ONLINE
                self.trajectory = None
        elif self.kind == NodeKind.MOORING and self.status == NodeStatus.BUSY:
            if self.trajectory and now > self.trajectory.get("ends_at", 0):
                self.status = NodeStatus.ONLINE
                self.trajectory = None


def build_registry() -> dict[str, NodeRuntime]:
    reg: dict[str, NodeRuntime] = {"safety-plc": NodeRuntime("safety-plc", NodeKind.SAFETY_PLC)}
    for b in ("MCK-1", "MCK-2", "RVG-1", "PID-1"):
        reg[f"moor-{b}"] = NodeRuntime(f"moor-{b}", NodeKind.MOORING)
    for c in ("MCK-C1", "MCK-C2", "RVG-C1", "PID-C1", "PID-C2"):
        reg[f"crane-{c}"] = NodeRuntime(f"crane-{c}", NodeKind.CRANE)
    for h in ("McKellar", "Rivergate", "PresidentsIsland"):
        reg[f"fusion-{h}"] = NodeRuntime(f"fusion-{h}", NodeKind.SENSOR_FUSION)
    return reg


REGISTRY = build_registry()
