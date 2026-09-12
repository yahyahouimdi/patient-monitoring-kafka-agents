# Step 06: Track A Ablation Harness

## What changed

- Added `TrackA/ablation.py` to process the same scenario states through:
  - the deterministic rule-table baseline, and
  - the full LangGraph Tier 2 path with retrieval and reasoning clients.
- Recorded an expected-divergence note before each scenario run for S1, S2, S4, S5, and S6.
- Added an offline deterministic reasoning mode for reproducible repository checks and a `--live` mode for Ollama/retrieval-backed runs.
- Added `TrackA/docs/ablation_results.csv` as the side-by-side output artifact.
- Added a regression test for S4 escalation, S5 contextual escalation, and S6 confidence preservation.

## Run it

```powershell
python -m TrackA.ablation
python -m TrackA.ablation --live
```

The offline mode verifies the orchestration and guardrail contract without requiring Kafka. The live mode exercises the configured retrieval and Ollama services.
