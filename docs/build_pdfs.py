"""Rebuild the report PDFs from their Markdown sources, so a PDF can never
carry numbers that the Markdown (and the result files behind it) no longer
has.

    TrackB/docs/appendix_A.pdf                <- TrackB/docs/appendix_A.md
    docs/vectordb_benchmark.pdf               <- experiment_protocol.md + appendix_A.md + figures
    docs/evaluation_framework_benchmark.pdf   <- TrackB/evaluation/README.md

Usage (from the repository root):
    python docs/build_pdfs.py

Needs markdown-it-py and a Chromium-based browser for printing (Microsoft
Edge or Chrome; set PDF_BROWSER to its path if it is not found).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
TRACKB_DOCS = ROOT / "TrackB" / "docs"
FIGURES = [
    ("Unfiltered query latency vs. corpus size", "fig1_latency_vs_corpus_size.png"),
    ("patient_id-filtered query latency vs. corpus size", "fig5_filtered_latency_vs_corpus_size.png"),
    ("Retrieval quality with and without the filter", "fig6_retrieval_quality.png"),
    ("Index build time vs. corpus size", "fig2_index_time_vs_corpus_size.png"),
    ("Latency percentiles at the largest corpus", "fig3_percentile_comparison.png"),
    ("Latency distribution at the largest corpus", "fig4_latency_distribution_boxplot.png"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 19pt; margin: 0 0 10pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ccc; padding-bottom: 3pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; }
th, td { border: 1px solid #bbb; padding: 3pt 6pt; }
th { background: #f0f0f0; }
tr { break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f4f4f4; padding: 0 2pt; }
pre { background: #f4f4f4; padding: 6pt; font-size: 9pt; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
img { max-width: 100%; }
figure { margin: 12pt 0; break-inside: avoid; text-align: center; }
figcaption { font-size: 9pt; color: #444; }
.section-break { break-before: page; }
"""


def find_browser() -> str:
    candidates = [
        os.environ.get("PDF_BROWSER"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge"), shutil.which("chrome"), shutil.which("chromium"),
        shutil.which("google-chrome"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("No Chromium-based browser found. Set PDF_BROWSER to msedge.exe or chrome.exe.")


def render_markdown(path: Path) -> str:
    return MarkdownIt("commonmark").enable("table").render(path.read_text(encoding="utf-8"))


def figures_html() -> str:
    parts = ['<h2 class="section-break">Figures</h2>']
    for caption, name in FIGURES:
        figure = TRACKB_DOCS / "figures" / name
        if figure.exists():
            parts.append(f'<figure><img src="{figure.as_uri()}"><figcaption>{caption}</figcaption></figure>')
    return "\n".join(parts)


def write_pdf(browser: str, body_html: str, title: str, output: Path) -> None:
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{CSS}</style></head><body>{body_html}</body></html>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                f"--user-data-dir={Path(tmp) / 'profile'}",
                f"--print-to-pdf={output}", page.as_uri(),
            ],
            check=True, capture_output=True, timeout=120,
        )
    if not output.exists() or output.stat().st_size == 0:
        raise SystemExit(f"Browser did not produce {output}")
    print(f"wrote {output.relative_to(ROOT)} ({output.stat().st_size // 1024} KB)")


def main() -> None:
    browser = find_browser()
    appendix = render_markdown(TRACKB_DOCS / "appendix_A.md")
    protocol = render_markdown(TRACKB_DOCS / "experiment_protocol.md")
    evaluation = render_markdown(ROOT / "TrackB" / "evaluation" / "README.md")

    write_pdf(browser, appendix, "Appendix A. Retrieval Benchmark Comparison", TRACKB_DOCS / "appendix_A.pdf")
    write_pdf(
        browser,
        appendix + f'<div class="section-break">{protocol}</div>' + figures_html(),
        "Vector-Store Benchmark",
        ROOT / "docs" / "vectordb_benchmark.pdf",
    )
    write_pdf(
        browser, evaluation, "Evaluation-Framework Benchmark",
        ROOT / "docs" / "evaluation_framework_benchmark.pdf",
    )


if __name__ == "__main__":
    sys.exit(main())
