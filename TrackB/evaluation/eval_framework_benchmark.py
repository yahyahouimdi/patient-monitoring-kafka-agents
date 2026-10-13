"""
eval_framework_benchmark.py

RAGAS vs DeepEval on THIS project's real data, with the same cases and the
same local judge.

Data sources:
    retrieval/loader.py
        - patient_profiles.json
        - medical_notes.json
        - queries/test_queries.json

Pipeline:
    1. Load the project's real documents and test queries.
    2. Retrieve top-K documents using all-MiniLM-L6-v2 (in-memory cosine
       search; this evaluates the embedding retrieval, not the Qdrant
       service or its patient filter).
    3. Generate an answer using qwen2.5:3b through Ollama.
    4. Score the same cases with RAGAS and with DeepEval, one metric at a
       time, timing each metric.
    5. Write results_eval_frameworks.csv (one row per framework x metric)
       and results_eval_cases.csv (one row per framework x metric x case).

Reporting rule:
    A case the judge model cannot score is reported as failed
    (valid_cases < case_count). Scores are averaged over valid cases only
    and are never filled in from another framework or by hand.

The entire evaluation is local:
    - Embeddings: sentence-transformers
    - Answer generation: Ollama / qwen2.5:3b
    - Judge (both frameworks): Ollama / qwen2.5:3b

No OpenAI API key is required.

Known limitations:
    - test_queries.json "expected" is a list of keywords/phrases rather
      than a complete reference answer. The phrases are joined into one
      reference string, so the reference-based metrics (context precision
      and recall) are approximate indicators.
    - qwen2.5:3b both generates the answer and judges it. That keeps the
      experiment self-hosted but is weaker than an independent, larger
      judge.
    - Seven cases: the scores are a smoke-level comparison, not a
      statistically meaningful ranking of the two frameworks.

Windows:
    WindowsSelectorEventLoopPolicy is configured before RAGAS is imported
    to avoid asyncio timeout/event-loop problems.

Usage (Ollama running, model pulled):

    python TrackB/evaluation/eval_framework_benchmark.py
    python TrackB/evaluation/eval_framework_benchmark.py --frameworks deepeval
"""

# ============================================================================
# Standard library
# ============================================================================

import asyncio
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# Windows asyncio compatibility
# ============================================================================
#
# This MUST happen before RAGAS creates/uses an asyncio event loop.
#

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )


# ============================================================================
# Third-party imports
# ============================================================================

import numpy as np
import requests


# ============================================================================
# Project paths
# ============================================================================

BASE = Path(__file__).resolve().parent
TRACKB_DIR = BASE.parent

# TrackB/
#   retrieval/
#       loader.py
#   evaluation/
#       eval_framework_benchmark.py
#
# Adding TrackB/ allows:
#
#     from retrieval.loader import ...
#
sys.path.insert(0, str(TRACKB_DIR))


from retrieval.loader import load_documents, load_queries  # noqa: E402


# ============================================================================
# Configuration
# ============================================================================

OLLAMA_MODEL = "qwen2.5:3b"

# Ollama's normal API
OLLAMA_BASE_URL = "http://localhost:11434"

# Ollama's OpenAI-compatible API.
# RAGAS llm_factory() can use this interface.
OLLAMA_OPENAI_URL = "http://localhost:11434/v1"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

TOP_K = 3

RESULTS_PATH = BASE / "results_eval_frameworks.csv"
CASE_RESULTS_PATH = BASE / "results_eval_cases.csv"

# Upper bound for one judge request / one RAGAS job, in seconds.
METRIC_CASE_TIMEOUT_S = 180


# ============================================================================
# Utilities
# ============================================================================

def now():
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Retrieval
# ============================================================================

