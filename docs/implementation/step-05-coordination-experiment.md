# Step 05: Coordination-Layer Systems Experiment

## What changed

- Added `TrackB/coordination_experiment.py` with two explicitly separate paths:
  - `synchronous`: Tier 1 waits for an injected Tier 2 delay.
  - `broker`: Tier 1 starts the delayed Tier 2 work asynchronously and records its alarm latency immediately.
- The harness repeats both paths over 0, 50, 100, 250, and 500 ms delays and writes `TrackB/docs/coordination_experiment.csv`.
- Added regression tests that assert the synchronous path grows with delay while the broker-style path returns first.

## Run it

```powershell
python -m TrackB.coordination_experiment --repeats 5
```

This is a disposable measurement harness. It does not replace the shared Kafka-based coordination path.
