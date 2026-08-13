"""Generates 4 report-ready figures from the REAL benchmark outputs produced
by run_all_benchmarks.py:
    - docs/results.csv            (aggregated stats per store x corpus size)
    - docs/raw_latencies/*.json   (every individual latency sample)

No numbers are invented here: if a store/corpus-size combination is missing
from results.csv, that line/bar is simply absent from the figure.

Run AFTER run_all_benchmarks.py:
    python plot_benchmarks.py

Output: docs/figures/fig1_latency_vs_corpus_size.png
        docs/figures/fig2_index_time_vs_corpus_size.png
        docs/figures/fig3_percentile_comparison.png
        docs/figures/fig4_latency_distribution_boxplot.png
(each also saved as .pdf for direct inclusion in a LaTeX report)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR.parent / "docs"
RESULTS_CSV = DOCS_DIR / "results.csv"
RAW_LATENCIES_DIR = DOCS_DIR / "raw_latencies"
FIGURES_DIR = DOCS_DIR / "figures"

# Consistent store -> colour mapping across all 4 figures.
STORE_COLORS = {
    "Chroma": "#4C72B0",
    "FAISS": "#DD8452",
    "Qdrant": "#55A868",
}
STORE_ORDER = ["FAISS", "Chroma", "Qdrant"]

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": "--",
})


def load_results() -> list[dict]:
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(
            f"{RESULTS_CSV} not found — run run_all_benchmarks.py first."
        )
    with RESULTS_CSV.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in (
            "documents_indexed", "index_creation_s", "average_latency_ms",
            "stdev_latency_ms", "min_latency_ms", "p50_latency_ms",
            "p95_latency_ms", "p99_latency_ms", "max_latency_ms", "query_count",
        ):
            row[key] = float(row[key])
    return rows


def latest_per_store_and_size(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """If a benchmark was re-run (append-only CSV), keep only the most
    recent row per (store, corpus size) so re-runs don't duplicate points."""
    latest: dict[tuple[str, int], dict] = {}
    for row in rows:
        key = (row["store"], int(row["documents_indexed"]))
        if key not in latest or row["recorded_at"] > latest[key]["recorded_at"]:
            latest[key] = row
    return latest


def load_raw_latencies(store: str, documents_indexed: int) -> list[float] | None:
    path = RAW_LATENCIES_DIR / f"{store.lower()}_{documents_indexed}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["query_latencies_ms"]


def save_fig(fig, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / f"{name}.png", bbox_inches="tight")
    fig.savefig(FIGURES_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {FIGURES_DIR / name}.png (+ .pdf)")


def fig1_latency_vs_corpus_size(latest: dict[tuple[str, int], dict]) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for store in STORE_ORDER:
        points = sorted(
            (size, row["average_latency_ms"], row["stdev_latency_ms"])
            for (s, size), row in latest.items() if s == store
        )
        if not points:
            continue
        sizes = [p[0] for p in points]
        means = [p[1] for p in points]
        stdevs = [p[2] for p in points]
        ax.errorbar(
            sizes, means, yerr=stdevs, marker="o", capsize=4,
            label=store, color=STORE_COLORS.get(store), linewidth=2,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Corpus size (documents, log scale)")
    ax.set_ylabel("Average query latency (ms, log scale)")
    ax.set_title("Average query latency vs. corpus size")
    ax.legend(title="Vector store")
    save_fig(fig, "fig1_latency_vs_corpus_size")


def fig2_index_time_vs_corpus_size(latest: dict[tuple[str, int], dict]) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for store in STORE_ORDER:
        points = sorted(
            (size, row["index_creation_s"])
            for (s, size), row in latest.items() if s == store
        )
        if not points:
            continue
        sizes = [p[0] for p in points]
        times = [p[1] for p in points]
        ax.plot(
            sizes, times, marker="o", label=store,
            color=STORE_COLORS.get(store), linewidth=2,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Corpus size (documents, log scale)")
    ax.set_ylabel("Index build time (s, log scale)")
    ax.set_title("Index build time vs. corpus size")
    ax.legend(title="Vector store")
    save_fig(fig, "fig2_index_time_vs_corpus_size")


def fig3_percentile_comparison(latest: dict[tuple[str, int], dict]) -> None:
    corpus_sizes = sorted({size for (_, size) in latest})
    if not corpus_sizes:
        return
    target_size = corpus_sizes[-1]  # largest corpus available, most tail-revealing

    metrics = ["p50_latency_ms", "p95_latency_ms", "p99_latency_ms"]
    metric_labels = ["P50", "P95", "P99"]
    stores_present = [s for s in STORE_ORDER if (s, target_size) in latest]

    x = np.arange(len(metrics))
    width = 0.8 / max(len(stores_present), 1)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for i, store in enumerate(stores_present):
        row = latest[(store, target_size)]
        values = [row[m] for m in metrics]
        offset = (i - (len(stores_present) - 1) / 2) * width
        bars = ax.bar(
            x + offset, values, width, label=store,
            color=STORE_COLORS.get(store),
        )
        ax.bar_label(bars, fmt="%.2f", fontsize=8, padding=2)

    ax.set_yscale("log")
    ax.set_xticks(x, metric_labels)
    ax.set_ylabel("Latency (ms, log scale)")
    ax.set_title(f"P50 / P95 / P99 latency at {target_size} documents")
    ax.legend(title="Vector store", loc="upper left", bbox_to_anchor=(1.02, 1.0))
    fig.tight_layout()
    save_fig(fig, "fig3_percentile_comparison")


def fig4_latency_distribution_boxplot(latest: dict[tuple[str, int], dict]) -> None:
    corpus_sizes = sorted({size for (_, size) in latest})
    if not corpus_sizes:
        return
    target_size = corpus_sizes[-1]

    data, labels, colors = [], [], []
    for store in STORE_ORDER:
        if (store, target_size) not in latest:
            continue
        latencies = load_raw_latencies(store, target_size)
        if not latencies:
            continue
        data.append(latencies)
        labels.append(store)
        colors.append(STORE_COLORS.get(store))

    if not data:
        print("  fig4 skipped: no raw_latencies/*.json found "
              "(re-run run_all_benchmarks.py with the updated benchmark scripts)")
        return

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bplot = ax.boxplot(
        data, tick_labels=labels, showfliers=True, patch_artist=True,
        medianprops={"color": "black"},
    )
    for patch, color in zip(bplot["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_yscale("log")
    ax.set_ylabel("Query latency (ms, log scale)")
    ax.set_title(f"Latency distribution across all sampled queries ({target_size} documents)")
    save_fig(fig, "fig4_latency_distribution_boxplot")


def main() -> None:
    print(f"Reading {RESULTS_CSV} ...")
    rows = load_results()
    latest = latest_per_store_and_size(rows)
    print(f"Found {len(latest)} (store, corpus size) combinations.")
    print("Generating figures ...")
    fig1_latency_vs_corpus_size(latest)
    fig2_index_time_vs_corpus_size(latest)
    fig3_percentile_comparison(latest)
    fig4_latency_distribution_boxplot(latest)
    print(f"Done. Figures written to {FIGURES_DIR}")


if __name__ == "__main__":
    main()