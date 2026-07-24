"""
eval_framework_benchmark.py

RAGAS-only benchmark against THIS project's real data:
loader.py's load_documents() / load_queries() (patient_profiles.json +
medical_notes.json + queries/test_queries.json), using a local
embedding-based retriever and qwen2.5:3b (via Ollama) as the judge
model -- fully self-hosted, no OpenAI key needed.

This mirrors what Tier 2 will actually do: retrieve context, generate
a grounded answer with the local reasoning model, then score it.

Setup:
    ollama pull qwen2.5:3b
    ollama serve                      # if not already running
    pip install ragas sentence-transformers langchain-community \
                langchain-ollama requests --break-system-packages

Usage:
    python eval_framework_benchmark.py
    (run from the same directory as loader.py)

    IMPORTANT: do not name this file ragas.py (or json.py, requests.py,
    etc.) -- a script named the same as a package it imports will shadow
    that package, since Python checks the script's own directory before
    site-packages. This exact bug caused "cannot import name 'evaluate'
    from 'ragas'" earlier when this file was named ragas.py.

Output:
    results_eval_frameworks.csv -- one row per metric, appended.

Known limitation, note this in your write-up: test_queries.json's
"expected" field is a list of keyword phrases, not a full reference
answer. It's joined into a single string here to stand in for
ground_truth on the metrics that need one (context_precision,
context_recall) -- treat those specific scores as approximate, not
authoritative, and say so.

Also note: qwen2.5:3b is used as BOTH the answer-generator and the
judge model here, to stay fully self-hosted per the project's "no
external API" constraint. Using the same (small) model to grade its
own output is weaker evidence than an independent, larger judge --
flag this explicitly as a limitation in the report rather than
treating the scores as ground truth.

Fix vs. the original combined script: all four RAGAS metrics are now
scored in a SINGLE evaluate() call instead of one evaluate() call per
metric in a loop. Calling ragas.evaluate() repeatedly in one process
was causing internal event-loop reuse failures that ragas silently
swallowed and reported as nan (ragas's default RunConfig does not
raise on a metric failure -- it just records nan for that row). This
version also sets raise_exceptions=True so a real failure surfaces as
a traceback instead of a silent nan.
"""

import asyncio
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Windows' default ProactorEventLoop is incompatible with ragas's internal
# asyncio timeout handling (causes "RuntimeError: Timeout should be used
# inside a task" and silently nan's out every score). Must be set before
# any event loop is created, hence right after stdlib imports.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE = Path(__file__).parent
RETRIEVAL_DIR = BASE.parent / "retrieval"  # loader.py lives in the sibling retrieval/ folder
sys.path.insert(0, str(RETRIEVAL_DIR))

from loader import load_documents, load_queries  # noqa: E402

OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # same model used in the vector-store benchmark
TOP_K = 3

RESULTS_PATH = BASE / "results_eval_frameworks.csv"


def now():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Retrieval: reuse the same embedding model as the vector-store benchmark,
# in-memory, so this script doesn't depend on which store you ended up
# wiring into the real retrieval service.
# --------------------------------------------------------------------------

def build_retriever():
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model = SentenceTransformer(EMBEDDING_MODEL)
    docs = load_documents()
    texts = [d["text"] for d in docs]
    doc_embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

    def retrieve(query, k=TOP_K):
        q_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0]
        scores = doc_embeddings @ q_emb
        top_idx = np.argsort(-scores)[:k]
        return [texts[i] for i in top_idx], [docs[i]["id"] for i in top_idx]

    return retrieve


# --------------------------------------------------------------------------
# Generation: call qwen2.5:3b directly through Ollama's HTTP API, the same
# way Tier 2's reason_about() will eventually call the reasoning model.
# --------------------------------------------------------------------------

def generate_answer(query, contexts):
    context_block = "\n".join(f"- {c}" for c in contexts)
    prompt = (
        "Answer the question using only the context below. Be concise.\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {query}\nAnswer:"
    )
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


# --------------------------------------------------------------------------
# Build the evaluation dataset: for each test query, retrieve, generate,
# and package it as {question, contexts, answer, ground_truth}.
# --------------------------------------------------------------------------

