from __future__ import annotations

from pathlib import Path

import pytest

from instrument_benchmark.candidate import CandidateContract, inventory_candidate
from instrument_benchmark.contracts import ContractError


def test_expands_one_source_contract_into_all_grouped_files() -> None:
    contract = CandidateContract.from_source_manifest(
        {
            "candidate": {
                "producer": "task_environment",
                "groups": ["step_1", "step_2"],
                "files_per_group": ["image.png", "components/sample.stl"],
            }
        }
    )

    assert contract.producer == "task_environment"
    assert contract.files == (
        "step_1/components/sample.stl",
        "step_1/image.png",
        "step_2/components/sample.stl",
        "step_2/image.png",
    )


def test_inventories_all_safe_regular_files_and_missing_files(tmp_path: Path) -> None:
    contract = CandidateContract("task_environment", ("a.stl", "b.png"))
    (tmp_path / "a.stl").write_text("mesh")

    inventory = inventory_candidate(tmp_path, contract)

    assert inventory.files == ("a.stl",)
    assert inventory.missing_files == ("b.png",)
    assert inventory.invalid_files == ()
    assert inventory.complete is False


def test_marks_expected_symlink_as_invalid(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("mesh")
    (tmp_path / "candidate.stl").symlink_to(target)

    inventory = inventory_candidate(
        tmp_path,
        CandidateContract("task_environment", ("candidate.stl",)),
    )

    assert inventory.files == ()
    assert inventory.missing_files == ()
    assert inventory.invalid_files == ("candidate.stl",)


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "a/../b"])
def test_rejects_unsafe_candidate_contract_path(relative: str) -> None:
    with pytest.raises(ContractError, match="candidate file"):
        CandidateContract("agent", (relative,))
