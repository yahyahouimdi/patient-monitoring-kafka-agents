"""Measure the broker-only coordination rule against a synchronous anti-pattern."""

from __future__ import annotations

import argparse
import csv
import threading
import time
from pathlib import Path
from typing import Iterable

from tiers import tier1_agent


DEFAULT_EVENT = {
    "patient_id": "P001",
    "device_id": "watch-001",
    "timestamp": "2026-09-12T00:00:00+00:00",
    "heart_rate": 155,
    "spo2": 95,
    "body_temperature": 37.2,
    "fall_detection": 0,
}
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "docs" / "coordination_experiment.csv"


def _delayed_tier2(delay_s: float) -> None:
    time.sleep(delay_s)


def measure_once(path: str, event: dict, delay_s: float) -> dict:
    """Return Tier 1 latency for one synchronous or broker-style run."""
    started = time.perf_counter()
    severity, reason = tier1_agent.evaluate(event)

    if path == "synchronous":
        _delayed_tier2(delay_s)
    elif path == "broker":
        worker = threading.Thread(target=_delayed_tier2, args=(delay_s,), daemon=True)
        worker.start()
    else:
        raise ValueError(f"unknown coordination path: {path}")

    latency_ms = (time.perf_counter() - started) * 1000.0
    if path == "broker":
        worker.join()

    return {
        "path": path,
        "delay_s": delay_s,
        "tier1_latency_ms": round(latency_ms, 3),
        "severity": severity or "normal",
        "reason": reason or "no threshold crossed",
    }


def run_experiment(
    delays: Iterable[float] = (0.0, 0.05, 0.1, 0.25, 0.5),
    repeats: int = 5,
    event: dict | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> list[dict]:
    event = dict(event or DEFAULT_EVENT)
    rows = []
    for delay_s in delays:
        for repeat in range(repeats):
            for path in ("synchronous", "broker"):
                row = measure_once(path, event, float(delay_s))
                row["repeat"] = repeat
                rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = run_experiment(repeats=args.repeats, output_path=args.output)
    print(f"wrote {len(rows)} measurements to {args.output}")


if __name__ == "__main__":
    main()
