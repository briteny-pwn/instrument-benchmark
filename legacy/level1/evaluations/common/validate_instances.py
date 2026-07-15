"""Validate the model-visible instance boundary and hidden evaluator layout."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .instance_manifest import validate_registry


VISIBLE_FILES = {
    Path("prompt.md"),
    Path("environment/instrument_manual.md"),
    Path("environment/simulator_protocol.md"),
}

LEAK_PATTERNS = {
    "grader implementation": re.compile(r"\bgrader\b", re.IGNORECASE),
    "evaluation spec": re.compile(r"\bspec\.json\b|pass_threshold|expected_sequence", re.IGNORECASE),
    "scoring rubric": re.compile(r"\brubric\b|trace_coverage|ordered_milestones", re.IGNORECASE),
    "reference solution": re.compile(r"reference[_ ]solution", re.IGNORECASE),
    "forbidden import hint": re.compile(r"forbidden imports?|do not import", re.IGNORECASE),
}


def validate(root: Path) -> list[str]:
    errors: list[str] = validate_registry(root)
    instances_root = root / "instances"
    evaluations_root = root / "evaluations"
    for instance_dir in sorted(path for path in instances_root.glob("*/*") if path.is_dir()):
        source = instance_dir.parent.name
        instance_id = instance_dir.name
        actual_files = {
            path.relative_to(instance_dir)
            for path in instance_dir.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        missing = VISIBLE_FILES - actual_files
        extra = actual_files - VISIBLE_FILES
        if missing:
            errors.append(f"{source}/{instance_id}: missing visible files {sorted(map(str, missing))}")
        if extra:
            errors.append(f"{source}/{instance_id}: unexpected model-visible files {sorted(map(str, extra))}")

        prompt = instance_dir / "prompt.md"
        if prompt.exists():
            text = prompt.read_text(encoding="utf-8")
            if not text.startswith("# Task Goal"):
                errors.append(f"{source}/{instance_id}: prompt must start with '# Task Goal'")
            if "solution.py" not in text or "run_experiment" not in text:
                errors.append(f"{source}/{instance_id}: prompt does not define the solution.py contract")

        for visible_file in sorted(actual_files):
            text = (instance_dir / visible_file).read_text(encoding="utf-8")
            for label, pattern in LEAK_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{source}/{instance_id}/{visible_file}: contains {label}")

        evaluation_dir = evaluations_root / source / instance_id
        required_hidden = [
            evaluation_dir / "spec.json",
            evaluation_dir / "grader.py",
            evaluation_dir / "reference_solution/experiment.py",
        ]
        for hidden_file in required_hidden:
            if not hidden_file.exists():
                errors.append(f"{source}/{instance_id}: missing hidden artifact {hidden_file.relative_to(root)}")
        spec_path = evaluation_dir / "spec.json"
        if spec_path.exists():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"{source}/{instance_id}: invalid hidden spec: {exc}")
            else:
                simulator_paths = [spec.get("simulator")]
                simulator_paths.extend(item.get("simulator") for item in spec.get("scenarios", []))
                authoring = spec.get("authoring", {})
                if not authoring.get("base_simulator") or not authoring.get("seed"):
                    errors.append(f"{source}/{instance_id}: missing dedicated authoring configuration")
                simulator_paths.append(authoring.get("base_simulator"))
                for simulator in filter(None, simulator_paths):
                    if not (evaluation_dir / simulator).is_file():
                        errors.append(
                            f"{source}/{instance_id}: missing hidden simulator {evaluation_dir.relative_to(root) / simulator}"
                        )
    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    errors = validate(root)
    if errors:
        print("Instance boundary validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("Instance boundary validation passed.")


if __name__ == "__main__":
    main()
