"""
eval_framework_benchmark.py

RAGAS benchmark against THIS project's real data.

Data sources:
    retrieval/loader.py
        - patient_profiles.json
        - medical_notes.json
        - queries/test_queries.json

Pipeline:
    1. Load the project's real documents and test queries.
    2. Retrieve top-K documents using all-MiniLM-L6-v2.
    3. Generate an answer using qwen2.5:3b through Ollama.
    4. Evaluate the generated RAG answers with RAGAS.
    5. Save one CSV row per metric.

The entire evaluation is local:
    - Embeddings: sentence-transformers
    - Answer generation: Ollama / qwen2.5:3b
    - RAGAS judge: Ollama / qwen2.5:3b

No OpenAI API key is required.

IMPORTANT:
    RAGAS 0.4.x uses the newer llm_factory() API.
    Do not use the old LangchainLLMWrapper /
    LangchainEmbeddingsWrapper integration here.

Known limitation:
    test_queries.json "expected" is a list of keywords/phrases rather
    than a complete reference answer. We join those phrases into one
    reference string for reference-based metrics. Therefore:
        - context_precision
        - context_recall

    should be treated as approximate indicators rather than authoritative
    ground-truth measurements.

Another limitation:
    qwen2.5:3b is used both to generate the answer and to judge it.
    This is useful for a fully self-hosted experiment but is weaker than
    using an independent, larger judge model.

Windows:
    WindowsSelectorEventLoopPolicy is configured before RAGAS is imported
    to avoid asyncio timeout/event-loop problems.

Usage:

    Make sure Ollama is running:

        ollama serve

    Make sure the model exists:

        ollama pull qwen2.5:3b

    Then:

        python eval_framework_benchmark.py
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

from sklearn import metrics


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
    Evaluate all four RAGAS metrics.

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
    from ragas.embeddings import HuggingFaceEmbeddings

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
    # IMPORTANT:
    # Do NOT use OllamaEmbeddings here.
    #
    # RAGAS 0.4.3 Collections/modern embedding validation rejects the
    # LangChain OllamaEmbeddings object.
    #
    # The legacy AnswerRelevancy metric can use this RAGAS-native
    # HuggingFace embedding implementation.
    # ------------------------------------------------------------------------

    ragas_embeddings = HuggingFaceEmbeddings(
        model="sentence-transformers/all-MiniLM-L6-v2"
    )

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
        (
            "faithfulness",
            faithfulness,
            False,
        ),
        (
            "answer_relevancy",
            answer_relevancy,
            False,
        ),
        (
            "context_precision",
            context_precision,
            True,
        ),
        (
            "context_recall",
            context_recall,
            True,
        ),
    ]

    metrics = [
        metric
        for _, metric, _ in metric_specs
    ]

    # ------------------------------------------------------------------------
    # Diagnostic information
    # ------------------------------------------------------------------------

    print("\nDEBUG METRICS:")

    for name, metric, needs_reference in metric_specs:
        print(
            f"  {name}: "
            f"{type(metric)} | "
            f"reference={needs_reference}"
        )

    # ------------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------------

    print("\nRunning RAGAS evaluation...")
    print(
        f"This uses {OLLAMA_MODEL} as the judge."
    )
    print(
        "Ollama must remain running during evaluation.\n"
    )

    start = time.perf_counter()

    result = evaluate(
        dataset,
        metrics=metrics,

        # Serial execution is intentional.
        #
        # We are using one local Ollama/Qwen instance.
        # This avoids sending multiple simultaneous requests
        # to the local judge and makes the benchmark more reproducible.
        run_config=__import__(
            "ragas.run_config",
            fromlist=["RunConfig"],
        ).RunConfig(
            max_workers=1,
        ),

        # Raise the actual metric exception instead of silently
        # converting failures into NaN values.
        raise_exceptions=True,
    )

    elapsed = time.perf_counter() - start

    # ------------------------------------------------------------------------
    # Convert result to DataFrame
    # ------------------------------------------------------------------------

    df = result.to_pandas()

    print("\nRaw RAGAS result:")
    print(df)

    # ------------------------------------------------------------------------
    # Calculate final rows
    # ------------------------------------------------------------------------

    rows = []

    for name, _, needs_ref in metric_specs:

        if name not in df.columns:
            raise RuntimeError(
                f"RAGAS did not return metric column: {name}. "
                f"Available columns: {list(df.columns)}"
            )

        values = df[name].dropna()

        if len(values) == 0:
            raise RuntimeError(
                f"RAGAS returned no valid values for metric "
                f"{name!r}. The metric produced only NaN values."
            )

        score = float(values.mean())

        rows.append(
            {
                "framework": "RAGAS",
                "metric": name,
                "requires_reference": needs_ref,
                "score": round(score, 4),
                "case_count": len(cases),
                "eval_time_s": round(elapsed, 4),
                "judge_model": OLLAMA_MODEL,
                "recorded_at": now(),
            }
        )

    return rows


# ============================================================================
# CSV output
# ============================================================================

def append_rows(rows):
    """
    Append evaluation results to results_eval_frameworks.csv.
    """

    file_exists = RESULTS_PATH.exists()

    with open(
        RESULTS_PATH,
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "framework",
                "metric",
                "requires_reference",
                "score",
                "case_count",
                "eval_time_s",
                "judge_model",
                "recorded_at",
            ],
        )

        if not file_exists:
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

        response = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=5,
        )

        response.raise_for_status()

        models = [
            model["name"]
            for model in response.json().get(
                "models",
                [],
            )
        ]

        matching_models = [
            model
            for model in models
            if model.startswith(OLLAMA_MODEL)
        ]

        if not matching_models:

            print(
                f"\nWARNING: {OLLAMA_MODEL} "
                "was not found in Ollama."
            )

            print(
                f"Run:\n    ollama pull {OLLAMA_MODEL}\n"
            )

            return False

        print(
            f"Ollama OK: {matching_models[0]}"
        )

        return True

    except requests.exceptions.RequestException as exc:

        print(
            f"\nERROR: Could not reach Ollama at "
            f"{OLLAMA_BASE_URL}"
        )

        print(
            "Make sure Ollama is running:"
        )

        print(
            "    ollama serve"
        )

        print(
            f"\nDetails: {exc}"
        )

        return False


# ============================================================================
# Main
# ============================================================================

def main():

    print("=" * 70)
    print("TrackB RAGAS Evaluation Benchmark")
    print("=" * 70)

    # ------------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------------

    if not check_ollama():
        raise SystemExit(
            "\nOllama is unavailable. "
            "Start Ollama and make sure the model exists."
        )

    # ------------------------------------------------------------------------
    # Build cases
    # ------------------------------------------------------------------------

    print(
        "\nBuilding retrieval + generation cases "
        "from the project's real knowledge base..."
    )

    cases = build_eval_cases()

    if not cases:

        print(
            "\nNo usable cases."
        )

        print(
            "All queries may have empty 'expected' fields."
        )

        return

    # ------------------------------------------------------------------------
    # RAGAS
    # ------------------------------------------------------------------------

    print("\n" + "=" * 70)
    print("Running RAGAS")
    print("=" * 70)

    try:

        rows = run_ragas(cases)

    except Exception as exc:

        print(
            "\nRAGAS evaluation FAILED."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        raise

    # ------------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------------

    if rows:

        append_rows(rows)

        print(
            f"\nRecorded {len(rows)} rows to:"
        )

        print(
            f"    {RESULTS_PATH}"
        )

        print("\nResults:")

        for row in rows:

            print(
                f"  {row['framework']:8s} "
                f"{row['metric']:22s} "
                f"ref={str(row['requires_reference']):5s} "
                f"score={row['score']:.4f} "
                f"time={row['eval_time_s']:.2f}s"
            )

    else:

        print(
            "\nNo results were recorded."
        )


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    main()