def build_retriever():
    """
    Build an in-memory embedding retriever.

    The same embedding model used by the vector-store benchmark is used:

        all-MiniLM-L6-v2

    Returns:
        retrieve(query, k=TOP_K)

    which returns:

        contexts, document_ids
    """

    from sentence_transformers import SentenceTransformer

    print(f"Loading embedding model: {EMBEDDING_MODEL}")

    model = SentenceTransformer(EMBEDDING_MODEL)

    docs = load_documents()

    if not docs:
        raise RuntimeError("load_documents() returned no documents.")

    texts = [d["text"] for d in docs]

    print(f"Loaded {len(texts)} documents.")

    print("Computing document embeddings...")

    doc_embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    def retrieve(query, k=TOP_K):
        """
        Retrieve the top-k most similar documents using cosine similarity.
        """

        q_emb = model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]

        scores = doc_embeddings @ q_emb

        top_idx = np.argsort(-scores)[:k]

        contexts = [texts[i] for i in top_idx]
        doc_ids = [docs[i]["id"] for i in top_idx]

        return contexts, doc_ids

    return retrieve


# ============================================================================
# Ollama answer generation
# ============================================================================

def generate_answer(query, contexts):
    """
    Generate a grounded answer using qwen2.5:3b through Ollama.
    """

    context_block = "\n".join(
        f"- {context}"
        for context in contexts
    )

    prompt = (
        "You are a medical information assistant evaluating a retrieval "
        "system.\n\n"
        "Answer the question using ONLY the context below.\n"
        "Do not invent information that is not present in the context.\n"
        "If the context does not contain enough information, say so.\n"
        "Be concise.\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {query}\n\n"
        "Answer:"
    )

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
            },
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    answer = data.get("response", "").strip()

    if not answer:
        raise RuntimeError(
            f"Ollama returned an empty answer for query: {query!r}"
        )

    return answer


# ============================================================================
# Build evaluation cases
# ============================================================================

def build_eval_cases():
    """
    Build the RAGAS evaluation dataset.

    Each case contains:

        question
        contexts
        retrieved_ids
        answer
        ground_truth
    """

    retrieve = build_retriever()

    queries = load_queries()

    if not queries:
        raise RuntimeError("load_queries() returned no queries.")

    print(f"Loaded {len(queries)} test queries.")

    cases = []
    skipped = 0

    for q in queries:

        question = q["query"]

        expected = q.get("expected", [])

        # Reference-based metrics require a usable reference.
        if not expected:
            skipped += 1
            continue

        contexts, doc_ids = retrieve(question)

        answer = generate_answer(
            question,
            contexts,
        )

        # IMPORTANT:
        #
        # The project's expected field is a list of keywords/phrases,
        # not a complete reference answer.
        #
        # We therefore join them into one string.
        #
        ground_truth = "; ".join(expected)

        cases.append(
            {
                "question": question,
                "contexts": contexts,
                "retrieved_ids": doc_ids,
                "answer": answer,
                "ground_truth": ground_truth,
            }
        )

        print(
            f"  [{len(cases)}/{len(queries)}] "
            f"{question!r} "
            f"-> retrieved {doc_ids}"
        )

        print(f"      Answer: {answer}")

    if skipped:
        print(
            f"\nSkipped {skipped} quer"
            f"{'y' if skipped == 1 else 'ies'} "
            "with empty 'expected'."
        )

    return cases


# ============================================================================
# RAGAS
# ============================================================================

