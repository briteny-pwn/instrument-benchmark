from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import ContractError  # noqa: E402
from instrument_benchmark.repository_layout import (  # noqa: E402
    resolve_evaluator_leaf,
    resolve_instance_leaf,
)


def _write_source(
    checkout: Path,
    source_id: str,
    leaf_ids: list[str],
    *,
    kind: str = "instances",
) -> Path:
    source = checkout / "sources" / source_id
    source.mkdir(parents=True)
    (source / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": source_id,
                "display_name": source_id.title(),
                "description": f"{source_id} test source",
                kind: leaf_ids,
            },
            sort_keys=False,
        )
    )
    identity_key = "instance_id" if kind == "instances" else "evaluator_id"
    manifest_name = "instance.yaml" if kind == "instances" else "evaluator.yaml"
    for leaf_id in leaf_ids:
        leaf = source / leaf_id
        leaf.mkdir()
        (leaf / manifest_name).write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "source_id": source_id,
                    identity_key: leaf_id,
                },
                sort_keys=False,
            )
        )
    return source


def test_resolves_instance_and_evaluator_from_strict_source_tree(
    tmp_path: Path,
) -> None:
    instances_repo_path = tmp_path / "instance"
    evaluator_repo_path = tmp_path / "evaluator"
    _write_source(instances_repo_path, "openfibsem", ["fibsem_liftout_v1"])
    _write_source(
        evaluator_repo_path,
        "pyvisa",
        ["pyvisa_dut_validation_v2"],
        kind="evaluators",
    )

    instance = resolve_instance_leaf(
        instances_repo_path, "openfibsem", "fibsem_liftout_v1"
    )
    assert instance.root == (
        instances_repo_path / "sources/openfibsem/fibsem_liftout_v1"
    )
    assert instance.source_manifest["instances"] == ["fibsem_liftout_v1"]

    evaluator = resolve_evaluator_leaf(
        evaluator_repo_path, "pyvisa", "pyvisa_dut_validation_v2"
    )
    assert evaluator.root == (
        evaluator_repo_path / "sources/pyvisa/pyvisa_dut_validation_v2"
    )


def test_instrument_repository_does_not_own_evaluator_container_assets() -> None:
    assert not (ROOT / "container").exists()


def test_readme_publishes_the_current_openfibsem_report_schema() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "OpenFIBSEM report is schema version 5" in text


