# Step 02: Structured Context and Patient-Scoped Retrieval

## What changed

- Tier 2 now keeps a bounded history of timestamped events with `source`, `type`, and `value` fields instead of retaining only the latest topic snapshot.
- `PatientState` exposes that history and derives an optional scenario identifier from fixture events.
- All framework implementations use the same compact event-log narrative formatter.
- LangGraph, AutoGen, and CrewAI now pass the current `patient_id` to Track B's retrieval endpoint so patient filtering is actually used.
- Added a unit test covering event-log preservation and narrative redaction of transport identifiers.

## Verification

The event-log test and the existing Track A test suite should pass. Live retrieval still requires the Qdrant-backed service; the client fallback remains available when it is offline.
