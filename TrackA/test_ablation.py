from pathlib import Path

from TrackA.ablation import run_ablation


def test_ablation_records_expected_scenario_differences():
    output = Path("TrackA/docs/.ablation_test.csv")
    try:
        rows = run_ablation(output_path=output)
        by_id = {row["scenario_id"]: row for row in rows}
        assert by_id["S2"]["baseline_severity"] == "normal"
        assert by_id["S4"]["baseline_severity"] == "normal"
        assert by_id["S4"]["reasoning_severity"] == "moderate"
        assert by_id["S5"]["reasoning_severity"] == "high"
        assert by_id["S6"]["reasoning_confidence"] == "uncertain_connectivity_drop"
    finally:
        output.unlink(missing_ok=True)
