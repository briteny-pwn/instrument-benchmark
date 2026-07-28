from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


BUILD_MANIFEST = ".iab-build-manifest.json"


class EvaluatorImageError(RuntimeError):
    """Evaluator image inputs or Docker results are invalid."""


@dataclass(frozen=True)
class EvaluatorBuildContext:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    dockerfile_sha256: str
    evaluator_commit: str


@dataclass(frozen=True)
class ImageCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class EvaluatorImageEvidence:
    reference: str
    image_id: str
    repo_digest: str | None
    dockerfile_sha256: str
    build_manifest_sha256: str
    evaluator_commit: str
    platform: str
    user: str


ImageExecutor = Callable[[list[str]], ImageCommandResult]


class EvaluatorImageBuilder:
    def __init__(
        self,
        *,
        assets_root: Path,
        docker_executable: str = "docker",
        executor: ImageExecutor | None = None,
    ) -> None:
        self.assets_root = assets_root.resolve()
        self.docker_executable = docker_executable
        self.executor = executor or _execute_image_command

    def build(self, evaluator_checkout: Path, *, run_id: str) -> EvaluatorImageEvidence:
        evaluator_checkout = evaluator_checkout.resolve()
        commit_time = _git(evaluator_checkout, "show", "-s", "--format=%ct", "HEAD")
        with tempfile.TemporaryDirectory(prefix="iab-evaluator-build-") as directory:
            context = stage_evaluator_build_context(
                evaluator_checkout,
                self.assets_root,
                Path(directory) / "context",
            )
            verify_build_manifest(context.root, context.manifest_path)
            safe_run = _safe_tag(run_id)
            reference = (
                f"iab/evaluator:{safe_run}-{context.evaluator_commit[:12]}"
            )
            build = self.executor(
                [
                    self.docker_executable,
                    "build",
                    "--network=none",
                    "--platform=linux/amd64",
                    "--pull=false",
                    "--build-arg",
                    f"SOURCE_DATE_EPOCH={commit_time}",
                    "--label",
                    "iab.managed=true",
                    "--label",
                    "iab.kind=evaluator-image",
                    "--label",
                    f"iab.evaluator_commit={context.evaluator_commit}",
                    "--tag",
                    reference,
                    "--file",
                    str(context.root / "evaluator.Dockerfile"),
                    str(context.root),
                ]
            )
            _require_success(build, "evaluator image build")
            inspected = self.executor(
                [self.docker_executable, "image", "inspect", reference]
            )
            _require_success(inspected, "evaluator image inspect")
            value = _one_image(inspected.stdout)
            platform = f"{value.get('Os')}/{value.get('Architecture')}"
            user = str(value.get("Config", {}).get("User", ""))
            if platform != "linux/amd64":
                raise EvaluatorImageError(
                    f"evaluator image platform is {platform}, expected linux/amd64"
                )
            if user != "11001:11001":
                raise EvaluatorImageError(
                    f"evaluator image user is {user!r}, expected '11001:11001'"
                )
            image_id = value.get("Id")
            if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
                raise EvaluatorImageError("evaluator image ID is invalid")
            repo_digests = value.get("RepoDigests", [])
            repo_digest = (
                str(repo_digests[0])
                if isinstance(repo_digests, list) and repo_digests
                else None
            )
            return EvaluatorImageEvidence(
                reference=reference,
                image_id=image_id,
                repo_digest=repo_digest,
                dockerfile_sha256=context.dockerfile_sha256,
                build_manifest_sha256=context.manifest_sha256,
                evaluator_commit=context.evaluator_commit,
                platform=platform,
                user=user,
            )

    def remove(self, image: EvaluatorImageEvidence) -> None:
        removed = self.executor(
            [self.docker_executable, "image", "rm", image.reference]
        )
        _require_success(removed, "evaluator image tag removal")


