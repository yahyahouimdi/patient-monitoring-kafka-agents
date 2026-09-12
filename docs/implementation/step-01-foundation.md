# Step 01: Foundation and Run-Path Corrections

## What changed

- Pointed the README and the Tier 2 scenario test at the real fixture location, `docs/kafka/`.
- Corrected the quick-start order so Tier 1 and Tier 2 consume before a scenario is replayed.
- Documented the retrieval service with its actual Uvicorn startup command.
- Added package-safe imports so the retrieval service can be launched as `TrackB.retrieval_service`.
- Registered the `network-requests` Kafka topic alongside the other project topics.
- Aligned Track A's default retrieval URL with the service's port (`8000`).
- Changed the default HTTP timeouts from millisecond-looking values to bounded second values: 30 seconds for Ollama and 2 seconds for retrieval.
- Updated the S5 scenario test to match the DOCX requirement: a high-severity, dedicated connection request.
- Kept Tier 1 alarm messages immutable while allowing Tier 2 to escalate the derived network request when corroborating context warrants it, which is required for S5.

## Verification

The next test run should exercise the S1-S6 harness instead of failing while opening the old `kafka/scenarios.json` path. The remaining service-level checks still require Kafka, Qdrant, and Ollama to be running.
