from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from dockcore import tokens
from dockcore.models import CommandRequest, HeartbeatBody
from edge.runtime import REGISTRY, NodeRuntime

TOKEN_ACTIONS = {"MOOR_SEQUENCE", "CRANE_DISPATCH", "APPROACH", "DEPART"}
MANUAL_ACTIONS = {"JOG", "CALIBRATE", "RESET", "HOME"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    async def ticker() -> None:
        while True:
            for node in REGISTRY.values():
                node.tick()
            await asyncio.sleep(0.5)

    task = asyncio.create_task(ticker())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="ARM Edge Runtime", version="0.1.0", lifespan=lifespan)


def _node(node_id: str) -> NodeRuntime:
    n = REGISTRY.get(node_id)
    if not n:
        raise HTTPException(404, f"unknown node {node_id}")
    return n


@app.get("/nodes")
async def list_nodes() -> dict:
    return {
        "arch": "aarch64",
        "count": len(REGISTRY),
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind.value,
                "status": n.status.value,
                "arch": n.arch,
                "last_hb_age_s": round(time.time() - n.last_hb, 2),
            }
            for n in REGISTRY.values()
        ],
    }


@app.get("/nodes/{node_id}/telemetry")
async def telemetry(node_id: str) -> dict:
    n = _node(node_id)
    return {
        "id": n.id,
        "kind": n.kind.value,
        "status": n.status.value,
        "arch": n.arch,
        "last_hb_age_s": round(time.time() - n.last_hb, 2),
        "trajectory": n.trajectory,
        "metrics": n.metrics,
    }


@app.post("/nodes/{node_id}/heartbeat")
async def heartbeat(node_id: str, body: HeartbeatBody) -> dict:
    n = _node(node_id)
    if n.kind.value != "SAFETY_PLC":
        raise HTTPException(400, "heartbeat only accepted by SAFETY_PLC")
    n.last_hb = time.time()
    if n.status == "SAFE_STOP":
        n.status = "ONLINE"
        n.metrics.pop("reason", None)
    n.metrics["seq"] = body.seq
    return {"ok": True, "status": n.status.value}


@app.post("/nodes/{node_id}/command")
async def command(node_id: str, req: CommandRequest) -> dict:
    n = _node(node_id)

    if n.status == "SAFE_STOP" and req.action not in MANUAL_ACTIONS:
        raise HTTPException(423, "node in SAFE_STOP; reset required")

    if req.action in TOKEN_ACTIONS:
        payload = tokens.verify(req.token)
        if not payload:
            raise HTTPException(403, "invalid or expired trajectory token")
        if req.action in ("APPROACH", "DEPART") and n.kind.value != "MOORING":
            raise HTTPException(400, "approach/depart only valid on mooring nodes")
        if req.action == "MOOR_SEQUENCE" and n.kind.value != "MOORING":
            raise HTTPException(400, "MOOR_SEQUENCE only valid on mooring nodes")
        if req.action == "CRANE_DISPATCH" and n.kind.value != "CRANE":
            raise HTTPException(400, "CRANE_DISPATCH only valid on crane nodes")

        duration = float(req.params.get("cycle_s", 30.0))
        n.trajectory = {
            "plan_id": payload["p"],
            "candidate_index": payload["c"],
            "action": req.action,
            "params": req.params,
            "started_at": time.time(),
            "ends_at": time.time() + duration,
        }
        n.status = "BUSY"
        n.metrics["last_action"] = req.action
        return {"accepted": True, "detail": f"{req.action} engaged for {duration}s"}

    if req.action in MANUAL_ACTIONS:
        if not req.params.get("manual_ack"):
            raise HTTPException(400, "manual_ack required for manual actions")
        if req.action == "RESET":
            n.status = "ONLINE"
            n.trajectory = None
            n.metrics.pop("reason", None)
        n.metrics["manual"] = req.action
        return {"accepted": True, "detail": f"manual {req.action}"}

    raise HTTPException(400, f"unknown action {req.action}")


@app.post("/nodes/{node_id}/abort")
async def abort(node_id: str, body: dict | None = None) -> dict:
    n = _node(node_id)
    n.status = "SAFE_STOP"
    n.trajectory = None
    n.metrics["reason"] = (body or {}).get("reason", "abort")
    return {"ok": True, "status": n.status.value}


@app.post("/nodes/{node_id}/reset")
async def reset(node_id: str) -> dict:
    n = _node(node_id)
    n.status = "ONLINE"
    n.trajectory = None
    n.metrics.pop("reason", None)
    return {"ok": True, "status": n.status.value}