def run_ragas(cases):
    """
    Evaluate all four RAGAS metrics. Returns (summary_rows, case_rows).

    Compatible with the current RAGAS 0.4.3 environment.

    Uses:
        - qwen2.5:3b via Ollama as the RAGAS judge
        - sentence-transformers/all-MiniLM-L6-v2 for AnswerRelevancy
        - legacy RAGAS metric objects because evaluate() expects
          the legacy Metric interface
    """

    # ------------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------------

    from datasets import Dataset
    from openai import OpenAI

    import ragas

    from ragas import evaluate
    from ragas.llms import llm_factory

    # IMPORTANT:
    # These are the legacy metric objects expected by ragas.evaluate()
    # in this RAGAS 0.4.3 setup.
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )

    # ------------------------------------------------------------------------
    # Print diagnostic information
    # ------------------------------------------------------------------------

    print(f"\nRAGAS version: {ragas.__version__}")
    print(f"RAGAS location: {ragas.__file__}")

    # ------------------------------------------------------------------------
    # Build Ollama OpenAI-compatible client
    # ------------------------------------------------------------------------

    print("\nConnecting RAGAS judge to Ollama...")

    ollama_client = OpenAI(
        api_key="ollama",
        base_url=OLLAMA_OPENAI_URL,
    )

    # ------------------------------------------------------------------------
    # Build RAGAS LLM
    # ------------------------------------------------------------------------

    judge_llm = llm_factory(
        OLLAMA_MODEL,
        provider="openai",
        client=ollama_client,
    )

    print(
        f"RAGAS judge configured: "
        f"{OLLAMA_MODEL} via Ollama"
    )

    # ------------------------------------------------------------------------
    # Build RAGAS embeddings
    # ------------------------------------------------------------------------
    #
    # The legacy AnswerRelevancy metric calls the LangChain-style
    # embed_query / embed_documents interface. RAGAS 0.4.3's own
    # HuggingFaceEmbeddings class does not provide it (every case failed
    # with AttributeError: no attribute 'embed_query'), so the same
    # sentence-transformers model is exposed through that interface here.
    # ------------------------------------------------------------------------

    from ragas.embeddings import BaseRagasEmbeddings
    from sentence_transformers import SentenceTransformer

    class SentenceTransformerEmbeddings(BaseRagasEmbeddings):
        def __init__(self, model_name):
            super().__init__()
            self._model = SentenceTransformer(model_name)

        def embed_query(self, text):
            return self._model.encode([text], normalize_embeddings=True)[0].tolist()

        def embed_documents(self, texts):
            return self._model.encode(list(texts), normalize_embeddings=True).tolist()

        async def aembed_query(self, text):
            return self.embed_query(text)

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

    ragas_embeddings = SentenceTransformerEmbeddings(EMBEDDING_MODEL)

    # ------------------------------------------------------------------------
    # Configure legacy RAGAS metrics
    # ------------------------------------------------------------------------
    #
    # These metric objects are the ones accepted by ragas.evaluate()
    # in this environment.
    #
    # We explicitly attach the LLM and embeddings to the metrics.
    # ------------------------------------------------------------------------

    faithfulness.llm = judge_llm

    answer_relevancy.llm = judge_llm
    answer_relevancy.embeddings = ragas_embeddings

    context_precision.llm = judge_llm
    context_recall.llm = judge_llm

    # ------------------------------------------------------------------------
    # Prepare dataset
    # ------------------------------------------------------------------------
    #
    # RAGAS expects these fields for the metrics we are evaluating:
    #
    #   user_input
    #   retrieved_contexts
    #   response
    #   reference
    #
    # Your benchmark cases use:
    #
    #   question
    #   contexts
    #   answer
    #   ground_truth
    #
    # Therefore we explicitly map them here.
    # ------------------------------------------------------------------------

    dataset_rows = []

    for case in cases:
        dataset_rows.append(
            {
                "user_input": case["question"],
                "retrieved_contexts": case["contexts"],
                "response": case["answer"],
                "reference": case["ground_truth"],
            }
        )

    dataset = Dataset.from_list(dataset_rows)

    print(
        f"\nPrepared RAGAS dataset with "
        f"{len(dataset_rows)} cases."
    )

    # ------------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------------

    metric_specs = [
        ("faithfulness", faithfulness, False),
        ("answer_relevancy", answer_relevancy, False),
        ("context_precision", context_precision, True),
        ("context_recall", context_recall, True),
    ]

    # ------------------------------------------------------------------------
    # Evaluate, one metric at a time
    # ------------------------------------------------------------------------
    #
    # Each metric gets its own evaluate() call so that its wall-clock time
    # is its own (DeepEval is timed the same way below).
    #
    # raise_exceptions=False: a case the judge cannot score comes back as
    # NaN. NaN cases are COUNTED and reported (valid_cases), never replaced
    # and never averaged over. A metric with zero valid cases is recorded
    # with an empty score.
    # ------------------------------------------------------------------------

    from ragas.run_config import RunConfig

    print(f"\nRunning RAGAS evaluation with {OLLAMA_MODEL} as the judge...\n")

    rows = []
    case_rows = []

    for name, metric, needs_ref in metric_specs:
        start = time.perf_counter()
        result = evaluate(
            dataset,
            metrics=[metric],
            # Serial execution: one local Ollama instance, one request at a time.
            run_config=RunConfig(max_workers=1, timeout=METRIC_CASE_TIMEOUT_S),
            raise_exceptions=False,
        )
        elapsed = time.perf_counter() - start

        df = result.to_pandas()
        values = [
            None if value is None or np.isnan(value) else float(value)
            for value in (df[name].tolist() if name in df.columns else [None] * len(cases))
        ]
        rows.append(_summary_row("RAGAS", name, needs_ref, values, elapsed))
        case_rows.extend(_case_rows("RAGAS", name, cases, values))
        print(f"  RAGAS {name}: {values} ({elapsed:.1f}s)")

    return rows, case_rows


