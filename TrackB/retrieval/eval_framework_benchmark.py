"""
eval_framework_benchmark.py

Benchmarks RAGAS and DeepEval against THIS project's real data:
loader.py's load_documents() / load_queries() (patient_profiles.json +
medical_notes.json + queries/test_queries.json), using a local
embedding-based retriever and qwen2.5:3b (via Ollama) as the judge
model for both frameworks -- fully self-hosted, no OpenAI key needed.

This mirrors what Tier 2 will actually do: retrieve context, generate
a grounded answer with the local reasoning model, then score it.

Setup:
    ollama pull qwen2.5:3b
    ollama serve                      # if not already running
    pip install ragas deepeval sentence-transformers \
                langchain-community langchain-ollama requests --break-system-packages

Usage:
    python eval_framework_benchmark.py
    (run from the same directory as loader.py)

Output:
    results_eval_frameworks.csv -- one row per (framework, metric),
    appended, in the same measured-run style as the vector-store
    benchmark (results.csv).

Known limitation, note this in your write-up: test_queries.json's
"expected" field is a list of keyword phrases, not a full reference
answer. It's joined into a single string here to stand in for
ground_truth on the metrics that need one (context_precision,
context_recall, contextual_precision, contextual_recall) -- treat
those specific scores as approximate, not authoritative, and say so.

Also note: qwen2.5:3b is used as BOTH the answer-generator and the
judge model here, to stay fully self-hosted per the project's "no
external API" constraint. Using the same (small) model to grade its
own output is weaker evidence than an independent, larger judge --
flag this explicitly as a limitation in the report rather than
treating the scores as ground truth.
"""

import csv
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))  # so `from loader import ...` finds loader.py next to this file

from loader import load_documents, load_queries  # noqa: E402

OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # same model used in the vector-store benchmark
TOP_K = 3
OLLAMA_TIMEOUT_S = 600  # local generation has been observed taking 8-9 min/case;
                        # 120s was too aggressive and produced silent ReadTimeouts

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
        timeout=OLLAMA_TIMEOUT_S,
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
    queries = queries[:2]  # limit to 2 for speed; remove this line to run all queries

    cases = []
    for q in queries:
        question = q["query"]
        contexts, doc_ids = retrieve(question)
        answer = generate_answer(question, contexts)
        ground_truth = "; ".join(q.get("expected", []))  # see limitation note above
        cases.append({
            "question": question,
            "contexts": contexts,
            "retrieved_ids": doc_ids,
            "answer": answer,
            "ground_truth": ground_truth,
        })
        print(f"  [{len(cases)}/{len(queries)}] {question!r} -> retrieved {doc_ids}")
    return cases


# --------------------------------------------------------------------------
# RAGAS, judged by qwen2.5:3b via LangChain's Ollama wrapper.
# --------------------------------------------------------------------------

def run_ragas(cases):
    from datasets import Dataset
    from langchain_ollama import ChatOllama
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas import evaluate
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
        #("answer_relevancy", answer_relevancy, False),
        #("context_precision", context_precision, True),
        #("context_recall", context_recall, True),
    ]

    rows = []
    for name, metric_fn, needs_ref in metric_specs:
        metric_fn.llm = judge_llm
        if hasattr(metric_fn, "embeddings"):
            metric_fn.embeddings = judge_embeddings

        start = time.perf_counter()
        result = evaluate(dataset, metrics=[metric_fn], llm=judge_llm, embeddings=judge_embeddings)
        elapsed = time.perf_counter() - start

        df = result.to_pandas()
        avg_score = float(df[name].mean())
        rows.append({
            "framework": "RAGAS", "metric": name, "requires_reference": needs_ref,
            "score": round(avg_score, 4), "case_count": len(cases),
            "eval_time_s": round(elapsed, 4), "judge_model": OLLAMA_MODEL,
            "recorded_at": now(),
        })
    return rows


# --------------------------------------------------------------------------
# DeepEval, judged by qwen2.5:3b through a small custom local-model wrapper
# (DeepEval's documented pattern for plugging in a non-OpenAI judge).
# --------------------------------------------------------------------------

class OllamaJudge:
    """Minimal DeepEvalBaseLLM-compatible wrapper around a local Ollama model."""

    def __init__(self, model_name=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL):
        self.model_name = model_name
        self.base_url = base_url

    def load_model(self):
        return self.model_name

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",  # forces syntactically valid JSON; DeepEval's
                                    # internal prompts already ask for JSON output
            },
            timeout=OLLAMA_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    
    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self):
        return f"ollama/{self.model_name}"


def run_deepeval(cases):
    from deepeval.models.base_model import DeepEvalBaseLLM
    from deepeval import evaluate as deepeval_evaluate
    from deepeval.metrics import (
        FaithfulnessMetric, AnswerRelevancyMetric,
        ContextualPrecisionMetric, ContextualRecallMetric,
    )
    from deepeval.test_case import LLMTestCase

    # Bind our judge to DeepEval's expected base class at runtime, so this
    # file doesn't hard-fail if DeepEvalBaseLLM's exact interface shifts
    # between versions -- adjust OllamaJudge above if this raises.
    JudgeModel = type("JudgeModel", (OllamaJudge, DeepEvalBaseLLM), {})
    judge = JudgeModel()

    test_cases = [
        LLMTestCase(
            input=c["question"], actual_output=c["answer"],
            retrieval_context=c["contexts"], expected_output=c["ground_truth"],
        )
        for c in cases
    ]

    metric_specs = [
        ("faithfulness", FaithfulnessMetric(model=judge), False),
        ("answer_relevancy", AnswerRelevancyMetric(model=judge), False),
        ("contextual_precision", ContextualPrecisionMetric(model=judge), True),
        ("contextual_recall", ContextualRecallMetric(model=judge), True),
    ]

    rows = []
    for name, metric, needs_ref in metric_specs:
        start = time.perf_counter()
        result = deepeval_evaluate(test_cases, [metric])
        elapsed = time.perf_counter() - start

        scores = [r.metrics_data[0].score for r in result.test_results if r.metrics_data]
        avg_score = sum(scores) / len(scores) if scores else None
        rows.append({
            "framework": "DeepEval", "metric": name, "requires_reference": needs_ref,
            "score": round(avg_score, 4) if avg_score is not None else "n/a",
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

    all_rows = []

    print("\nRunning RAGAS...")
    try:
        all_rows.extend(run_ragas(cases))
    except Exception:
        print("  RAGAS run failed:")
        traceback.print_exc()

    print("Running DeepEval...")
    try:
        all_rows.extend(run_deepeval(cases))
    except Exception:
        print("  DeepEval run failed:")
        traceback.print_exc()

    if all_rows:
        append_rows(all_rows)
        print(f"\nRecorded {len(all_rows)} rows to {RESULTS_PATH.name}")
        for row in all_rows:
            print(f"  {row['framework']:10s} {row['metric']:22s} "
                  f"ref={row['requires_reference']!s:5s} score={row['score']} "
                  f"time={row['eval_time_s']}s")
    else:
        print("No results recorded -- check the errors above.")


if __name__ == "__main__":
    main()