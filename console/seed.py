"""Memphis slack-water scenario: three harbors, mixed bulk, ARM edge nodes."""
from __future__ import annotations

from dockcore.models import (
    Barge,
    Berth,
    Crane,
    DockState,
    EdgeNode,
    HaulRoute,
    NodeKind,
    NodeStatus,
)


def seed() -> DockState:
    berths = [
        Berth(id="MCK-1", harbor="McKellar", length_m=300, max_draft_m=12.0,
              crane_ids=["MCK-C1"]),
        Berth(id="MCK-2", harbor="McKellar", length_m=260, max_draft_m=11.0,
              crane_ids=["MCK-C2"]),
        Berth(id="RVG-1", harbor="Rivergate", length_m=240, max_draft_m=10.0,
              crane_ids=["RVG-C1"]),
        Berth(id="PID-1", harbor="PresidentsIsland", length_m=320, max_draft_m=13.0,
              crane_ids=["PID-C1", "PID-C2"]),
    ]
    cranes = [
        Crane(id="MCK-C1", berth_id="MCK-1", capacity_tph=400),
        Crane(id="MCK-C2", berth_id="MCK-2", capacity_tph=320),
        Crane(id="RVG-C1", berth_id="RVG-1", capacity_tph=280),
        Crane(id="PID-C1", berth_id="PID-1", capacity_tph=450),
        Crane(id="PID-C2", berth_id="PID-1", capacity_tph=380),
    ]
    barges = [
        Barge(id="B-101", length_m=180, draft_m=8.5, cargo_type="grain",
              cargo_tonnes=4200, priority=1, eta_s=0),
        Barge(id="B-102", length_m=150, draft_m=7.2, cargo_type="ammonia",
              cargo_tonnes=2600, priority=2, eta_s=600),
        Barge(id="B-103", length_m=200, draft_m=9.5, cargo_type="steel_coil",
              cargo_tonnes=6800, priority=1, eta_s=1200),
        Barge(id="B-104", length_m=120, draft_m=6.0, cargo_type="grain",
              cargo_tonnes=1800, priority=3, eta_s=1800),
        Barge(id="B-105", length_m=190, draft_m=8.0, cargo_type="ammonia",
              cargo_tonnes=5100, priority=2, eta_s=2400),
        Barge(id="B-106", length_m=160, draft_m=7.8, cargo_type="container",
              cargo_tonnes=3300, priority=2, eta_s=3000),
    ]
    haul_routes = [
        HaulRoute(id="H-MCK-1-rail", berth_id="MCK-1", dest="rail_yard_a",
                  travel_time_s=900, capacity_tph=800),
        HaulRoute(id="H-MCK-1-silo", berth_id="MCK-1", dest="silo_2",
                  travel_time_s=600, capacity_tph=600),
        HaulRoute(id="H-MCK-2-rail", berth_id="MCK-2", dest="rail_yard_a",
                  travel_time_s=1100, capacity_tph=700),
        HaulRoute(id="H-RVG-1-tank", berth_id="RVG-1", dest="tank_farm_1",
                  travel_time_s=1500, capacity_tph=500),
        HaulRoute(id="H-PID-1-rail", berth_id="PID-1", dest="rail_yard_b",
                  travel_time_s=750, capacity_tph=900),
    ]
    edge_nodes = {
        "safety-plc": EdgeNode(id="safety-plc", kind=NodeKind.SAFETY_PLC,
                               arch="aarch64", metrics={"interlocks": "armed"}),
        "moor-MCK-1": EdgeNode(id="moor-MCK-1", kind=NodeKind.MOORING),
        "moor-MCK-2": EdgeNode(id="moor-MCK-2", kind=NodeKind.MOORING),
        "moor-RVG-1": EdgeNode(id="moor-RVG-1", kind=NodeKind.MOORING),
        "moor-PID-1": EdgeNode(id="moor-PID-1", kind=NodeKind.MOORING),
        "crane-MCK-C1": EdgeNode(id="crane-MCK-C1", kind=NodeKind.CRANE),
        "crane-MCK-C2": EdgeNode(id="crane-MCK-C2", kind=NodeKind.CRANE),
        "crane-RVG-C1": EdgeNode(id="crane-RVG-C1", kind=NodeKind.CRANE),
        "crane-PID-C1": EdgeNode(id="crane-PID-C1", kind=NodeKind.CRANE),
        "crane-PID-C2": EdgeNode(id="crane-PID-C2", kind=NodeKind.CRANE),
        "fusion-McKellar": EdgeNode(id="fusion-McKellar",
                                    kind=NodeKind.SENSOR_FUSION),
        "fusion-Rivergate": EdgeNode(id="fusion-Rivergate",
                                     kind=NodeKind.SENSOR_FUSION),
        "fusion-PresidentsIsland": EdgeNode(id="fusion-PresidentsIsland",
                                            kind=NodeKind.SENSOR_FUSION),
    }
    return DockState(
        barges=barges,
        berths=berths,
        cranes=cranes,
        haul_routes=haul_routes,
        edge_nodes=edge_nodes,
    )
