# Memphis Dock — Agentic Autonomous Unloading/Offloading System

Brute-force combinatorial planning (Brute Genius) + agentic console API +
ARM-native edge runtime + MCP tool surface.

## Run locally

    pip install -e ".[dev]"
    uvicorn edge.app:app --port 8090 &
    uvicorn console.app:app --port 8080 &

## Run on ARM (aarch64)

    docker compose up --build

## Demo flow

    python - <<'PY'
    from sdk import DockClient
    c = DockClient()
    print(c.state()["barges"][0])
    job = c.plan(max_cost_usd=5.0)
    done = c.wait(job["plan_id"])
    print(done["status"], done["combos_scored"], done["est_cost_usd"])
    res = c.results(job["plan_id"])
    print("top score", res["candidates"][0]["score"])
    print(c.commit(job["plan_id"], 0, "sup-001"))
    PY

## Architecture

    [Agent / MCP] -> [Console API :8080] -> [Brute Genius engine]
                          |                       |
                          v                       v
                    [Safety predicates]    [ranked candidates]
                          |
                          v
                    [ARM Edge :8090] -> mooring winches / cranes / safety PLC

- Console exposes intent-level endpoints and blocks execution in `MANUAL_SAFE`.
- Brute Genius enumerates the Cartesian product of feasible
  (barge, berth, crane-set, haul-route) options, prunes, scores, ranks.
  Cost governor refuses requests whose estimate exceeds `max_cost_usd`.
- Edge runtime verifies HMAC trajectory tokens, runs heartbeat watchdog,
  and drives to `SAFE_STOP` on abort or heartbeat loss.
- `POST /v1/dock/abort` kills all planning shards and all edge nodes.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /v1/health | liveness + mode |
| GET | /v1/dock/state | full dock snapshot |
| POST | /v1/dock/mode | AUTONOMOUS / SUPERVISED / MANUAL_SAFE |
| POST | /v1/dock/plan | submit planning request |
| GET | /v1/dock/plan/{id}/status | job progress |
| GET | /v1/dock/plan/{id}/results | ranked candidates |
| POST | /v1/dock/execute | safety-check + dispatch to edge |
| POST | /v1/dock/abort | kill plans + safe-stop edge |
| POST | /v1/dock/kill/{id} | kill a single plan |
| POST | /v1/dock/approach | docking corridor approval |
| POST | /v1/dock/depart | departure corridor approval |
| GET | /v1/edge/{node}/telemetry | edge node telemetry |
| POST | /v1/edge/{node}/command | manual command (MANUAL_SAFE only) |

## Tests

    pytest -q