# ============================================================================
# DeepEval
# ============================================================================

class OllamaJudge:
    """Minimal DeepEvalBaseLLM-compatible wrapper around a local Ollama
    model (DeepEval's documented pattern for a non-OpenAI judge)."""

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
                # Constrain decoding to valid JSON: small models fail
                # free-form "output JSON" instructions far more often.
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=METRIC_CASE_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self):
        return f"ollama/{self.model_name}"


def run_deepeval(cases):
    """
    Evaluate the same four metrics with DeepEval, same cases, same judge.

    Each case is measured on its own so that one unparseable judge answer
    costs one case, not the whole metric. Failed cases are counted and
    reported (valid_cases), exactly like the RAGAS NaN cases.
    """

    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
    )
    from deepeval.models.base_model import DeepEvalBaseLLM
    from deepeval.test_case import LLMTestCase

    import deepeval

    print(f"\nDeepEval version: {deepeval.__version__}")

    JudgeModel = type("JudgeModel", (OllamaJudge, DeepEvalBaseLLM), {})
    judge = JudgeModel()

    test_cases = [
        LLMTestCase(
            input=case["question"],
            actual_output=case["answer"],
            retrieval_context=case["contexts"],
            expected_output=case["ground_truth"],
        )
        for case in cases
    ]

    metric_specs = [
        ("faithfulness", FaithfulnessMetric, False),
        ("answer_relevancy", AnswerRelevancyMetric, False),
        ("contextual_precision", ContextualPrecisionMetric, True),
        ("contextual_recall", ContextualRecallMetric, True),
    ]

    rows = []
    case_rows = []

    for name, metric_class, needs_ref in metric_specs:
        start = time.perf_counter()
        values = []
        for test_case in test_cases:
            metric = metric_class(model=judge, async_mode=False, include_reason=False)
            try:
                metric.measure(test_case, _show_indicator=False)
                values.append(None if metric.score is None else float(metric.score))
            except Exception as exc:  # judge output the metric could not parse
                print(f"    DeepEval {name} case failed: {type(exc).__name__}: {str(exc)[:120]}")
                values.append(None)
        elapsed = time.perf_counter() - start

        rows.append(_summary_row("DeepEval", name, needs_ref, values, elapsed))
        case_rows.extend(_case_rows("DeepEval", name, cases, values))
        print(f"  DeepEval {name}: {values} ({elapsed:.1f}s)")

    return rows, case_rows


# ============================================================================
# Result rows
# ============================================================================

