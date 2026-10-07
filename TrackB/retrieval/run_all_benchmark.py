"""Driver for the vector-store benchmark: runs the chroma_test, faiss_test and
qdrant_test benchmarks for every corpus size, each in its own subprocess so
one store's memory and caches cannot influence the next.

Requires a running Qdrant server (`docker compose up -d qdrant`).

Usage (from the repository root):
    python TrackB/retrieval/run_all_benchmark.py --fresh

Outputs:
    docs/results.csv                 one row per store x corpus size x mode
    docs/raw_latencies/*.json        every individual latency sample
    docs/benchmark_environment.json  machine and software versions of the run
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parent
DOCS_DIR = ROOT_DIR.parent / "docs"
CORPUS_SIZES = [100, 1000, 10000, 50000]
BENCHMARK_SCRIPTS = [
    ROOT_DIR / "faiss_test" / "benchmark.py",
    ROOT_DIR / "chroma_test" / "benchmark.py",
    ROOT_DIR / "qdrant_test" / "benchmark.py",
]


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _qdrant_server_version() -> str | None:
    url = f"http://{os.getenv('QDRANT_HOST', 'localhost')}:{os.getenv('QDRANT_PORT', '6333')}"
    try:
        with urlopen(url, timeout=5) as response:
            return json.load(response).get("version")
    except Exception:
        return None


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def write_environment(sizes: list[int]) -> None:
    sys.path.insert(0, str(ROOT_DIR))
    import benchmark_common

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "benchmark_environment.json").write_text(
        json.dumps({
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "git_commit_at_run": _git_commit(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "packages": {
                name: _package_version(name)
                for name in ("faiss-cpu", "chromadb", "qdrant-client", "sentence-transformers", "numpy")
            },
            "qdrant_server_version": _qdrant_server_version(),
            "embedding_model": benchmark_common.EMBEDDING_MODEL_NAME,
            "top_k": benchmark_common.TOP_K,
            "target_samples_per_mode": benchmark_common.TARGET_SAMPLES,
            "warmup_queries": benchmark_common.WARMUP_QUERIES,
            "corpus_sizes": sizes,
        }, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove prior aggregate and raw benchmark outputs before this run.",
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=CORPUS_SIZES)
    args = parser.parse_args()

    if args.fresh:
        results_path = DOCS_DIR / "results.csv"
        raw_dir = DOCS_DIR / "raw_latencies"
        if results_path.exists():
            results_path.unlink()
        if raw_dir.exists():
            for raw_file in raw_dir.glob("*.json"):
                raw_file.unlink()

    write_environment(args.sizes)

    failures = 0
    for corpus_size in args.sizes:
        for script in BENCHMARK_SCRIPTS:
            print(f"--- {script.parent.name} | corpus size {corpus_size}", flush=True)
            env = os.environ.copy()
            env["BENCHMARK_SCALE"] = str(corpus_size)
            result = subprocess.run([sys.executable, str(script)], env=env)
            if result.returncode != 0:
                failures += 1
                print(f"WARNING: {script} failed for corpus size {corpus_size} "
                      f"(exit code {result.returncode})", file=sys.stderr)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