def test_duplicate_leaf_ids_resolve_only_within_requested_source(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    _write_source(checkout, "source_a", ["shared_id"])
    _write_source(checkout, "source_b", ["shared_id"])

    first = resolve_instance_leaf(checkout, "source_a", "shared_id")
    second = resolve_instance_leaf(checkout, "source_b", "shared_id")

    assert first.root == checkout / "sources/source_a/shared_id"
    assert second.root == checkout / "sources/source_b/shared_id"
    assert first.root != second.root


@pytest.mark.parametrize(
    ("source_id", "leaf_id"),
    [
        ("BadSource", "valid_leaf"),
        ("valid_source", "BadLeaf"),
        ("../escape", "valid_leaf"),
        ("valid_source", "../escape"),
    ],
)
def test_rejects_invalid_ids_before_path_resolution(
    tmp_path: Path, source_id: str, leaf_id: str
) -> None:
    checkout = tmp_path / "checkout"
    outside = tmp_path / "escape"
    _write_source(checkout, "valid_source", ["valid_leaf"])
    outside.mkdir()
    (outside / "instance.yaml").write_text("not: a valid leaf\n")

    with pytest.raises(ContractError, match="invalid"):
        resolve_instance_leaf(checkout, source_id, leaf_id)


@pytest.mark.parametrize("payload", ["- not\n- a\n- mapping\n", "[unterminated"])
def test_rejects_missing_or_malformed_source_manifest(
    tmp_path: Path, payload: str
) -> None:
    checkout = tmp_path / "checkout"
    source = _write_source(checkout, "pyvisa", ["leaf"])
    manifest = source / "source.yaml"
    manifest.unlink()
    if payload:
        manifest.write_text(payload)

    with pytest.raises(ContractError, match="source manifest"):
        resolve_instance_leaf(checkout, "pyvisa", "leaf")


def test_rejects_missing_source_manifest(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    source = _write_source(checkout, "pyvisa", ["leaf"])
    (source / "source.yaml").unlink()

    with pytest.raises(ContractError, match="source manifest"):
        resolve_instance_leaf(checkout, "pyvisa", "leaf")


@pytest.mark.parametrize("registry", [["z_leaf", "a_leaf"], ["leaf", "leaf"]])
def test_rejects_unsorted_or_duplicate_source_registry(
    tmp_path: Path, registry: list[str]
) -> None:
    checkout = tmp_path / "checkout"
    source = _write_source(checkout, "pyvisa", ["leaf"])
    source_manifest = yaml.safe_load((source / "source.yaml").read_text())
    source_manifest["instances"] = registry
    (source / "source.yaml").write_text(
        yaml.safe_dump(source_manifest, sort_keys=False)
    )

    with pytest.raises(ContractError, match="unique, and sorted"):
        resolve_instance_leaf(checkout, "pyvisa", "leaf")


def test_rejects_registered_missing_and_unregistered_orphan_leaves(
    tmp_path: Path,
) -> None:
    missing_checkout = tmp_path / "missing"
    missing_source = _write_source(missing_checkout, "pyvisa", ["leaf"])
    leaf = missing_source / "leaf"
    (leaf / "instance.yaml").unlink()
    leaf.rmdir()
    with pytest.raises(ContractError, match="registry and leaf directories differ"):
        resolve_instance_leaf(missing_checkout, "pyvisa", "leaf")

    orphan_checkout = tmp_path / "orphan"
    orphan_source = _write_source(orphan_checkout, "pyvisa", ["leaf"])
    orphan = orphan_source / "orphan_leaf"
    orphan.mkdir()
    (orphan / "instance.yaml").write_text(
        "schema_version: 2\nsource_id: pyvisa\ninstance_id: orphan_leaf\n"
    )
    with pytest.raises(ContractError, match="registry and leaf directories differ"):
        resolve_instance_leaf(orphan_checkout, "pyvisa", "leaf")


def test_rejects_source_leaf_and_manifest_symlinks(tmp_path: Path) -> None:
    real_checkout = tmp_path / "real"
    real_source = _write_source(real_checkout, "pyvisa", ["leaf"])

    source_link_checkout = tmp_path / "source-link"
    (source_link_checkout / "sources").mkdir(parents=True)
    (source_link_checkout / "sources" / "pyvisa").symlink_to(
        real_source, target_is_directory=True
    )
    with pytest.raises(ContractError, match="source directory|symlink"):
        resolve_instance_leaf(source_link_checkout, "pyvisa", "leaf")

    leaf_link_checkout = tmp_path / "leaf-link"
    leaf_source = _write_source(leaf_link_checkout, "pyvisa", ["leaf"])
    leaf = leaf_source / "leaf"
    manifest_contents = (leaf / "instance.yaml").read_text()
    (leaf / "instance.yaml").unlink()
    leaf.rmdir()
    external_leaf = tmp_path / "external-leaf"
    external_leaf.mkdir()
    (external_leaf / "instance.yaml").write_text(manifest_contents)
    leaf.symlink_to(external_leaf, target_is_directory=True)
    with pytest.raises(ContractError, match="symlink"):
        resolve_instance_leaf(leaf_link_checkout, "pyvisa", "leaf")

    source_manifest_checkout = tmp_path / "source-manifest-link"
    source = _write_source(source_manifest_checkout, "pyvisa", ["leaf"])
    source_manifest = source / "source.yaml"
    external_source_manifest = tmp_path / "external-source.yaml"
    external_source_manifest.write_text(source_manifest.read_text())
    source_manifest.unlink()
    source_manifest.symlink_to(external_source_manifest)
    with pytest.raises(ContractError, match="source manifest"):
        resolve_instance_leaf(source_manifest_checkout, "pyvisa", "leaf")

    leaf_manifest_checkout = tmp_path / "leaf-manifest-link"
    source = _write_source(leaf_manifest_checkout, "pyvisa", ["leaf"])
    leaf_manifest = source / "leaf" / "instance.yaml"
    external_leaf_manifest = tmp_path / "external-instance.yaml"
    external_leaf_manifest.write_text(leaf_manifest.read_text())
    leaf_manifest.unlink()
    leaf_manifest.symlink_to(external_leaf_manifest)
    with pytest.raises(ContractError, match="leaf manifest|symlink"):
        resolve_instance_leaf(leaf_manifest_checkout, "pyvisa", "leaf")


def test_rejects_source_and_leaf_manifest_identity_mismatches(
    tmp_path: Path,
) -> None:
    source_checkout = tmp_path / "source-mismatch"
    source = _write_source(source_checkout, "pyvisa", ["leaf"])
    source_value = yaml.safe_load((source / "source.yaml").read_text())
    source_value["source_id"] = "other"
    (source / "source.yaml").write_text(yaml.safe_dump(source_value))
    with pytest.raises(ContractError, match="source manifest identity"):
        resolve_instance_leaf(source_checkout, "pyvisa", "leaf")

    leaf_checkout = tmp_path / "leaf-mismatch"
    source = _write_source(leaf_checkout, "pyvisa", ["leaf"])
    leaf_manifest = source / "leaf" / "instance.yaml"
    leaf_value = yaml.safe_load(leaf_manifest.read_text())
    leaf_value["instance_id"] = "other"
    leaf_manifest.write_text(yaml.safe_dump(leaf_value))
    with pytest.raises(ContractError, match="leaf manifest identity"):
        resolve_instance_leaf(leaf_checkout, "pyvisa", "leaf")

    leaf_source_checkout = tmp_path / "leaf-source-mismatch"
    source = _write_source(leaf_source_checkout, "pyvisa", ["leaf"])
    leaf_manifest = source / "leaf" / "instance.yaml"
    leaf_value = yaml.safe_load(leaf_manifest.read_text())
    leaf_value["source_id"] = "other"
    leaf_manifest.write_text(yaml.safe_dump(leaf_value))
    with pytest.raises(ContractError, match="leaf manifest identity"):
        resolve_instance_leaf(leaf_source_checkout, "pyvisa", "leaf")


def test_rejects_legacy_flat_instance_and_evaluator_layouts(
    tmp_path: Path,
) -> None:
    instances_repo_path = tmp_path / "instance"
    _write_source(instances_repo_path, "pyvisa", ["leaf"])
    legacy_leaf = instances_repo_path / "legacy_leaf"
    legacy_leaf.mkdir()
    (legacy_leaf / "instance.yaml").write_text("instance_id: legacy_leaf\n")
    with pytest.raises(ContractError, match="legacy flat"):
        resolve_instance_leaf(instances_repo_path, "pyvisa", "leaf")

    evaluator_repo_path = tmp_path / "evaluator"
    _write_source(evaluator_repo_path, "pyvisa", ["leaf"], kind="evaluators")
    (evaluator_repo_path / "evaluators").mkdir()
    with pytest.raises(ContractError, match="legacy evaluators"):
        resolve_evaluator_leaf(evaluator_repo_path, "pyvisa", "leaf")