def stage_evaluator_build_context(
    evaluator_checkout: Path,
    assets_root: Path,
    destination: Path,
) -> EvaluatorBuildContext:
    evaluator_checkout = evaluator_checkout.resolve()
    assets_root = assets_root.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise EvaluatorImageError(f"build context already exists: {destination}")
    _verify_wheelhouse(assets_root / "wheelhouse")
    _verify_docker_cli(assets_root / "docker-cli")
    destination.mkdir(parents=True)
    evaluator_target = destination / "evaluator"
    evaluator_target.mkdir()
    commit = _git(evaluator_checkout, "rev-parse", "HEAD")
    for relative in _tracked_files(evaluator_checkout):
        source = evaluator_checkout / relative
        if source.is_symlink() or not source.is_file():
            raise EvaluatorImageError(f"tracked evaluator input is not a regular file: {relative}")
        target = evaluator_target / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for name in ("evaluator.Dockerfile", "evaluator-requirements.lock"):
        source = assets_root / name
        if not source.is_file() or source.is_symlink():
            raise EvaluatorImageError(f"missing evaluator image input: {name}")
        shutil.copy2(source, destination / name)
    shutil.copytree(assets_root / "wheelhouse", destination / "wheelhouse")
    shutil.copytree(assets_root / "docker-cli", destination / "docker-cli")
    manifest_path = destination / BUILD_MANIFEST
    manifest = {
        "schema_version": 1,
        "files": _file_records(destination, exclude={BUILD_MANIFEST}),
    }
    payload = _canonical_json(manifest)
    manifest_path.write_bytes(payload)
    return EvaluatorBuildContext(
        root=destination,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(payload),
        dockerfile_sha256=_sha256((destination / "evaluator.Dockerfile").read_bytes()),
        evaluator_commit=commit,
    )


def verify_build_manifest(root: Path, manifest_path: Path) -> None:
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(f"cannot load build manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvaluatorImageError("build manifest schema is invalid")
    expected = value.get("files")
    actual = _file_records(root.resolve(), exclude={BUILD_MANIFEST})
    if expected != actual:
        raise EvaluatorImageError("build manifest does not match staged inputs")


def _verify_wheelhouse(wheelhouse: Path) -> None:
    manifest_path = wheelhouse / "manifest.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(f"cannot load wheel manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvaluatorImageError("wheel manifest schema is invalid")
    expected = value.get("files")
    if not isinstance(expected, dict) or not expected:
        raise EvaluatorImageError("wheel manifest files are invalid")
    actual: dict[str, dict[str, int | str]] = {}
    for path in sorted(wheelhouse.glob("*.whl")):
        payload = path.read_bytes()
        actual[path.name] = {"sha256": _sha256(payload), "bytes": len(payload)}
    if expected != actual:
        raise EvaluatorImageError("wheel manifest does not match wheel files")


def _verify_docker_cli(root: Path) -> None:
    manifest_path = root / "manifest.json"
    executable = root / "docker"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = executable.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(f"cannot load Docker CLI asset: {exc}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("platform") != "linux/amd64"
        or value.get("docker_sha256") != _sha256(payload)
    ):
        raise EvaluatorImageError("Docker CLI manifest does not match binary")


def _tracked_files(repository: Path) -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise EvaluatorImageError(
            completed.stderr.decode("utf-8", errors="replace").strip()
            or "cannot list evaluator files"
        )
    return tuple(
        Path(raw.decode("utf-8"))
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise EvaluatorImageError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _file_records(root: Path, *, exclude: set[str]) -> dict[str, dict[str, int | str]]:
    records: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        if path.is_symlink():
            raise EvaluatorImageError(f"build input is a symlink: {relative}")
        payload = path.read_bytes()
        records[relative] = {"sha256": _sha256(payload), "bytes": len(payload)}
    return records


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _execute_image_command(arguments: list[str]) -> ImageCommandResult:
    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise EvaluatorImageError(
            f"cannot launch Docker image command: {exc}"
        ) from exc
    return ImageCommandResult(completed.returncode, completed.stdout, completed.stderr)


def _require_success(result: ImageCommandResult, operation: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise EvaluatorImageError(f"{operation} failed: {detail}")


def _one_image(payload: str) -> dict:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EvaluatorImageError("evaluator image inspect returned invalid JSON") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise EvaluatorImageError("evaluator image inspect must return one object")
    return value[0]


def _safe_tag(value: str) -> str:
    safe = "".join(
        character.lower() if character.isalnum() else "-"
        for character in value
    ).strip("-")
    return (safe or "run")[:48]