def _summary_row(framework, metric, needs_ref, values, elapsed):
    valid = [value for value in values if value is not None]
    return {
        "framework": framework,
        "metric": metric,
        "requires_reference": needs_ref,
        "score": round(sum(valid) / len(valid), 4) if valid else "",
        "valid_cases": len(valid),
        "case_count": len(values),
        "eval_time_s": round(elapsed, 2),
        "judge_model": OLLAMA_MODEL,
        "recorded_at": now(),
    }


def _case_rows(framework, metric, cases, values):
    return [
        {
            "framework": framework,
            "metric": metric,
            "case": index + 1,
            "question": case["question"],
            "score": "" if value is None else round(value, 4),
        }
        for index, (case, value) in enumerate(zip(cases, values))
    ]


def write_csv(path, rows):
    """Overwrite: one run is one results file, so rows from different runs
    (or different judge set-ups) can never be mixed."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# ============================================================================
# Ollama health check
# ============================================================================

def check_ollama():
    """
    Check that Ollama is reachable and qwen2.5:3b exists.
    """

    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"\nERROR: Could not reach Ollama at {OLLAMA_BASE_URL}")
        print("Make sure Ollama is running:\n    ollama serve")
        print(f"\nDetails: {exc}")
        return False

    models = [model["name"] for model in response.json().get("models", [])]
    matching_models = [model for model in models if model.startswith(OLLAMA_MODEL)]
    if not matching_models:
        print(f"\nWARNING: {OLLAMA_MODEL} was not found in Ollama.")
        print(f"Run:\n    ollama pull {OLLAMA_MODEL}\n")
        return False

    print(f"Ollama OK: {matching_models[0]}")
    return True


# ============================================================================
# Main
# ============================================================================

RUNNERS = {
    "ragas": ("RAGAS", run_ragas),
    "deepeval": ("DeepEval", run_deepeval),
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RAGAS vs DeepEval on the project's knowledge base.")
    parser.add_argument("--frameworks", nargs="+", default=list(RUNNERS), choices=list(RUNNERS))
    args = parser.parse_args()

    print("=" * 70)
    print("TrackB evaluation-framework benchmark: RAGAS vs DeepEval")
    print("=" * 70)

    if not check_ollama():
        raise SystemExit("\nOllama is unavailable. Start Ollama and make sure the model exists.")

    print("\nBuilding retrieval + generation cases from the project's real knowledge base...")
    cases = build_eval_cases()
    if not cases:
        print("\nNo usable cases. All queries may have empty 'expected' fields.")
        return

    summary_rows = []
    case_rows = []

    for key in args.frameworks:
        label, runner = RUNNERS[key]
        print("\n" + "=" * 70)
        print(f"Running {label}")
        print("=" * 70)
        try:
            rows, per_case = runner(cases)
        except Exception as exc:
            # A framework that cannot run at all is a result too: record it
            # as zero valid cases instead of leaving a gap someone might
            # later fill in by hand.
            print(f"\n{label} could not run: {type(exc).__name__}: {exc}")
            rows = [{
                "framework": label,
                "metric": f"(framework failed: {type(exc).__name__})",
                "requires_reference": "",
                "score": "",
                "valid_cases": 0,
                "case_count": len(cases),
                "eval_time_s": "",
                "judge_model": OLLAMA_MODEL,
                "recorded_at": now(),
            }]
            per_case = []
        summary_rows.extend(rows)
        case_rows.extend(per_case)

    write_csv(RESULTS_PATH, summary_rows)
    if case_rows:
        write_csv(CASE_RESULTS_PATH, case_rows)

    print(f"\nRecorded {len(summary_rows)} rows to:\n    {RESULTS_PATH}")
    print("\nResults:")
    for row in summary_rows:
        score = f"{row['score']:.4f}" if row["score"] != "" else "  n/a "
        elapsed = f"{row['eval_time_s']:.1f}s" if row["eval_time_s"] != "" else "n/a"
        print(
            f"  {row['framework']:8s} {row['metric']:22s} score={score} "
            f"valid={row['valid_cases']}/{row['case_count']} time={elapsed}"
        )


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    main()
