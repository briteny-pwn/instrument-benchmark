from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVALUATOR_ROOT = str((ROOT.parent / "evaluator").resolve())
sys.path.insert(0, EVALUATOR_ROOT)

from instrument_benchmark.contracts import (  # noqa: E402
    ContractError,
    load_run_config,
    validate_evaluator_report,
)
from instrument_benchmark.orchestrator import (  # noqa: E402
    _build_evaluator_request,
    _publish_fibsem_artifacts,
)
from evaluators.fibsem_liftout_v1.tests.test_reports import (  # noqa: E402
    complete_report,
)

sys.path.remove(EVALUATOR_ROOT)


OPENFIBSEM_COMMIT = "2ebccb8b9721234ca66bb94de36d0f7cfe047af9"


def test_three_repository_readmes_publish_fibsem_operator_contract() -> None:
    readmes = {
        "instance": (ROOT.parent / "instance" / "README.md").read_text(),
        "evaluator": (ROOT.parent / "evaluator" / "README.md").read_text(),
        "instrument": (ROOT / "README.md").read_text(),
    }

    assert all("fibsem_liftout_v1" in text for text in readmes.values())
    combined = "\n".join(readmes.values())
    assert (
        "run_experiment(microscope, scenario, checkpoint, output_dir) -> dict"
        in combined
    )
    assert all(step in combined for step in ("step_1", "step_2", "step_3", "step_4"))
    assert "native Linux Docker" in combined
    assert "reports/fibsem_liftout_v1.artifacts" in combined
    assert (
        "python scripts/validate_fibsem_benchmark.py --config "
        "configs/fibsem_liftout_v1.yaml"
    ) in readmes["instrument"]


def test_real_fibsem_config_pins_all_three_repos_and_openfibsem_source() -> None:
    config = load_run_config(ROOT / "configs" / "fibsem_liftout_v1.yaml")

    assert config.instance_id == "fibsem_liftout_v1"
    assert config.evaluator_id == "fibsem_liftout_v1"
    assert config.repeated_worlds == 5
    assert config.openfibsem_checkout == (ROOT.parent / "fibsem").resolve()
    assert config.openfibsem_commit == OPENFIBSEM_COMMIT


def test_openfibsem_fields_are_conditional_and_exact(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    evaluator = tmp_path / "evaluator"
    openfibsem = tmp_path / "openfibsem"
    for path in (instance, evaluator, openfibsem):
        path.mkdir()
    candidate = tmp_path / "solution.py"
    candidate.write_text("pass")
    base = {
        "schema_version": 1,
        "run_id": "run",
        "instance_checkout": str(instance),
        "instance_id": "fibsem_liftout_v1",
        "evaluator_checkout": str(evaluator),
        "evaluator_id": "fibsem_liftout_v1",
        "candidate_path": str(candidate),
        "report_path": str(tmp_path / "report.json"),
        "timeout_seconds": 30,
        "max_output_bytes": 65536,
        "repeated_worlds": 5,
        "repeated_base_seed": 47000,
        "container_protocol_version": 1,
        "image_mode": "locked",
        "openfibsem_checkout": str(openfibsem),
        "openfibsem_commit": OPENFIBSEM_COMMIT,
    }
    config = tmp_path / "run.yaml"

    for missing in ("openfibsem_checkout", "openfibsem_commit"):
        value = dict(base)
        value.pop(missing)
        config.write_text(yaml.safe_dump(value))
        with pytest.raises(ContractError, match="OpenFIBSEM"):
            load_run_config(config)

    value = dict(base)
    value["instance_id"] = value["evaluator_id"] = "pyvisa_dut_validation_v2"
    config.write_text(yaml.safe_dump(value))
    with pytest.raises(ContractError, match="only valid for FIBSEM"):
        load_run_config(config)


def test_fibsem_request_carries_exact_evaluator_image_id() -> None:
    config = load_run_config(ROOT / "configs" / "fibsem_liftout_v1.yaml")
    image_id = "sha256:" + "a" * 64

    request = _build_evaluator_request(
        config,
        instance_root=config.instance_checkout / config.instance_id,
        shared_run_root=ROOT,
        evaluator_manifest={"protocol_version": 1},
        evaluator_image_id=image_id,
    )

    assert request["evaluator_image_id"] == image_id


def test_report_v3_requires_ten_world_checkpoint_and_sibling_evidence() -> None:
    report = complete_report()
    validated = validate_evaluator_report(
        report,
        "fibsem_liftout_v1",
        expected_run_id="ignored-for-schema-v3",
    )
    assert validated["schema_version"] == 3
    assert len(validated["worlds"]) == 10

    broken = json.loads(json.dumps(report))
    broken["worlds"][0]["checkpoints"].pop("step_2")
    with pytest.raises(ContractError, match="checkpoint evidence"):
        validate_evaluator_report(broken, "fibsem_liftout_v1")

    broken = json.loads(json.dumps(report))
    broken["worlds"][0]["sim_container_evidence"] = None
    with pytest.raises(ContractError, match="sibling evidence"):
        validate_evaluator_report(broken, "fibsem_liftout_v1")


def test_trusted_checkpoint_bundles_are_published_beside_report(
    tmp_path: Path,
) -> None:
    report = complete_report()
    run_root = tmp_path / "run"
    run_root.mkdir()
    for index, world in enumerate(report["worlds"]):
        world_id = world["world_id"]
        evidence = run_root / f"fibsem-w-{index}" / "evidence"
        evidence.mkdir(parents=True)
        for name in ("journal.jsonl", "journal-summary.json"):
            (evidence / name).write_text("{}\n")
        steps = list(world["checkpoints"])
        (evidence / "service-summary.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "run",
                    "world_id": world_id,
                    "checkpoints": steps,
                }
            )
        )
        for step in steps:
            bundle = evidence / "artifacts" / world_id / step
            bundle.mkdir(parents=True)
            (bundle / "scene.glb").write_bytes(
                f"{world_id}/{step}".encode()
            )
            (bundle / "checkpoint.json").write_text("{}\n")
            index_hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(bundle.iterdir())
            }
            digest = hashlib.sha256(
                json.dumps(
                    index_hashes, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            world["checkpoints"][step]["artifact_digest"] = digest

    destination = tmp_path / "report.artifacts"
    published = _publish_fibsem_artifacts(
        run_root,
        report,
        destination,
        run_id="run",
    )

    assert published["root"] == destination.name
    assert len(published["worlds"]) == 10
    assert (destination / "nominal" / "step_1" / "scene.glb").is_file()
    assert not (destination / "nominal" / "step_1" / "scene.glb").stat().st_mode & 0o222
