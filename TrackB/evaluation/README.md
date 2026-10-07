# Evaluation-Framework Benchmark: RAGAS vs DeepEval

## Setup

`eval_framework_benchmark.py` builds seven question / retrieved-context / answer cases from the project's own knowledge base (`kb/patient_profiles.json`, `kb/medical_notes.json`, `queries/test_queries.json`):

1. the top 3 documents are retrieved with `all-MiniLM-L6-v2` (in-memory cosine search; this evaluates the embedding retrieval, not the Qdrant service or its patient filter);
2. `qwen2.5:3b` (Ollama) writes an answer from those documents;
3. RAGAS 0.4.3 and DeepEval 4.2.8 score the same cases with the same local judge (`qwen2.5:3b`), one metric at a time, and each metric is timed.

A case the judge cannot score is reported as failed (`valid_cases < case_count`); scores are averaged over valid cases only and are never filled in from another framework or by hand.

## Results

Run recorded on 2026-10-13. All 7 cases produced a valid score for every metric in both frameworks.

| Metric | RAGAS 0.4.3 | DeepEval 4.2.8 | RAGAS time (s) | DeepEval time (s) |
| --- | ---: | ---: | ---: | ---: |
| Faithfulness | 0.93 | 0.54 | 49.0 | 61.6 |
| Answer relevancy | 0.61 | 0.74 | 14.7 | 42.6 |
| Context precision | 0.88 | 1.00 | 52.1 | 28.4 |
| Context recall | 0.86 | 0.67 | 24.4 | 24.1 |
| **Total** | | | **140.2** | **156.7** |

Summary rows are in `results_eval_frameworks.csv`, per-case scores in `results_eval_cases.csv`.

## What this run supports

- **The two frameworks do not agree.** With identical inputs and the same judge, the per-metric averages differ by 0.12 to 0.39. The frameworks ask the judge different questions (different prompts and claim-extraction steps), and a 3B-parameter judge answers them inconsistently.
- **The scores are not stable enough to rank anything.** Between two consecutive runs of this script, the faithfulness score of the first case moved from 0.0 to 0.5 in RAGAS and from 1.0 to 0.0 in DeepEval. With seven cases, one flipped case moves an average by 0.14.
- **Neither framework is meaningfully faster.** Total time was 140 s for RAGAS and 157 s for DeepEval; both are dominated by local judge calls.

## Limitations

- Seven cases.
- The same model generates the answers and judges them.
- The references are keyword phrases joined into a string, not full reference answers, so the reference-based metrics (context precision and recall) are approximate.

## Conclusion

This experiment does not justify choosing one framework over the other. Either can be driven by a local judge; a trustworthy quality number needs a larger labelled query set and a stronger, independent judge model. Retrieval quality is therefore reported with the label-based metrics of the vector-store benchmark (Recall@3, cross-patient leakage), which need no judge model.

Earlier versions of this repository reported near-identical RAGAS and DeepEval scores and a 10x speed advantage for RAGAS. Those RAGAS figures were not measured (the RAGAS run had returned no scores) and have been removed.

## Reproduce

```powershell
ollama pull qwen2.5:3b
pip install deepeval
python TrackB/evaluation/eval_framework_benchmark.py
```
