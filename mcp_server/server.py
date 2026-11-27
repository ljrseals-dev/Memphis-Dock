"""MCP tool surface for agentic supervisors. Proxies to the console HTTP API."""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

CONSOLE = os.environ.get("CONSOLE_URL", "http://localhost:8080")

mcp = FastMCP("memphis-dock")


def _get(path: str) -> dict:
    with httpx.Client(timeout=5.0) as c:
        r = c.get(f"{CONSOLE}{path}")
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict) -> dict:
    with httpx.Client(timeout=10.0) as c:
        r = c.post(f"{CONSOLE}{path}", json=body)
        if r.status_code >= 400:
            return {"error": r.status_code, "detail": r.text}
        return r.json()


@mcp.tool()
def dock_state() -> dict:
    """Return the current dock snapshot (berths, barges, cranes, edge nodes)."""
    return _get("/v1/dock/state")


@mcp.tool()
def brute_genius_plan(
    objective: str = "minimize_barge_turnaround",
    max_cost_usd: float = 25.0,
    weights: dict | None = None,
) -> dict:
    """Submit a planning request. Returns plan_id. Use brute_genius_status to poll."""
    body = {
        "objective": objective,
        "constraints": {"max_cost_usd": max_cost_usd},
        "weights": weights or {"turnaround": 0.5, "crane": 0.3, "haul": 0.2},
    }
    return _post("/v1/dock/plan", body)


@mcp.tool()
def brute_genius_launch(
    objective: str = "minimize_barge_turnaround",
    max_cost_usd: float = 25.0,
) -> dict:
    """Alias for brute_genius_plan — launch an exhaustive search."""
    return brute_genius_plan(objective=objective, max_cost_usd=max_cost_usd)


@mcp.tool()
def brute_genius_status(plan_id: str) -> dict:
    """Poll a plan job: status, progress, combos scored, cost so far."""
    return _get(f"/v1/dock/plan/{plan_id}/status")


@mcp.tool()
def brute_genius_results(plan_id: str) -> dict:
    """Return the ranked candidate list once the plan is DONE."""
    return _get(f"/v1/dock/plan/{plan_id}/results")


@mcp.tool()
def brute_genius_kill(plan_id: str) -> dict:
    """Kill a running plan immediately (stops all shards)."""
    return _post(f"/v1/dock/kill/{plan_id}", {})


@mcp.tool()
def dock_plan(objective: str = "minimize_barge_turnaround") -> dict:
    """Convenience wrapper: plan with default ceiling."""
    return brute_genius_plan(objective=objective)


@mcp.tool()
def dock_commit(plan_id: str, candidate_index: int, supervisor_token: str) -> dict:
    """Commit a ranked candidate to the ARM edge runtime. Requires supervisor token."""
    return _post("/v1/dock/execute", {
        "plan_id": plan_id,
        "candidate_index": candidate_index,
        "supervisor_token": supervisor_token,
    })


@mcp.tool()
def dock_abort() -> dict:
    """Emergency stop: kill all planning jobs and drive every edge node to safe state."""
    return _post("/v1/dock/abort", {})


@mcp.tool()
def edge_probe(node_id: str) -> dict:
    """Read telemetry from a single ARM edge node."""
    return _get(f"/v1/edge/{node_id}/telemetry")


if __name__ == "__main__":
    mcp.run()
