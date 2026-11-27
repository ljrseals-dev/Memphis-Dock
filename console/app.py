from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

import brutegenius
from brutegenius import KILL, InfeasibleError, KilledError, NODE_FLOOR_USD, PRICE_PER_MILLION
from console import safety
from console.seed import seed
from console.state import STORE
from dockcore import tokens
from dockcore.models import (
    ApproachRequest,
    ApproachResponse,
    CommandRequest,
    DockState,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionReceipt,
    HeartbeatBody,
    Mode,
    ModeRequest,
    PlanJob,
    PlanRequest,
)

EDGE_URL = os.environ.get("EDGE_URL", "http://localhost:8090")
HEARTBEAT_INTERVAL_S = 2.0
HEARTBEAT_LOST_S = 6.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORE.state = seed()
    task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Memphis Dock Console API", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------- heartbeat

async def _heartbeat_loop() -> None:
    seq = 0
    async with httpx.AsyncClient(timeout=1.5) as client:
        while True:
            seq += 1
            try:
                await client.post(
                    f"{EDGE_URL}/nodes/safety-plc/heartbeat",
                    json=HeartbeatBody(seq=seq).model_dump(),
                )
                STORE.state.heartbeat_ok = True
                STORE.state.edge_nodes["safety-plc"].last_heartbeat = time.time()
            except Exception:
                plc = STORE.state.edge_nodes.get("safety-plc")
                if plc and time.time() - plc.last_heartbeat > HEARTBEAT_LOST_S:
                    STORE.state.heartbeat_ok = False
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)


# ---------------------------------------------------------------- plan job

async def _run_plan(job: PlanJob, req: PlanRequest) -> None:
    job.status = "RUNNING"

    def progress(scored: int, total: int) -> None:
        job.combos_scored = scored
        job.combos_total = total
        job.progress = round(scored / total, 4) if total else 0.0
        job.est_cost_usd = round(
            NODE_FLOOR_USD + PRICE_PER_MILLION * (scored / 1_000_000.0), 4
        )

    try:
        cands = await asyncio.to_thread(
            brutegenius.plan, STORE.state, req, job.plan_id, progress
        )
        job.candidates = brutegenius.to_candidate_models(cands)
        job.status = "DONE"
        job.progress = 1.0
    except KilledError:
        job.status = "KILLED"
        job.error = "killed by operator or cost governor"
    except InfeasibleError as exc:
        job.status = "FAILED"
        job.error = f"infeasible: {exc}"
    except Exception as exc:  # noqa: BLE001
        job.status = "FAILED"
        job.error = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- routes

@app.get("/v1/health")
async def health() -> dict:
    return {"ok": True, "mode": STORE.mode, "ts": time.time()}


@app.get("/v1/dock/state", response_model=DockState)
async def dock_state() -> DockState:
    return STORE.state


@app.post("/v1/dock/mode")
async def set_mode(req: ModeRequest) -> dict:
    STORE.mode = req.mode
    if req.mode == Mode.MANUAL_SAFE:
        await _broadcast_abort("mode_manual_safe")
    return {"mode": STORE.mode}


@app.post("/v1/dock/plan", response_model=PlanJob)
async def create_plan(req: PlanRequest) -> PlanJob:
    if STORE.mode == Mode.MANUAL_SAFE:
        raise HTTPException(423, "dock is in MANUAL_SAFE mode")

    try:
        combos, usd = brutegenius.estimate(STORE.state, req)
    except InfeasibleError as exc:
        raise HTTPException(422, f"infeasible: {exc}") from exc

    if usd > req.constraints.max_cost_usd:
        raise HTTPException(
            402,
            detail={
                "error": "cost_ceiling_exceeded",
                "estimated_combinations": combos,
                "estimated_cost_usd": usd,
                "max_cost_usd": req.constraints.max_cost_usd,
            },
        )

    job = PlanJob(
        plan_id="pln_" + uuid.uuid4().hex[:10],
        objective=req.objective,
        constraints=req.constraints,
        combos_total=combos,
        est_cost_usd=usd,
    )
    with STORE.lock:
        STORE.jobs[job.plan_id] = job
    asyncio.create_task(_run_plan(job, req))
    return job


@app.get("/v1/dock/plan/{plan_id}/status", response_model=PlanJob)
async def plan_status(plan_id: str) -> PlanJob:
    job = STORE.jobs.get(plan_id)
    if not job:
        raise HTTPException(404, "unknown plan_id")
    return job


@app.get("/v1/dock/plan/{plan_id}/results")
async def plan_results(plan_id: str) -> dict:
    job = STORE.jobs.get(plan_id)
    if not job:
        raise HTTPException(404, "unknown plan_id")
    if job.status != "DONE":
        raise HTTPException(409, f"plan is {job.status}")
    return {
        "plan_id": plan_id,
        "count": len(job.candidates),
        "candidates": [c.model_dump() for c in job.candidates],
    }


