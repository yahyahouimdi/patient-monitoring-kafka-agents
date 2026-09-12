# Step 04: Fair Framework Benchmarking

## What changed

- Added a lightweight native-Python pipeline as the fourth comparison candidate required by Proposal A.
- Added deterministic benchmark adapters for retrieval, the local reasoning call, and emission.
- Wrapped every candidate in the same mocked stage costs, so recorded overhead excludes model and retrieval variability.
- Kept production clients unchanged outside the benchmark process.
- Made the benchmark recorder include framework-managed background threads, which is needed for CrewAI's tool dispatcher.
- Updated the Track A README to describe the four-candidate comparison and the native baseline.

## Verification

Run the benchmark with:

```powershell
python -m TrackA.benchmark.run_benchmark --repeats 1
```

The resulting `TrackA/benchmark/results.json` should contain non-empty stage logs for reasoning paths and a fourth `lightweight` summary. The full test suite remains independent of the benchmark's optional framework runtime costs.
