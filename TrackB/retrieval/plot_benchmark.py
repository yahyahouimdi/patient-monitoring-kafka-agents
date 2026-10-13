"""Generates the report figures from the benchmark outputs produced by
run_all_benchmark.py:
    - docs/results.csv            (aggregated stats per store x corpus size x mode)
    - docs/raw_latencies/*.json   (every individual latency sample)

No numbers are invented here: if a store/corpus-size combination is missing
from results.csv, that line/bar is simply absent from the figure.

Run AFTER run_all_benchmark.py:
    python TrackB/retrieval/plot_benchmark.py

Output (each as .png and .pdf) in docs/figures/:
    fig1_latency_vs_corpus_size          unfiltered P50 with P95 whiskers
    fig2_index_time_vs_corpus_size
    fig3_percentile_comparison           largest corpus, unfiltered
    fig4_latency_distribution_boxplot    largest corpus, unfiltered
    fig5_filtered_latency_vs_corpus_size patient_id-filtered P50 with P95 whiskers
    fig6_retrieval_quality               Recall@k and cross-patient leakage
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR.parent / "docs"
RESULTS_CSV = DOCS_DIR / "results.csv"
RAW_LATENCIES_DIR = DOCS_DIR / "raw_latencies"
FIGURES_DIR = DOCS_DIR / "figures"

# Consistent store -> colour mapping across all figures.
STORE_COLORS = {
    "Chroma": "#4C72B0",
    "FAISS": "#DD8452",
    "Qdrant": "#55A868",
    "Qdrant-REST": "#8172B3",
}
STORE_ORDER = ["FAISS", "Chroma", "Qdrant", "Qdrant-REST"]
STORE_LABELS = {
    "FAISS": "FAISS (in-process, exact)",
    "Chroma": "Chroma (in-process, HNSW)",
    "Qdrant": "Qdrant (server, gRPC)",
    "Qdrant-REST": "Qdrant (server, REST)",
}
NUMERIC_COLUMNS = (
    "documents_indexed", "index_creation_s", "average_latency_ms",
    "stdev_latency_ms", "min_latency_ms", "p50_latency_ms",
    "p95_latency_ms", "p99_latency_ms", "max_latency_ms", "query_count",
    "recall_at_k", "ann_recall_vs_exact",
)

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

Key = tuple[str, int, str]  # (store, corpus size, mode)


def load_results() -> list[dict]:
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(
            f"{RESULTS_CSV} not found — run run_all_benchmark.py first."
        )
    with RESULTS_CSV.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in NUMERIC_COLUMNS:
            row[key] = float(row[key])
        leakage = row["cross_patient_leakage"]
        row["cross_patient_leakage"] = float(leakage) if leakage != "" else None
    return rows


def latest_per_key(rows: list[dict]) -> dict[Key, dict]:
    """If a benchmark was re-run (append-only CSV), keep only the most
    recent row per (store, corpus size, mode)."""
    latest: dict[Key, dict] = {}
    for row in rows:
        key = (row["store"], int(row["documents_indexed"]), row["mode"])
        if key not in latest or row["recorded_at"] > latest[key]["recorded_at"]:
            latest[key] = row
    return latest


def load_raw_latencies(store: str, documents_indexed: int, mode: str) -> list[float] | None:
    path = RAW_LATENCIES_DIR / f"{store.lower()}_{documents_indexed}_{mode}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["query_latencies_ms"]


def save_fig(fig, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / f"{name}.png", bbox_inches="tight")
    fig.savefig(FIGURES_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {FIGURES_DIR / name}.png (+ .pdf)")


def _largest_size(latest: dict[Key, dict]) -> int | None:
    sizes = sorted({size for (_, size, _) in latest})
    return sizes[-1] if sizes else None


def _latency_vs_size(latest: dict[Key, dict], mode: str, title: str, name: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for store in STORE_ORDER:
        points = sorted(
            (size, row["p50_latency_ms"], row["p95_latency_ms"])
            for (s, size, m), row in latest.items() if s == store and m == mode
        )
        if not points:
            continue
        sizes = [p[0] for p in points]
        p50 = np.array([p[1] for p in points])
        p95 = np.array([p[2] for p in points])
        ax.errorbar(
            sizes, p50, yerr=[np.zeros_like(p50), p95 - p50], marker="o", capsize=4,
            label=STORE_LABELS[store], color=STORE_COLORS[store], linewidth=2,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Corpus size (documents, log scale)")
    ax.set_ylabel("Query latency (ms, log scale)")
    ax.set_title(title)
    ax.legend(title="Median, whisker to P95", fontsize=9, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    save_fig(fig, name)


def fig2_index_time_vs_corpus_size(latest: dict[Key, dict]) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for store in STORE_ORDER:
        points = sorted(
            (size, row["index_creation_s"])
            for (s, size, m), row in latest.items() if s == store and m == "unfiltered"
        )
        if not points:
            continue
        ax.plot(
            [p[0] for p in points], [p[1] for p in points], marker="o",
            label=STORE_LABELS[store], color=STORE_COLORS[store], linewidth=2,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Corpus size (documents, log scale)")
    ax.set_ylabel("Index build time (s, log scale)")
    ax.set_title("Index build time vs. corpus size")
    ax.legend(fontsize=9)
    save_fig(fig, "fig2_index_time_vs_corpus_size")


def fig3_percentile_comparison(latest: dict[Key, dict]) -> None:
    target_size = _largest_size(latest)
    if target_size is None:
        return
    metrics = ["p50_latency_ms", "p95_latency_ms", "p99_latency_ms"]
    stores_present = [s for s in STORE_ORDER if (s, target_size, "unfiltered") in latest]

    x = np.arange(len(metrics))
    width = 0.8 / max(len(stores_present), 1)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for i, store in enumerate(stores_present):
        row = latest[(store, target_size, "unfiltered")]
        offset = (i - (len(stores_present) - 1) / 2) * width
        bars = ax.bar(
            x + offset, [row[m] for m in metrics], width,
            label=STORE_LABELS[store], color=STORE_COLORS[store],
        )
        ax.bar_label(bars, fmt="%.2f", fontsize=8, padding=2)

    ax.set_yscale("log")
    ax.set_xticks(x, ["P50", "P95", "P99"])
    ax.set_ylabel("Latency (ms, log scale)")
    ax.set_title(f"Unfiltered P50 / P95 / P99 latency at {target_size:,} documents")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=9)
    fig.tight_layout()
    save_fig(fig, "fig3_percentile_comparison")


def fig4_latency_distribution_boxplot(latest: dict[Key, dict]) -> None:
    target_size = _largest_size(latest)
    if target_size is None:
        return
    data, labels, colors = [], [], []
    for store in STORE_ORDER:
        latencies = load_raw_latencies(store, target_size, "unfiltered")
        if not latencies:
            continue
        data.append(latencies)
        labels.append(store)
        colors.append(STORE_COLORS[store])
    if not data:
        print("  fig4 skipped: no raw_latencies/*.json found")
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
    ax.set_title(f"Unfiltered latency distribution, all timed queries ({target_size:,} documents)")
    save_fig(fig, "fig4_latency_distribution_boxplot")


def fig6_retrieval_quality(latest: dict[Key, dict]) -> None:
    """Recall@k and cross-patient leakage for the patient-scoped use case,
    without and with the patient_id filter, at the largest corpus."""
    target_size = _largest_size(latest)
    if target_size is None:
        return
    stores_present = [s for s in STORE_ORDER if (s, target_size, "filtered") in latest]
    if not stores_present:
        print("  fig6 skipped: no filtered rows in results.csv")
        return

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    x = np.arange(len(stores_present))
    width = 0.38
    panels = [
        (axes[0], "recall_at_k", "Recall@3 (labelled relevant document found)"),
        (axes[1], "cross_patient_leakage", "Cross-patient leakage (share of results\nfrom another patient)"),
    ]
    for ax, metric, title in panels:
        for offset, mode, hatch in ((-width / 2, "unfiltered", "//"), (width / 2, "filtered", "")):
            values = [latest[(s, target_size, mode)][metric] or 0.0 for s in stores_present]
            bars = ax.bar(
                x + offset, values, width, hatch=hatch, edgecolor="white",
                color=[STORE_COLORS[s] for s in stores_present],
                alpha=0.55 if mode == "unfiltered" else 1.0,
            )
            ax.bar_label(bars, fmt="%.2f", fontsize=8, padding=2)
        ax.set_xticks(x, stores_present)
        ax.set_ylim(0, 1.12)
        ax.set_title(title, fontsize=10)
    axes[0].set_ylabel("Score (0-1)")
    fig.suptitle(
        f"Retrieval quality at {target_size:,} documents — hatched: no filter, solid: patient_id filter",
        fontsize=11,
    )
    fig.tight_layout()
    save_fig(fig, "fig6_retrieval_quality")


def main() -> None:
    print(f"Reading {RESULTS_CSV} ...")
    latest = latest_per_key(load_results())
    print(f"Found {len(latest)} (store, corpus size, mode) combinations.")
    print("Generating figures ...")
    _latency_vs_size(
        latest, "unfiltered", "Unfiltered query latency vs. corpus size",
        "fig1_latency_vs_corpus_size",
    )
    fig2_index_time_vs_corpus_size(latest)
    fig3_percentile_comparison(latest)
    fig4_latency_distribution_boxplot(latest)
    _latency_vs_size(
        latest, "filtered", "patient_id-filtered query latency vs. corpus size",
        "fig5_filtered_latency_vs_corpus_size",
    )
    fig6_retrieval_quality(latest)
    print(f"Done. Figures written to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
