from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import ContractError  # noqa: E402
from instrument_benchmark.environment import (  # noqa: E402
    EVALUATOR_REPO_PATH,
    INSTANCES_REPO_PATH,
    RepositoryPaths,
    load_repository_paths,
    read_repository_path_values,
)


def _repositories(tmp_path: Path) -> tuple[Path, Path]:
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    return instances, evaluator


def test_dotenv_supplies_repository_paths(tmp_path: Path) -> None:
    instances, evaluator = _repositories(tmp_path)
    (tmp_path / ".env").write_text(
        f"{INSTANCES_REPO_PATH}={instances}\n"
        f"{EVALUATOR_REPO_PATH}={evaluator}\n",
        encoding="utf-8",
    )

    result = load_repository_paths(tmp_path, environ={})

    assert result == RepositoryPaths(
        instances_repo_path=instances.resolve(),
        evaluator_repo_path=evaluator.resolve(),
    )


def test_process_environment_overrides_dotenv(tmp_path: Path) -> None:
    dotenv_instances, evaluator = _repositories(tmp_path)
    process_instances = tmp_path / "process-instances"
    process_instances.mkdir()
    (tmp_path / ".env").write_text(
        f"{INSTANCES_REPO_PATH}={dotenv_instances}\n"
        f"{EVALUATOR_REPO_PATH}={evaluator}\n",
        encoding="utf-8",
    )

    result = load_repository_paths(
        tmp_path,
        environ={INSTANCES_REPO_PATH: str(process_instances)},
    )

    assert result.instances_repo_path == process_instances.resolve()
    assert result.evaluator_repo_path == evaluator.resolve()


def test_complete_process_environment_does_not_require_dotenv(tmp_path: Path) -> None:
    instances, evaluator = _repositories(tmp_path)

    result = load_repository_paths(
        tmp_path,
        environ={
            INSTANCES_REPO_PATH: str(instances),
            EVALUATOR_REPO_PATH: str(evaluator),
        },
    )

    assert result.instances_repo_path == instances.resolve()
    assert result.evaluator_repo_path == evaluator.resolve()


def test_loader_does_not_search_parent_directories(tmp_path: Path) -> None:
    instances, evaluator = _repositories(tmp_path)
    (tmp_path / ".env").write_text(
        f"{INSTANCES_REPO_PATH}={instances}\n"
        f"{EVALUATOR_REPO_PATH}={evaluator}\n",
        encoding="utf-8",
    )
    nested = tmp_path / "nested"
    nested.mkdir()

    with pytest.raises(ContractError, match=f"{INSTANCES_REPO_PATH}.*required"):
        load_repository_paths(nested, environ={})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "required"),
        ("", "blank"),
        ("   ", "blank"),
        ("relative/repository", "absolute"),
    ],
)
def test_invalid_instances_value_is_rejected(
    tmp_path: Path,
    value: str | None,
    message: str,
) -> None:
    _, evaluator = _repositories(tmp_path)
    environ = {EVALUATOR_REPO_PATH: str(evaluator)}
    if value is not None:
        environ[INSTANCES_REPO_PATH] = value

    with pytest.raises(
        ContractError,
        match=rf"{INSTANCES_REPO_PATH}.*{message}",
    ):
        load_repository_paths(tmp_path, environ=environ)


def test_blank_process_value_does_not_fall_back_to_dotenv(tmp_path: Path) -> None:
    instances, evaluator = _repositories(tmp_path)
    (tmp_path / ".env").write_text(
        f"{INSTANCES_REPO_PATH}={instances}\n"
        f"{EVALUATOR_REPO_PATH}={evaluator}\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match=rf"{INSTANCES_REPO_PATH}.*blank"):
        load_repository_paths(
            tmp_path,
            environ={INSTANCES_REPO_PATH: ""},
        )


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_repository_value_must_name_an_existing_directory(
    tmp_path: Path,
    kind: str,
) -> None:
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    evaluator.mkdir()
    if kind == "file":
        instances.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(
        ContractError,
        match=rf"{INSTANCES_REPO_PATH}.*existing directory",
    ):
        load_repository_paths(
            tmp_path,
            environ={
                INSTANCES_REPO_PATH: str(instances),
                EVALUATOR_REPO_PATH: str(evaluator),
            },
        )


def test_raw_values_use_the_same_precedence_without_directory_validation(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        f'{INSTANCES_REPO_PATH}="/dotenv/instances"\n'
        f'{EVALUATOR_REPO_PATH}="/dotenv/evaluator"\n',
        encoding="utf-8",
    )

    values = read_repository_path_values(
        tmp_path,
        environ={INSTANCES_REPO_PATH: "/process/instances"},
    )

    assert values == ("/process/instances", "/dotenv/evaluator")
