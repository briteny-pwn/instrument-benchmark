from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .paths import ROOT
from .run_store import write_json


PROTOCOL_VERSION = 1


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "pass", "passed"}


def _item_metadata(instance: str) -> dict[str, Any]:
    source, _, instance_id = instance.partition("/")
    spec_path = ROOT / "evaluations" / source / instance_id / "spec.json"
    if not spec_path.is_file():
        return {"backend": source or "unknown", "capabilities": []}
    spec = _read_json(spec_path)
    capabilities = [
        name
        for name, weight in spec.get("rubric", {}).items()
        if float(weight) > 0 and name not in {"sim_execution", "forbidden_api", "robustness"}
    ]
    return {
        "backend": spec.get("gateway", source or "unknown"),
        "capabilities": capabilities,
        "rubric": spec.get("rubric", {}),
        "pass_threshold": spec.get("pass_threshold", 0.8),
    }


def _record_from_report(report_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    run_dir = report_path.parent.parent
    manifest_path = run_dir / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    instance = str(manifest.get("instance") or report.get("instance_id") or "unknown")
    metadata = _item_metadata(instance)
    scenarios = report.get("scenarios", [])
    scenario_outcomes = [
        {
            "scenario_id": item.get("scenario_id", item.get("run_id")),
            "repetition": item.get("repetition", 1),
            "passed": bool(item.get("pass")),
            "score": float(item.get("total", 0.0)),
        }
        for item in scenarios
    ]
    seeds = manifest.get("seeds", {})
    pair_seed = seeds.get("model") or seeds.get("authoring")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "record_type": "baseline_result",
        "system_id": manifest.get("model") or manifest.get("model_metadata", {}).get("model_id") or "unknown",
        "provider": manifest.get("model_metadata", {}).get("provider"),
        "agent": manifest.get("agent"),
        "item_id": instance,
        "trial_id": manifest.get("run_id", run_dir.name),
        "pair_id": f"{instance}:{pair_seed}" if pair_seed is not None else None,
        "seed": pair_seed,
        "benchmark_release": manifest.get("benchmark_release"),
        "backend": metadata["backend"],
        "capabilities": metadata["capabilities"],
        "passed": bool(report.get("pass")),
        "score": float(report.get("total", 0.0)),
        "hidden_scenario_pass_rate": _as_float(report.get("pass_rate")),
        "scenario_outcomes": scenario_outcomes,
        "dimension_scores": report.get("scores", {}),
        "rubric": metadata.get("rubric", {}),
        "pass_threshold": metadata.get("pass_threshold"),
        "manifest_sha256": (
            hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else None
        ),
    }


