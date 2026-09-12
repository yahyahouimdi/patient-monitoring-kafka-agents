# Step 07: Retrieval Persistence and Local Stack

## What changed

- Added Qdrant to `docker-compose.yml` with a named persistent storage volume.
- Changed the retrieval service to reuse an existing populated collection after restart.
- Added the explicit `QDRANT_REBUILD_ON_STARTUP=1` escape hatch for intentional corpus or embedding changes.
- Updated both README quick starts to launch Kafka and Qdrant together.

## Verification

The Python tests remain independent of a live Qdrant instance. The service-level smoke check can now be run after:

```powershell
docker compose up -d kafka qdrant
python -m uvicorn TrackB.retrieval_service:app --host 127.0.0.1 --port 8000
python TrackB/test_retrieval_service.py
```