@app.post("/v1/dock/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    if STORE.mode == Mode.MANUAL_SAFE:
        raise HTTPException(423, "dock is in MANUAL_SAFE mode")
    if not req.supervisor_token:
        raise HTTPException(401, "supervisor_token required")

    job = STORE.jobs.get(req.plan_id)
    if not job:
        raise HTTPException(404, "unknown plan_id")
    if job.status != "DONE":
        raise HTTPException(409, f"plan is {job.status}")
    if not (0 <= req.candidate_index < len(job.candidates)):
        raise HTTPException(400, "candidate_index out of range")

    cand = job.candidates[req.candidate_index]
    violations = safety.check(cand, STORE.state)
    if violations:
        raise HTTPException(
            409, detail={"error": "safety_veto", "violations": violations}
        )

    token = tokens.issue(req.plan_id, req.candidate_index)
    receipts: list[ExecutionReceipt] = []

    async with httpx.AsyncClient(timeout=2.5) as client:
        for a in cand.assignments:
            moor_node = f"moor-{a.berth_id}"
            receipts.append(await _send(client, moor_node, "MOOR_SEQUENCE", token,
                                        {"sequence": a.mooring_sequence,
                                         "barge_id": a.barge_id}))
            for cid in a.crane_ids:
                receipts.append(await _send(client, f"crane-{cid}", "CRANE_DISPATCH",
                                            token, {"barge_id": a.barge_id,
                                                    "berth_id": a.berth_id,
                                                    "cycle_s": a.est_cycle_s}))

    job.committed = True
    job.committed_index = req.candidate_index
    return ExecuteResponse(
        plan_id=req.plan_id,
        candidate_index=req.candidate_index,
        receipts=receipts,
        trajectory_token=token,
    )


async def _send(client: httpx.AsyncClient, node_id: str, action: str,
                token: str, params: dict) -> ExecutionReceipt:
    try:
        r = await client.post(
            f"{EDGE_URL}/nodes/{node_id}/command",
            json={"action": action, "params": params, "token": token},
        )
        if r.status_code >= 400:
            return ExecutionReceipt(node_id=node_id, action=action,
                                    accepted=False, detail=f"http_{r.status_code}")
        return ExecutionReceipt(node_id=node_id, action=action, accepted=True,
                                detail=r.json().get("detail", "ok"))
    except Exception as exc:  # noqa: BLE001
        return ExecutionReceipt(node_id=node_id, action=action, accepted=False,
                                detail=f"unreachable:{type(exc).__name__}")


@app.post("/v1/dock/abort")
async def abort() -> dict:
    for plan_id, job in STORE.jobs.items():
        if job.status in ("QUEUED", "RUNNING"):
            KILL.kill(plan_id)
            job.status = "KILLED"
    KILL.kill_all()
    await _broadcast_abort("console_abort")
    return {"aborted": True, "ts": time.time()}


async def _broadcast_abort(reason: str) -> None:
    async with httpx.AsyncClient(timeout=1.5) as client:
        for node_id in STORE.state.edge_nodes:
            try:
                await client.post(f"{EDGE_URL}/nodes/{node_id}/abort",
                                  json={"reason": reason})
            except Exception:
                pass


@app.post("/v1/dock/kill/{plan_id}")
async def kill_plan(plan_id: str) -> dict:
    KILL.kill(plan_id)
    job = STORE.jobs.get(plan_id)
    if job and job.status in ("QUEUED", "RUNNING"):
        job.status = "KILLED"
    return {"killed": plan_id}


# ---------------------------------------------------------------- edge proxy

@app.get("/v1/edge/{node_id}/telemetry")
async def edge_telemetry(node_id: str) -> dict:
    async with httpx.AsyncClient(timeout=2.0) as client:
        try:
            r = await client.get(f"{EDGE_URL}/nodes/{node_id}/telemetry")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"edge unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/v1/edge/{node_id}/command")
async def edge_command(node_id: str, req: CommandRequest) -> dict:
    if STORE.mode != Mode.MANUAL_SAFE:
        raise HTTPException(409, "manual commands only allowed in MANUAL_SAFE")
    async with httpx.AsyncClient(timeout=2.0) as client:
        try:
            r = await client.post(
                f"{EDGE_URL}/nodes/{node_id}/command",
                json=req.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"edge unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


# ---------------------------------------------------------------- approach / depart

@app.post("/v1/dock/approach", response_model=ApproachResponse)
async def approach(req: ApproachRequest) -> ApproachResponse:
    berth = next((b for b in STORE.state.berths if b.id == req.berth_id), None)
    if not berth:
        raise HTTPException(404, "unknown berth")
    if req.current_knots > 2.0:
        return ApproachResponse(approved=False,
                                reason=f"current {req.current_knots} kn > 2.0 kn limit")
    if req.wind_knots > 25.0:
        return ApproachResponse(approved=False,
                                reason=f"wind {req.wind_knots} kn > 25 kn limit")
    plc = STORE.state.edge_nodes.get("safety-plc")
    if plc and plc.status == "SAFE_STOP":
        return ApproachResponse(approved=False, reason="safety plc in SAFE_STOP")

    corridor = [
        {"wp": 0, "x": -600, "y": 0, "speed_kn": 1.2},
        {"wp": 1, "x": -300, "y": 0, "speed_kn": 0.8},
        {"wp": 2, "x": -80, "y": 0, "speed_kn": 0.4},
        {"wp": 3, "x": 0, "y": 0, "speed_kn": 0.0},
    ]
    token = tokens.issue(f"approach-{req.vessel_id}", 0, ttl_s=600)
    return ApproachResponse(approved=True, corridor=corridor,
                            reason="corridor approved", trajectory_token=token)


@app.post("/v1/dock/depart", response_model=ApproachResponse)
async def depart(req: ApproachRequest) -> ApproachResponse:
    resp = await approach(req)
    if resp.approved:
        resp.corridor = list(reversed(resp.corridor))
        resp.reason = "departure corridor approved"
    return resp
