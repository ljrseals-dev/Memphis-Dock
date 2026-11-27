from __future__ import annotations

import time

import httpx


class DockClient:
    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _c(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout)

    def state(self) -> dict:
        with self._c() as c:
            return c.get(f"{self.base_url}/v1/dock/state").json()

    def plan(self, objective: str = "minimize_barge_turnaround",
             max_cost_usd: float = 25.0, weights: dict | None = None) -> dict:
        body = {
            "objective": objective,
            "constraints": {"max_cost_usd": max_cost_usd},
            "weights": weights or {"turnaround": 0.5, "crane": 0.3, "haul": 0.2},
        }
        with self._c() as c:
            r = c.post(f"{self.base_url}/v1/dock/plan", json=body)
            r.raise_for_status()
            return r.json()

    def wait(self, plan_id: str, timeout_s: float = 60.0, poll_s: float = 0.25) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            with self._c() as c:
                job = c.get(f"{self.base_url}/v1/dock/plan/{plan_id}/status").json()
            if job["status"] in ("DONE", "FAILED", "KILLED"):
                return job
            time.sleep(poll_s)
        raise TimeoutError(f"plan {plan_id} did not finish in {timeout_s}s")

    def results(self, plan_id: str) -> dict:
        with self._c() as c:
            return c.get(f"{self.base_url}/v1/dock/plan/{plan_id}/results").json()

    def commit(self, plan_id: str, candidate_index: int, supervisor_token: str) -> dict:
        with self._c() as c:
            r = c.post(f"{self.base_url}/v1/dock/execute", json={
                "plan_id": plan_id,
                "candidate_index": candidate_index,
                "supervisor_token": supervisor_token,
            })
            return {"status": r.status_code, "body": r.json()}

    def abort(self) -> dict:
        with self._c() as c:
            return c.post(f"{self.base_url}/v1/dock/abort").json()

    def set_mode(self, mode: str) -> dict:
        with self._c() as c:
            return c.post(f"{self.base_url}/v1/dock/mode", json={"mode": mode}).json()
