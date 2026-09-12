# Step 03: Network-Request Persistence and Read API

## What changed

- Tier 2 network requests now include the optional scenario ID and are written to Kafka and a durable JSONL artifact.
- Fixture replay stamps every event with its scenario ID so emitted requests can be queried later.
- Added `TrackB/request_service.py` with `GET /health`, `GET /requests/latest`, and `GET /requests/{scenario}`.
- Added a checked-in OpenAPI contract at `docs/network_request_service.openapi.yaml`.
- Added service tests for latest-request lookup, scenario lookup, and the empty-log response.

## Running the service

```powershell
python -m uvicorn TrackB.request_service:app --host 127.0.0.1 --port 8001
```

The service reads `TrackB/docs/network_requests.jsonl` by default. Set `NETWORK_REQUEST_LOG_PATH` when using a different artifact location.
