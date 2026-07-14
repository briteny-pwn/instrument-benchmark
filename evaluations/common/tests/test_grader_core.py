from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluations.common import grader_core, raw_trace


class TraceOracleTests(unittest.TestCase):
    def test_numeric_aggregate_supports_first_and_last(self) -> None:
        raw_trace.TRACE[:] = [
            raw_trace.TraceEvent("query", {"command": "READ?", "response": "VALUE 1.5"}),
            raw_trace.TraceEvent("query", {"command": "READ?", "response": "VALUE 2.5"}),
        ]
        check = {
            "selector": {"kind": "query", "command": "READ?"},
            "response_regex": r"^VALUE\s+([-+0-9.eE]+)$",
            "assertions": [
                {"result_path": "$.first", "aggregate": "first"},
                {"result_path": "$.last", "aggregate": "last"},
            ],
        }
        score, detail = grader_core._grade_trace_numeric_aggregate(
            check, {"first": 1.5, "last": 2.5}
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(detail["values"], [1.5, 2.5])

    def setUp(self) -> None:
        raw_trace.reset_trace()

    def test_trace_numeric_aggregate_recomputes_candidate_statistics(self) -> None:
        for value in (1.0, 2.0, 3.0):
            raw_trace.record(
                "query",
                {"command": "MEASURE? signal", "response": f"MEASURED signal {value} ID 1"},
            )
        check = {
            "type": "trace_numeric_aggregate",
            "response_regex": r"^MEASURED\s+signal\s+([-+0-9.eE]+)",
            "selector": {"kind": "query", "command": "MEASURE? signal"},
            "assertions": [
                {"result_path": "$.sample_count", "aggregate": "count"},
                {"result_path": "$.mean_signal", "aggregate": "mean"},
                {"result_path": "$.std_signal", "aggregate": "sample_stdev"},
                {
                    "result_path": "$.stable",
                    "aggregate": "sample_stdev",
                    "compare": "lt",
                    "threshold": 1.1,
                },
            ],
        }
        result = {"sample_count": 3, "mean_signal": 2.0, "std_signal": 1.0, "stable": True}

        score, evidence = grader_core._grade_trace_numeric_aggregate(check, result)

        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["values"], [1.0, 2.0, 3.0])

    def test_empty_trace_cannot_match_empty_or_default_result(self) -> None:
        check = {
            "type": "trace_numeric_aggregate",
            "response_regex": r"([-+0-9.eE]+)",
            "selector": {"kind": "query"},
            "assertions": [
                {"result_path": "$.sample_count", "aggregate": "count"},
                {
                    "result_path": "$.stable",
                    "aggregate": "sample_stdev",
                    "compare": "lt",
                    "threshold": 0.01,
                },
            ],
        }

        score, evidence = grader_core._grade_trace_numeric_aggregate(check, {})

        self.assertEqual(score, 0.0)
        self.assertFalse(any(item["matched"] for item in evidence["assertions"]))

    def test_command_regex_accepts_equivalent_numeric_format(self) -> None:
        raw_trace.record("write", {"handle": "h1", "command": ":SOURce1:VOLTage 3.300"})

        matched = grader_core._match_command(
            {"kind": "write", "command_regex": r"^:SOURCE1:VOLTAGE 3\.3(?:0*)?$"}, raw_trace.TRACE
        )

        self.assertTrue(matched)

    def test_trace_expectation_can_match_connection_parameters(self) -> None:
        raw_trace.record(
            "open",
            {
                "handle": "h1",
                "resource": "TCPIP0::host::INSTR",
                "timeout": 4000,
                "read_termination": "\n",
                "write_termination": "\n",
                "timeout_explicit": True,
                "read_termination_explicit": True,
                "write_termination_explicit": True,
            },
        )

        matched = grader_core._match_command(
            {
                "kind": "open",
                "payload_equals": {
                    "timeout": 4000,
                    "read_termination": "\n",
                    "write_termination": "\n",
                    "timeout_explicit": True,
                    "read_termination_explicit": True,
                    "write_termination_explicit": True,
                },
            },
            raw_trace.TRACE,
        )

        self.assertTrue(matched)

    def test_trace_numeric_array_checks_values_count_and_mean(self) -> None:
        raw_trace.record(
            "query",
            {"handle": "h1", "command": "TRACE:DATA?", "response": "-1.0,+2.0,3.0E-1"},
        )
        check = {
            "selector": {"kind": "query", "command": "TRACE:DATA?"},
            "delimiter": ",",
            "assertions": [
                {"result_path": "$.samples", "aggregate": "values"},
                {"result_path": "$.count", "aggregate": "count"},
                {"result_path": "$.average", "aggregate": "mean"},
            ],
        }
        result = {"samples": [-1.0, 2.0, 0.3], "count": 3, "average": 1.3 / 3}

        score, evidence = grader_core._grade_trace_numeric_array(check, result)

        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["values"], [-1.0, 2.0, 0.3])

    def test_string_history_is_bound_to_trace_responses(self) -> None:
        raw_trace.record("query", {"command": "MON?", "response": "STATE=RAMPING"})
        raw_trace.record("query", {"command": "MON?", "response": "STATE=STABLE"})
        check = {
            "selector": {"kind": "query", "command": "MON?"},
            "result_path": "$.history",
        }
        score, detail = grader_core._grade_trace_string_array(
            check, {"history": ["STATE=RAMPING", "STATE=STABLE"]}
        )
        self.assertEqual(score, 1.0)
        self.assertTrue(detail["matched"])

    def test_ieee_block_oracle_decodes_multi_digit_length_and_scaling(self) -> None:
        raw_trace.record("query", {"command": "CURVE?", "response": "#212ABCDEFGHIJKL"})
        raw_codes = list(b"ABCDEFGHIJKL")
        voltages = [(value - 128) * 0.02 for value in raw_codes]
        check = {
            "selector": {"kind": "query", "command": "CURVE?"},
            "scale": 0.02,
            "offset": 128,
            "assertions": [
                {"result_path": "$.raw_codes", "derived": "raw_values"},
                {"result_path": "$.sample_count", "derived": "count"},
                {"result_path": "$.voltages", "derived": "scaled_values"},
                {"result_path": "$.mean", "derived": "scaled_mean"},
            ],
        }
        result = {
            "raw_codes": raw_codes,
            "sample_count": 12,
            "voltages": voltages,
            "mean": sum(voltages) / len(voltages),
        }

        score, evidence = grader_core._grade_trace_ieee_block(check, result)

        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["payload_length"], 12)

    def test_truncated_ieee_block_cannot_score(self) -> None:
        raw_trace.record("query", {"command": "CURVE?", "response": "#18ABC"})
        check = {
            "selector": {"kind": "query", "command": "CURVE?"},
            "assertions": [{"result_path": "$.sample_count", "derived": "count"}],
        }

        score, evidence = grader_core._grade_trace_ieee_block(check, {"sample_count": 3})

        self.assertEqual(score, 0.0)
        self.assertTrue(evidence["parse_errors"])

    def test_uploaded_numeric_command_is_checked_semantically(self) -> None:
        raw_trace.record(
            "write", {"command": "DATA:ARB RAMP,0,0.2500,5e-1,0.750000,1.0"}
        )
        check = {
            "command_prefix": "DATA:ARB ",
            "expected_name": "RAMP",
            "expected_values": [0.0, 0.25, 0.5, 0.75, 1.0],
            "result_name_path": "$.waveform",
            "result_values_path": "$.points",
            "result_count_path": "$.count",
        }
        result = {"waveform": "RAMP", "points": [0, 0.25, 0.5, 0.75, 1], "count": 5}

        score, evidence = grader_core._grade_trace_command_numeric_array(check, result)

        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["parsed_commands"][0]["values"], [0.0, 0.25, 0.5, 0.75, 1.0])

    def test_result_boolean_is_bound_to_instrument_response(self) -> None:
        raw_trace.record("query", {"command": "OUTP?", "response": "ON"})
        check = {
            "selector": {"kind": "query", "command": "OUTP?"},
            "parse": "bool_on_off",
            "expected": True,
            "result_path": "$.enabled",
        }

        score, evidence = grader_core._grade_trace_response(check, {"enabled": True})

        self.assertEqual(score, 1.0)
        self.assertTrue(evidence["parsed"])

    def test_result_value_can_be_bound_to_hidden_simulator_state(self) -> None:
        check = {
            "name": "attempts",
            "type": "result_sim_state_binding",
            "result_path": "$.start_attempts",
            "sim_path": "$.state.pump.start_attempts",
        }
        score, evidence = grader_core._run_v2_check(
            check,
            {"start_attempts": 2},
            {"state": {"pump": {"start_attempts": 2}}},
            [],
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["state_value"], 2)

        false_score, _ = grader_core._run_v2_check(
            check,
            {"start_attempts": True},
            {"state": {"pump": {"start_attempts": 1}}},
            [],
        )
        self.assertEqual(false_score, 0.0)

    def test_identity_model_is_parsed_from_csv_response(self) -> None:
        raw_trace.record(
            "query",
            {"handle": "h1", "command": "*IDN?", "response": "Vendor,Logger300,SERIAL,1.0"},
        )
        check = {
            "selector": {"kind": "query", "command": "*IDN?"},
            "parse": "csv_field",
            "field_index": 1,
            "expected": "Logger300",
            "result_path": "$.instrument",
        }

        score, evidence = grader_core._grade_trace_response(check, {"instrument": "Logger300"})

        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["parsed"], "Logger300")

    def test_missing_identity_response_scores_zero_instead_of_crashing(self) -> None:
        check = {
            "selector": {"kind": "query", "command": "*IDN?"},
            "parse": "csv_field",
            "field_index": 1,
            "expected": "Logger300",
        }

        score, evidence = grader_core._grade_trace_response(check, {})

        self.assertEqual(score, 0.0)
        self.assertIsNone(evidence["parsed"])

    def test_threshold_decision_is_recomputed_from_verified_metrics(self) -> None:
        check = {
            "result_path": "$.passed",
            "conditions": [
                {"path": "$.output_enabled", "equals": True},
                {"path": "$.average", "target": 1.2, "abs_tol": 0.002},
                {"path": "$.peak_to_peak", "target": 1.2, "abs_tol": 0.02},
            ],
        }

        score, evidence = grader_core._grade_result_threshold_decision(
            check,
            {"output_enabled": True, "average": 1.201, "peak_to_peak": 1.19, "passed": True},
        )

        self.assertEqual(score, 1.0)
        self.assertTrue(evidence["expected"])

    def test_threshold_decision_supports_range_limit_and_equality(self) -> None:
        check = {
            "result_path": "$.passed",
            "conditions": [
                {"path": "$.supply", "range": [4.95, 5.05]},
                {"path": "$.error", "max": 0.005},
                {"path": "$.enabled", "equals": True},
            ],
        }

        score, evidence = grader_core._grade_result_threshold_decision(
            check, {"supply": 5.001, "error": 0.004, "enabled": True, "passed": True}
        )

        self.assertEqual(score, 1.0)

    def test_threshold_decision_can_emit_alarm_labels(self) -> None:
        check = {
            "result_path": "$.alarm",
            "true_value": "NO_ALARM",
            "false_value": "HIGH",
            "conditions": [{"path": "$.max_error", "max": 0.05}],
        }
        score, detail = grader_core._grade_result_threshold_decision(
            check, {"alarm": "HIGH", "max_error": 0.08}
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(detail["expected"], "HIGH")

    def test_boolean_decision_rejects_integer_alias(self) -> None:
        check = {
            "result_path": "$.passed",
            "conditions": [{"path": "$.value", "max": 1.0}],
        }
        score, _ = grader_core._grade_result_threshold_decision(
            check, {"value": 0.5, "passed": 1}
        )
        self.assertEqual(score, 0.0)

    def test_endpoint_slope_is_recomputed_from_observed_arrays(self) -> None:
        check = {
            "x_path": "$.x",
            "y_path": "$.y",
            "slope_path": "$.slope",
        }
        score, detail = grader_core._grade_result_endpoint_slope(
            check, {"x": [-0.2, 0.0, 0.4], "y": [100, 140, 220], "slope": 200.0}
        )
        self.assertEqual(score, 1.0)
        self.assertAlmostEqual(detail["derived"], 200.0)

    def test_cross_device_validation_detects_faulty_processor(self) -> None:
        check = {
            "values_path": "$.sensors",
            "average_path": "$.average",
            "deviation_path": "$.deviation",
            "result_path": "$.valid",
        }
        score, detail = grader_core._grade_result_mean_deviation_validation(
            check,
            {"sensors": [10.0, 14.0], "average": 12.5, "deviation": 2.5, "valid": False},
        )
        self.assertEqual(score, 1.0)
        self.assertFalse(detail["expected_decision"])

    def test_argmax_position_is_recomputed(self) -> None:
        check = {"x_path": "$.positions", "y_path": "$.signals", "result_path": "$.best"}
        score, detail = grader_core._grade_result_argmax_x(
            check, {"positions": [-1, 0, 1], "signals": [0.1, 0.8, 0.2], "best": 0}
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(detail["expected"], 0)

    def test_xy_spectrum_is_recomputed_from_trace_arrays(self) -> None:
        raw_trace.record("query", {"command": "WAVELENGTHS?", "response": "WAVELENGTHS 500,501,502"})
        raw_trace.record("query", {"command": "COUNTS?", "response": "COUNTS 2,5,3"})
        check = {
            "x_selector": {"kind": "query", "command": "WAVELENGTHS?"},
            "y_selector": {"kind": "query", "command": "COUNTS?"},
            "x_prefix": "WAVELENGTHS",
            "y_prefix": "COUNTS",
            "result_paths": {
                "point_count": "$.count",
                "peak_x": "$.peak_wavelength",
                "peak_y": "$.peak_counts",
                "integral": "$.integrated",
            },
        }
        score, detail = grader_core._grade_trace_xy_spectrum(
            check,
            {"count": 3, "peak_wavelength": 501, "peak_counts": 5, "integrated": 10},
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(detail["derived"]["peak_x"], 501.0)

    def test_pairwise_error_is_recomputed_from_bound_arrays(self) -> None:
        check = {
            "left_path": "$.scope",
            "right_path": "$.dmm",
            "result_path": "$.max_error",
        }

        score, evidence = grader_core._grade_result_pairwise_max_abs_error(
            check,
            {"scope": [0.0, 0.3, 0.6], "dmm": [0.001, 0.298, 0.603], "max_error": 0.003},
        )

        self.assertEqual(score, 1.0)
        self.assertAlmostEqual(evidence["derived"], 0.003)

    def test_pairwise_difference_array_is_recomputed(self) -> None:
        check = {
            "left_path": "$.setpoints",
            "right_path": "$.readbacks",
            "result_path": "$.errors",
        }
        score, detail = grader_core._grade_result_pairwise_differences(
            check,
            {"setpoints": [0, 1, 2], "readbacks": [0.01, 0.99, 2.03], "errors": [0.01, -0.01, 0.03]},
        )
        self.assertEqual(score, 1.0)
        self.assertTrue(detail["matched"])

    def test_linear_fit_is_recomputed_from_observed_arrays(self) -> None:
        check = {
            "x_path": "$.x",
            "y_path": "$.y",
            "slope_path": "$.slope",
            "intercept_path": "$.intercept",
        }

        score, evidence = grader_core._grade_result_linear_fit(
            check,
            {"x": [-0.1, 0.0, 0.1], "y": [-0.19, 0.01, 0.21], "slope": 2.0, "intercept": 0.01},
        )

        self.assertEqual(score, 1.0)
        self.assertAlmostEqual(evidence["derived_slope"], 2.0)
        self.assertAlmostEqual(evidence["derived_intercept"], 0.01)


class GateTests(unittest.TestCase):
    def test_failed_required_check_blocks_pass(self) -> None:
        failures = grader_core._evaluate_gates(
            [{"dimension": "instrument_access", "min": 1.0}, {"check": "oracle", "min": 1.0}],
            {"instrument_access": 1.0},
            [{"name": "oracle", "score": 0.75}],
        )

        self.assertEqual(len(failures), 1)
        self.assertIn("check oracle", failures[0])


class ScenarioSuiteTests(unittest.TestCase):
    def test_suite_uses_pass_rate_as_robustness(self) -> None:
        reports = iter(
            [
                {"scores": {"task_success": 1.0}, "total": 1.0, "pass": True, "feedback": []},
                {"scores": {"task_success": 0.5}, "total": 0.5, "pass": False, "feedback": []},
            ]
        )
        spec = {
            "instance_id": "example",
            "spec_version": 2,
            "pass_threshold": 0.7,
            "suite": {"robustness_weight": 0.25, "minimum_pass_rate": 1.0},
            "scenarios": [
                {"id": "nominal", "simulator": "sim/a.json"},
                {"id": "perturbed", "simulator": "sim/b.json"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(grader_core, "_grade_single", side_effect=lambda *args: next(reports)):
                report = grader_core._grade_scenario_suite(
                    Path(tmpdir) / "solution.py", Path(tmpdir) / "spec.json", spec
                )

        self.assertEqual(report["pass_rate"], 0.5)
        self.assertEqual(report["scores"]["robustness"], 0.5)
        self.assertEqual(report["reliability"]["overall"]["run_count"], 2)
        self.assertEqual(report["reliability"]["overall"]["mean_total"], 0.75)
        low, high = report["reliability"]["overall"]["pass_rate_wilson_ci95"]
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)
        self.assertFalse(report["pass"])

    def test_reliability_is_reported_per_scenario(self) -> None:
        reports = [
            {"scenario_id": "stable", "total": 1.0, "pass": True},
            {"scenario_id": "stable", "total": 0.8, "pass": True},
            {"scenario_id": "noisy", "total": 0.6, "pass": False},
        ]

        reliability = grader_core._build_reliability_report(reports)

        self.assertEqual(reliability["by_scenario"]["stable"]["run_count"], 2)
        self.assertEqual(reliability["by_scenario"]["stable"]["mean_total"], 0.9)
        self.assertEqual(reliability["by_scenario"]["noisy"]["pass_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
