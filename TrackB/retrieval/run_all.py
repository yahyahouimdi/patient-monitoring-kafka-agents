"""Task 1 driver: runs chroma_test, faiss_test and qdrant_test benchmarks
for every corpus size in CORPUS_SIZES, each in its own subprocess so that
BENCHMARK_SCALE (read once by loader.py at import time) is picked up fresh
every run instead of being cached from a previous size.

Usage:
    python run_all_benchmarks.py

Results land in docs/results.csv (one row per store x corpus size, with
average/stdev/min/p50/p95/p99/max) and docs/raw_latencies/<store>_<n>.json
(every individual latency sample, needed later for the P99/boxplot figures).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
CORPUS_SIZES = [6, 100, 1000]
BENCHMARK_SCRIPTS = [
    ROOT_DIR / "chroma_test" / "benchmark.py",
    ROOT_DIR / "faiss_test" / "benchmark.py",
    ROOT_DIR / "qdrant_test" / "benchmark.py",
]


def main() -> None:
    for corpus_size in CORPUS_SIZES:
        for script in BENCHMARK_SCRIPTS:
            print("=" * 60)
            print(f"Running {script.parent.name} | BENCHMARK_SCALE={corpus_size}")
            print("=" * 60)
            env = os.environ.copy()
            env["BENCHMARK_SCALE"] = str(corpus_size)
            result = subprocess.run([sys.executable, str(script)], env=env)
            if result.returncode != 0:
                print(f"WARNING: {script} failed for corpus size {corpus_size} "
                      f"(exit code {result.returncode})", file=sys.stderr)


if __name__ == "__main__":
    main()