def _normalize_external(row: dict[str, Any]) -> dict[str, Any]:
    required = ("system_id", "item_id", "trial_id", "passed")
    missing = [name for name in required if row.get(name) in (None, "")]
    if missing:
        raise ValueError(f"baseline row missing required fields: {', '.join(missing)}")
    normalized = dict(row)
    normalized.setdefault("protocol_version", PROTOCOL_VERSION)
    normalized.setdefault("record_type", "baseline_result")
    normalized["passed"] = _as_bool(normalized["passed"])
    normalized["score"] = float(normalized.get("score", int(normalized["passed"])))
    normalized["hidden_scenario_pass_rate"] = _as_float(
        normalized.get("hidden_scenario_pass_rate")
    )
    for field in ("capabilities", "scenario_outcomes", "dimension_scores", "rubric"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = (
                json.loads(value)
                if value.strip()
                else ([] if field in {"capabilities", "scenario_outcomes"} else {})
            )
    normalized.setdefault("capabilities", [])
    normalized.setdefault("scenario_outcomes", [])
    normalized.setdefault("dimension_scores", {})
    normalized.setdefault("rubric", {})
    normalized.setdefault("backend", "unknown")
    normalized.setdefault("pair_id", None)
    normalized.setdefault("seed", None)
    return normalized


def import_baselines(inputs: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in inputs:
        if source.is_dir():
            reports = sorted(source.glob("*/evaluation/report.json"))
            if (source / "evaluation/report.json").is_file():
                reports.append(source / "evaluation/report.json")
            records.extend(_record_from_report(path) for path in reports)
        elif source.name == "report.json":
            records.append(_record_from_report(source))
        elif source.suffix == ".csv":
            with source.open(newline="", encoding="utf-8") as stream:
                records.extend(_normalize_external(row) for row in csv.DictReader(stream))
        elif source.suffix in {".jsonl", ".ndjson"}:
            records.extend(
                _normalize_external(json.loads(line))
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        elif source.suffix == ".json":
            data = _read_json(source)
            rows = data if isinstance(data, list) else data.get("records", [])
            records.extend(_normalize_external(row) for row in rows)
        else:
            raise ValueError(f"unsupported baseline input: {source}")
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return statistics.mean(items) if items else None


def _system_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_item[str(record["item_id"])].append(record)
    item_pass_rates = {
        item: statistics.mean(float(row["passed"]) for row in rows)
        for item, rows in sorted(by_item.items())
    }
    item_hspr = {
        item: statistics.mean(
            value
            for row in rows
            if (value := row.get("hidden_scenario_pass_rate")) is not None
        )
        for item, rows in sorted(by_item.items())
        if any(row.get("hidden_scenario_pass_rate") is not None for row in rows)
    }
    return {
        "trials": len(records),
        "items": len(by_item),
        "MIPR": _mean(item_pass_rates.values()),
        "MHSPR": _mean(item_hspr.values()),
        "mean_score": _mean(float(row["score"]) for row in records),
        "item_pass_rates": item_pass_rates,
    }


def _group_summaries(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        values = row.get(field, [])
        if not isinstance(values, list):
            values = [values]
        for value in values or ["unknown"]:
            grouped[str(value)].append(row)
    return {name: _system_summary(rows) for name, rows in sorted(grouped.items())}


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _paired_comparisons(
    records: list[dict[str, Any]], bootstrap_samples: int, seed: int
) -> list[dict[str, Any]]:
    item_system: dict[tuple[str, str], list[float]] = defaultdict(list)
    systems = sorted({str(row["system_id"]) for row in records})
    for row in records:
        item_system[(str(row["item_id"]), str(row["system_id"]))].append(float(row["passed"]))
    comparisons = []
    rng = random.Random(seed)
    for left, right in itertools.combinations(systems, 2):
        shared = sorted(
            item
            for item in {key[0] for key in item_system}
            if (item, left) in item_system and (item, right) in item_system
        )
        differences = [
            statistics.mean(item_system[(item, left)])
            - statistics.mean(item_system[(item, right)])
            for item in shared
        ]
        if not differences:
            continue
        draws = [
            statistics.mean(rng.choice(differences) for _ in differences)
            for _ in range(bootstrap_samples)
        ]
        comparisons.append(
            {
                "system_a": left,
                "system_b": right,
                "estimand": "paired item-level MIPR difference (a-b)",
                "paired_items": len(shared),
                "difference": statistics.mean(differences),
                "bootstrap_samples": bootstrap_samples,
                "bootstrap_ci95": [_percentile(draws, 0.025), _percentile(draws, 0.975)],
            }
        )
    return comparisons


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    return numerator / denominator if denominator else None


def _item_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    system_item: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        system_item[(str(row["system_id"]), str(row["item_id"]))].append(row)
    items = sorted({item for _, item in system_item})
    systems = sorted({system for system, _ in system_item})
    output: dict[str, Any] = {}
    for item in items:
        item_rows = [row for row in records if str(row["item_id"]) == item]
        xs, ys = [], []
        for system in systems:
            current = system_item.get((system, item))
            other = [
                statistics.mean(float(row["passed"]) for row in system_item[(system, candidate)])
                for candidate in items
                if candidate != item and (system, candidate) in system_item
            ]
            if current and other:
                xs.append(statistics.mean(float(row["passed"]) for row in current))
                ys.append(statistics.mean(other))
        retest_pairs = [
            (left, right)
            for (system, candidate), rows in system_item.items()
            if candidate == item
            for left, right in itertools.combinations(rows, 2)
        ]
        output[item] = {
            "observations": len(item_rows),
            "difficulty": 1.0 - statistics.mean(float(row["passed"]) for row in item_rows),
            "discrimination": _correlation(xs, ys),
            "discrimination_method": "item pass rate vs leave-one-item-out system pass rate",
            "test_retest_pairs": len(retest_pairs),
            "test_retest_pass_agreement": (
                statistics.mean(float(left["passed"] == right["passed"]) for left, right in retest_pairs)
                if retest_pairs
                else None
            ),
            "test_retest_mean_absolute_score_difference": (
                statistics.mean(abs(float(left["score"]) - float(right["score"])) for left, right in retest_pairs)
                if retest_pairs
                else None
            ),
        }
    return output


def analyze(
    records: list[dict[str, Any]], *, bootstrap_samples: int = 2000, seed: int = 1729
) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_system[str(row["system_id"])].append(row)
    if not records:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "status": "blocked_no_data",
            "blocker": "No external model, human, or hardware baseline records were supplied.",
            "systems": {},
        }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "complete",
        "definitions": {
            "MIPR": "macro mean of per-item pass rates",
            "MHSPR": "macro mean of per-item hidden-scenario pass rates",
        },
        "systems": {
            system: {
                **_system_summary(rows),
                "by_backend": _group_summaries(rows, "backend"),
                "by_capability": _group_summaries(rows, "capabilities"),
            }
            for system, rows in sorted(by_system.items())
        },
        "paired_comparisons": _paired_comparisons(records, bootstrap_samples, seed),
        "item_metrics": _item_metrics(records),
    }


def sensitivity(
    records: list[dict[str, Any]],
    thresholds: list[float],
    perturbations: list[float],
) -> dict[str, Any]:
    if not records:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "status": "blocked_no_data",
            "blocker": "Sensitivity analysis requires baseline records with dimension scores.",
        }
    systems = sorted({str(row["system_id"]) for row in records})
    threshold_results = []
    for threshold in thresholds:
        rates = {}
        for system in systems:
            by_item: dict[str, list[float]] = defaultdict(list)
            for row in records:
                if str(row["system_id"]) == system:
                    by_item[str(row["item_id"])].append(float(float(row["score"]) >= threshold))
            rates[system] = statistics.mean(
                statistics.mean(outcomes) for outcomes in by_item.values()
            )
        threshold_results.append(
            {"threshold": threshold, "MIPR_by_system": rates, "ranking": sorted(rates, key=rates.get, reverse=True)}
        )

    rubric_results = []
    dimensions = sorted(
        {
            name
            for row in records
            for name in row.get("rubric", {})
            if name in row.get("dimension_scores", {})
        }
    )
    for dimension in dimensions:
        for delta in perturbations:
            rates: dict[str, float] = {}
            for system in systems:
                outcomes: dict[str, list[float]] = defaultdict(list)
                for row in records:
                    if str(row["system_id"]) != system or not row.get("rubric"):
                        continue
                    weights = {name: float(value) for name, value in row["rubric"].items()}
                    weights[dimension] = max(0.0, weights.get(dimension, 0.0) * (1.0 + delta))
                    total_weight = sum(weights.values())
                    score = sum(
                        float(row.get("dimension_scores", {}).get(name, 0.0)) * weight
                        for name, weight in weights.items()
                    ) / total_weight
                    outcomes[str(row["item_id"])].append(
                        float(score >= float(row.get("pass_threshold") or 0.8))
                    )
                if outcomes:
                    rates[system] = statistics.mean(
                        statistics.mean(item_outcomes) for item_outcomes in outcomes.values()
                    )
            rubric_results.append(
                {
                    "dimension": dimension,
                    "relative_weight_change": delta,
                    "MIPR_by_system": rates,
                    "ranking": sorted(rates, key=rates.get, reverse=True),
                }
            )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "complete",
        "method": "diagnostic rescoring; required gates and scenario minimum-pass-rate rules are held out",
        "threshold_sensitivity": threshold_results,
        "rubric_weight_sensitivity": rubric_results,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        _normalize_external(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m benchmark_harness.validity")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="normalize run artifacts, JSONL, JSON, or CSV")
    importer.add_argument("inputs", nargs="+", type=Path)
    importer.add_argument("--output", required=True, type=Path)
    analyzer = commands.add_parser("analyze", help="compute baseline validity statistics")
    analyzer.add_argument("--input", required=True, type=Path)
    analyzer.add_argument("--output", required=True, type=Path)
    analyzer.add_argument("--bootstrap-samples", type=int, default=2000)
    analyzer.add_argument("--seed", type=int, default=1729)
    sensitivity_parser = commands.add_parser("sensitivity", help="rescore thresholds and rubric weights")
    sensitivity_parser.add_argument("--input", required=True, type=Path)
    sensitivity_parser.add_argument("--output", required=True, type=Path)
    sensitivity_parser.add_argument("--thresholds", default="0.7,0.75,0.8,0.85,0.9")
    sensitivity_parser.add_argument("--perturbations", default="-0.2,0.2")
    args = parser.parse_args()
    if args.command == "import":
        records = import_baselines(args.inputs)
        write_jsonl(args.output, records)
        print(json.dumps({"records": len(records), "output": str(args.output)}, indent=2))
    elif args.command == "analyze":
        report = analyze(
            _load_jsonl(args.input),
            bootstrap_samples=max(1, args.bootstrap_samples),
            seed=args.seed,
        )
        write_json(args.output, report)
        print(json.dumps(report, indent=2))
    else:
        report = sensitivity(
            _load_jsonl(args.input),
            [float(value) for value in args.thresholds.split(",")],
            [float(value) for value in args.perturbations.split(",")],
        )
        write_json(args.output, report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
