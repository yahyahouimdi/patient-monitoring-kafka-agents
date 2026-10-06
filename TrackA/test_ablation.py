from pathlib import Path

from TrackA.ablation import run_ablation


def test_scripted_ablation_checks_pipeline_wiring():
    """Wiring check only: the scripted mode replaces the model with a fixed
    lookup, so this proves the gate/guardrail/emission plumbing, not the
    quality of the reasoning model."""
    output = Path("TrackA/docs/.ablation_test.csv")
    try:
        rows = run_ablation(live=False, output_path=output)
        by_id = {row["scenario_id"]: row for row in rows}
        assert all(row["reasoning_source"] == "scripted-stub" for row in rows)
        assert by_id["S2"]["baseline_severity"] == "normal"
        assert by_id["S2"]["llm_raw_severity"] == "not called (gate declined)"
        assert by_id["S4"]["baseline_severity"] == "normal"
        assert by_id["S4"]["reasoning_severity"] == "moderate"
        assert by_id["S5"]["reasoning_severity"] == "high"
        assert by_id["S6"]["reasoning_confidence"] == "uncertain_connectivity_drop"
    finally:
        output.unlink(missing_ok=True)
