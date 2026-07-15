"""Run representative negative candidates and verify that required gates reject them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


CASES = [
    ("forbidden_pyvisa", "pyvisa/pyvisa_dc_power_supply_basic", "import_pyvisa.py", "forbidden_import"),
    ("hardcoded_no_io", "pyvisa/pyvisa_dc_power_supply_basic", "hardcoded_no_io.py", "gate_failed:dimension:instrument_access"),
    ("unsafe_power_output", "pyvisa/pyvisa_dc_power_supply_basic", "unsafe_power_output.py", "check_failed:safe_output_state"),
    ("hardcoded_ascii_summary", "pyvisa/pyvisa_dmm_ascii_average", "hardcoded_ascii_summary.py", "check_failed:ascii_array_oracle"),
    ("hardcoded_binary_waveform", "pyvisa/pyvisa_scope_binary_waveform", "hardcoded_binary_waveform.py", "check_failed:ieee_waveform_oracle"),
    ("wrong_awg_upload", "pyvisa/pyvisa_awg_ascii_upload", "wrong_awg_upload.py", "check_failed:uploaded_waveform_oracle"),
    (
        "mixed_without_source",
        "pyvisa/pyvisa_mixed_signal_calibration",
        "mixed_measure_without_source.py",
        "check_failed:dmm_observation_oracle",
    ),
    (
        "dut_missing_route_forgery",
        "pyvisa/pyvisa_multi_instrument_dut_validation",
        "dut_missing_route_forgery.py",
        "check_failed:dmm_observation_oracle",
    ),
    (
        "fixed_logger_resource",
        "pyvisa/pyvisa_resource_discovery_idn",
        "fixed_logger_resource.py",
        "check_failed:temperature_oracle",
    ),
    (
        "sweep_query_without_setting",
        "qcodes/qcodes_station_sweep_basic",
        "sweep_query_without_setting.py",
        "check_failed:sweep_causal_alignment",
    ),
    (
        "pump_start_without_interlock",
        "epics/epics_asyn_serial_pump_interlock",
        "pump_start_without_interlock.py",
        "check_failed:pump_safety_process",
    ),
    (
        "spectrometer_hardcoded_summary",
        "yaq/yaq_fake_spectrometer_triggered_acquisition",
        "spectrometer_hardcoded_summary.py",
        "check_failed:spectrum_trace_oracle",
    ),
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    negative_root = root / "evaluations/common/negative_cases"
    failures: list[str] = []
    for case_id, evaluation, candidate_name, expected_evidence in CASES:
        grader = root / "evaluations" / evaluation / "grader.py"
        candidate = negative_root / candidate_name
        process = subprocess.run(
            [sys.executable, str(grader), str(candidate)], cwd=root, text=True, capture_output=True
        )
        if process.returncode != 0:
            failures.append(f"{case_id}: grader exited {process.returncode}: {process.stderr.strip()}")
            print(f"{case_id:<28} error")
            continue
        try:
            report = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            failures.append(f"{case_id}: invalid JSON report: {exc}")
            print(f"{case_id:<28} invalid-json")
            continue
        failure_codes = set(report.get("failure_codes", []))
        for scenario in report.get("scenarios", []):
            failure_codes.update(scenario.get("failure_codes", []))
        rejected = not report.get("pass", False)
        evidence_found = expected_evidence in failure_codes
        print(
            f"{case_id:<28} total={float(report.get('total', 0.0)):.4f}  "
            f"rejected={str(rejected).lower():5}  evidence={str(evidence_found).lower()}"
        )
        if not rejected or not evidence_found:
            failures.append(
                f"{case_id}: expected rejection with exact failure code {expected_evidence!r}; "
                f"got {sorted(failure_codes)!r}"
            )
    if failures:
        print("\nNegative suite failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\nAll {len(CASES)} negative cases were correctly rejected.")


if __name__ == "__main__":
    main()
