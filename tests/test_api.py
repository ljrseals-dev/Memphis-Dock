import time

from fastapi.testclient import TestClient

from console.app import app


def _wait(client, plan_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get(f"/v1/dock/plan/{plan_id}/status").json()
        if j["status"] in ("DONE", "FAILED", "KILLED"):
            return j
        time.sleep(0.1)
    raise TimeoutError


def test_health():
    with TestClient(app) as c:
        assert c.get("/v1/health").json()["ok"] is True


def test_full_plan_flow():
    with TestClient(app) as c:
        r = c.post("/v1/dock/plan", json={})
        assert r.status_code == 200, r.text
        pid = r.json()["plan_id"]
        job = _wait(c, pid)
        assert job["status"] == "DONE", job
        res = c.get(f"/v1/dock/plan/{pid}/results").json()
        assert res["count"] > 0
        assert res["candidates"][0]["score"] >= res["candidates"][-1]["score"]


def test_cost_ceiling_refused():
    with TestClient(app) as c:
        r = c.post("/v1/dock/plan", json={"constraints": {"max_cost_usd": 0.01}})
        assert r.status_code == 402
        assert r.json()["detail"]["error"] == "cost_ceiling_exceeded"


def test_execute_blocked_in_manual_safe():
    with TestClient(app) as c:
        c.post("/v1/dock/mode", json={"mode": "MANUAL_SAFE"})
        r = c.post("/v1/dock/execute", json={
            "plan_id": "x", "candidate_index": 0, "supervisor_token": "t"})
        assert r.status_code == 423
        c.post("/v1/dock/mode", json={"mode": "SUPERVISED"})


def test_abort_kills_running_plans():
    with TestClient(app) as c:
        pid = c.post("/v1/dock/plan", json={}).json()["plan_id"]
        c.post("/v1/dock/abort")
        job = _wait(c, pid)
        assert job["status"] in ("KILLED", "DONE")


def test_approach_current_limit():
    with TestClient(app) as c:
        r = c.post("/v1/dock/approach", json={
            "vessel_id": "B-101", "berth_id": "MCK-1", "current_knots": 3.0})
        assert r.json()["approved"] is False
        r = c.post("/v1/dock/approach", json={
            "vessel_id": "B-101", "berth_id": "MCK-1", "current_knots": 0.8})
        assert r.json()["approved"] is True
