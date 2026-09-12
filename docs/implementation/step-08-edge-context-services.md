# Step 08: Explicit Edge and Context Services

## What changed

- Added `tiers/edge_service.py`, a FastAPI adapter that exposes the existing deterministic Tier 1 scorer as `POST /score` with an explicit anomaly score.
- Added `tiers/context_agent.py`, a Kafka context normalizer for smart-home, connectivity, and profile events. It publishes bounded structured context to `patient-context`.
- Registered the `patient-context` topic and allowed Tier 2 to consume it alongside the original streams.
- Added tests for critical edge scoring and bounded context history.

## Run the edge adapter

```powershell
python -m uvicorn tiers.edge_service:app --host 127.0.0.1 --port 8002
```

The adapter remains deterministic and does not call an AI model.