def build_eval_cases():
    retrieve = build_retriever()
    queries = load_queries()

    cases = []
    skipped = 0
    for q in queries:
        question = q["query"]
        expected = q.get("expected", [])
        if not expected:
            # context_precision / context_recall need a non-empty ground_truth;
            # an empty one silently degrades those two metrics rather than
            # failing loudly, so drop these cases and say how many were dropped.
            skipped += 1
            continue
        contexts, doc_ids = retrieve(question)
        answer = generate_answer(question, contexts)
        ground_truth = "; ".join(expected)  # see limitation note above
        cases.append({
            "question": question,
            "contexts": contexts,
            "retrieved_ids": doc_ids,
            "answer": answer,
            "ground_truth": ground_truth,
        })
        print(f"  [{len(cases)}/{len(queries)}] {question!r} -> retrieved {doc_ids}")

    if skipped:
        print(f"  Skipped {skipped} quer{'y' if skipped == 1 else 'ies'} with empty "
              f"'expected' (no usable ground_truth for reference-based metrics).")
    return cases


# --------------------------------------------------------------------------
# RAGAS, judged by qwen2.5:3b via LangChain's Ollama wrapper.
# All four metrics are scored in a single evaluate() call -- calling
# evaluate() repeatedly in a loop (once per metric) is what caused the
# earlier silent nan failures.
# --------------------------------------------------------------------------

def run_ragas(cases):
    from datasets import Dataset
    from langchain_ollama import ChatOllama
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas import evaluate
    from ragas.run_config import RunConfig
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall

    judge_llm = LangchainLLMWrapper(ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL))
    judge_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=f"sentence-transformers/{EMBEDDING_MODEL}")
    )

    dataset = Dataset.from_list([
        {
            "question": c["question"],
            "contexts": c["contexts"],
            "answer": c["answer"],
            "ground_truth": c["ground_truth"],
        }
        for c in cases
    ])

    metric_specs = [
        ("faithfulness", faithfulness, False),
        ("answer_relevancy", answer_relevancy, False),
        ("context_precision", context_precision, True),
        ("context_recall", context_recall, True),
    ]
    metrics = [m for _, m, _ in metric_specs]

    start = time.perf_counter()
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
        # max_workers=1 runs serially -- a single local Ollama instance
        # won't handle concurrent judge calls well.
        run_config=RunConfig(max_workers=1),
        # raise_exceptions=True surfaces a real traceback instead of ragas's
        # default behaviour of writing nan and continuing silently.
        # (moved here from RunConfig -- current ragas puts it on evaluate()
        # itself, not on RunConfig.)
        raise_exceptions=True,
    )
    elapsed = time.perf_counter() - start

    df = result.to_pandas()
    rows = []
    for name, _, needs_ref in metric_specs:
        rows.append({
            "framework": "RAGAS", "metric": name, "requires_reference": needs_ref,
            "score": round(float(df[name].mean()), 4),
            "case_count": len(cases), "eval_time_s": round(elapsed, 4),
            "judge_model": OLLAMA_MODEL, "recorded_at": now(),
        })
    return rows


def append_rows(rows):
    file_exists = RESULTS_PATH.exists()
    with open(RESULTS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "framework", "metric", "requires_reference", "score",
            "case_count", "eval_time_s", "judge_model", "recorded_at",
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def check_ollama():
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(OLLAMA_MODEL in m for m in models):
            print(f"WARNING: {OLLAMA_MODEL} not found in `ollama list`. "
                  f"Run: ollama pull {OLLAMA_MODEL}")
    except requests.exceptions.RequestException:
        print(f"WARNING: could not reach Ollama at {OLLAMA_BASE_URL}. "
              f"Is `ollama serve` running?")


def main():
    check_ollama()

    print("Building retrieval + generation cases from the project's real "
          "knowledge base and test queries...")
    cases = build_eval_cases()

    if not cases:
        print("No usable cases (all queries had empty 'expected') -- nothing to evaluate.")
        return

    print("\nRunning RAGAS...")
    try:
        rows = run_ragas(cases)
    except Exception as e:
        print(f"  RAGAS run failed: {e}")
        raise

    if rows:
        append_rows(rows)
        print(f"\nRecorded {len(rows)} rows to {RESULTS_PATH.name}")
        for row in rows:
            print(f"  {row['framework']:10s} {row['metric']:22s} "
                  f"ref={row['requires_reference']!s:5s} score={row['score']} "
                  f"time={row['eval_time_s']}s")
    else:
        print("No results recorded -- check the errors above.")


if __name__ == "__main__":
    main()