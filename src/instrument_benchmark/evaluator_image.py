from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .contracts import ContractError
from .repository_layout import ID_PATTERN, resolve_evaluator_leaf


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
    source_id: str
    evaluator_id: str
    source_manifest_sha256: str
    source_tree_sha256: str
    openfibsem_commit: str | None = None
    openfibsem_source_sha256: str | None = None


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
    source_id: str = ""
    evaluator_id: str = ""
    source_manifest_sha256: str = ""
    source_tree_sha256: str = ""
    openfibsem_commit: str | None = None
    openfibsem_source_sha256: str | None = None


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

    def build(
        self,
        evaluator_checkout: Path,
        *,
        run_id: str,
        source_id: str,
        evaluator_id: str,
        openfibsem_checkout: Path | None = None,
        openfibsem_commit: str | None = None,
    ) -> EvaluatorImageEvidence:
        evaluator_checkout = evaluator_checkout.resolve()
        commit_time = _git(evaluator_checkout, "show", "-s", "--format=%ct", "HEAD")
        with tempfile.TemporaryDirectory(prefix="iab-evaluator-build-") as directory:
            context = stage_evaluator_build_context(
                evaluator_checkout,
                self.assets_root,
                Path(directory) / "context",
                source_id=source_id,
                evaluator_id=evaluator_id,
                openfibsem_checkout=openfibsem_checkout,
                openfibsem_commit=openfibsem_commit,
            )
            verify_build_manifest(
                context.root,
                context.manifest_path,
                expected_evaluator_commit=context.evaluator_commit,
            )
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
                    "--label",
                    f"iab.source_id={context.source_id}",
                    "--label",
                    f"iab.evaluator_id={context.evaluator_id}",
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
                source_id=context.source_id,
                evaluator_id=context.evaluator_id,
                source_manifest_sha256=context.source_manifest_sha256,
                source_tree_sha256=context.source_tree_sha256,
                platform=platform,
                user=user,
                openfibsem_commit=context.openfibsem_commit,
                openfibsem_source_sha256=context.openfibsem_source_sha256,
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
    *,
    source_id: str,
    evaluator_id: str,
    openfibsem_checkout: Path | None = None,
    openfibsem_commit: str | None = None,
) -> EvaluatorBuildContext:
    evaluator_checkout = evaluator_checkout.resolve()
    assets_root = assets_root.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise EvaluatorImageError(f"build context already exists: {destination}")
    try:
        selected_leaf = resolve_evaluator_leaf(
            evaluator_checkout, source_id, evaluator_id
        )
    except (ContractError, OSError) as exc:
        raise EvaluatorImageError(str(exc)) from exc
    if _git(evaluator_checkout, "status", "--porcelain"):
        raise EvaluatorImageError("evaluator checkout must be clean")
    _verify_docker_cli(assets_root / "docker-cli")
    _verify_docker_buildx(assets_root / "docker-buildx")
    if (openfibsem_checkout is None) != (openfibsem_commit is None):
        raise EvaluatorImageError(
            "OpenFIBSEM checkout and commit must be supplied together"
        )
    fibsem_profile = openfibsem_checkout is not None
    if fibsem_profile:
        assert openfibsem_commit is not None
        _verify_openfibsem_runtime(assets_root, expected_commit=openfibsem_commit)
        _verify_fibsem_system_packages(assets_root / "fibsem-system-packages")
    else:
        _verify_wheelhouse(assets_root / "wheelhouse")
    destination.mkdir(parents=True)
    evaluator_target = destination / "evaluator"
    evaluator_target.mkdir()
    commit = _git(evaluator_checkout, "rev-parse", "HEAD")
    selected = tuple(
        relative
        for relative in _tracked_files(evaluator_checkout)
        if _selected_evaluator_file(relative, source_id=source_id)
    )
    if selected_leaf.manifest_path.relative_to(evaluator_checkout) not in selected:
        raise EvaluatorImageError("selected evaluator packaging inputs are incomplete")
    for relative in selected:
        source = evaluator_checkout / relative
        if source.is_symlink() or not source.is_file():
            raise EvaluatorImageError(
                f"tracked evaluator input is not a regular file: {relative}"
            )
        target = evaluator_target / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    staged_source = evaluator_target / "sources" / source_id
    staged_source_manifest = staged_source / "source.yaml"
    if staged_source_manifest.is_symlink() or not staged_source_manifest.is_file():
        raise EvaluatorImageError("selected source manifest is not a regular file")
    source_manifest_sha256 = _sha256(staged_source_manifest.read_bytes())
    source_tree_sha256 = _sha256(
        _canonical_json(_file_records(staged_source, exclude=set()))
    )
    profile_inputs = (
        (
            ("fibsem-evaluator.Dockerfile", "evaluator.Dockerfile"),
            ("openfibsem-requirements.lock", "openfibsem-requirements.lock"),
        )
        if fibsem_profile
        else (
            ("evaluator.Dockerfile", "evaluator.Dockerfile"),
            ("evaluator-requirements.lock", "evaluator-requirements.lock"),
        )
    )
    for source_name, target_name in profile_inputs:
        source = assets_root / source_name
        if not source.is_file() or source.is_symlink():
            raise EvaluatorImageError(f"missing evaluator image input: {source_name}")
        shutil.copy2(source, destination / target_name)
    if fibsem_profile:
        _stage_openfibsem_wheelhouse(
            assets_root / "openfibsem-wheelhouse",
            destination / "openfibsem-wheelhouse",
        )
        shutil.copytree(
            assets_root / "fibsem-system-packages",
            destination / "fibsem-system-packages",
        )
    else:
        shutil.copytree(assets_root / "wheelhouse", destination / "wheelhouse")
    shutil.copytree(assets_root / "docker-cli", destination / "docker-cli")
    shutil.copytree(assets_root / "docker-buildx", destination / "docker-buildx")
    source_digest: str | None = None
    if openfibsem_checkout is not None and openfibsem_commit is not None:
        source_digest = _stage_openfibsem_source(
            openfibsem_checkout,
            destination / "openfibsem",
            expected_commit=openfibsem_commit,
        )
    runtime_profile = {
        "schema_version": 1,
        "profile": "fibsem" if fibsem_profile else "default",
        "openfibsem_commit": openfibsem_commit,
        "openfibsem_source_sha256": source_digest,
    }
    (destination / "runtime-profile.json").write_bytes(
        _canonical_json(runtime_profile)
    )
    manifest_path = destination / BUILD_MANIFEST
    manifest = {
        "schema_version": 2,
        "evaluator_commit": commit,
        "source_id": source_id,
        "evaluator_id": evaluator_id,
        "source_manifest_sha256": source_manifest_sha256,
        "source_tree_sha256": source_tree_sha256,
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
        source_id=source_id,
        evaluator_id=evaluator_id,
        source_manifest_sha256=source_manifest_sha256,
        source_tree_sha256=source_tree_sha256,
        openfibsem_commit=openfibsem_commit,
        openfibsem_source_sha256=source_digest,
    )


def verify_build_manifest(
    root: Path,
    manifest_path: Path,
    *,
    expected_evaluator_commit: str,
) -> None:
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(f"cannot load build manifest: {exc}") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "evaluator_commit",
            "source_id",
            "evaluator_id",
            "source_manifest_sha256",
            "source_tree_sha256",
            "files",
        }
        or value.get("schema_version") != 2
    ):
        raise EvaluatorImageError("build manifest schema is invalid")
    if value.get("evaluator_commit") != expected_evaluator_commit:
        raise EvaluatorImageError("build manifest evaluator commit mismatch")
    source_id = value.get("source_id")
    evaluator_id = value.get("evaluator_id")
    if (
        not isinstance(source_id, str)
        or ID_PATTERN.fullmatch(source_id) is None
        or not isinstance(evaluator_id, str)
        or ID_PATTERN.fullmatch(evaluator_id) is None
        or not _is_raw_sha256(value.get("source_manifest_sha256"))
        or not _is_raw_sha256(value.get("source_tree_sha256"))
    ):
        raise EvaluatorImageError("build manifest source identity is invalid")
    source_root = root.resolve() / "evaluator" / "sources" / source_id
    source_manifest = source_root / "source.yaml"
    if source_manifest.is_symlink() or not source_manifest.is_file():
        raise EvaluatorImageError("staged source manifest is not a regular file")
    if value["source_manifest_sha256"] != _sha256(source_manifest.read_bytes()):
        raise EvaluatorImageError("build manifest source manifest digest mismatch")
    source_tree_sha256 = _sha256(
        _canonical_json(_file_records(source_root, exclude=set()))
    )
    if value["source_tree_sha256"] != source_tree_sha256:
        raise EvaluatorImageError("build manifest source tree digest mismatch")
    expected = value.get("files")
    actual = _file_records(root.resolve(), exclude={BUILD_MANIFEST})
    if expected != actual:
        raise EvaluatorImageError("build manifest does not match staged inputs")


def _selected_evaluator_file(relative: Path, *, source_id: str) -> bool:
    return (
        relative == Path("pyproject.toml")
        or relative.parts[:1] == ("instrument_benchmark_evaluator",)
        or relative == Path("sources/__init__.py")
        or relative.parts[:2] == ("sources", source_id)
        or source_id == "pyvisa"
        and relative.parts[:2] == ("vendor", "pyvisa-sim-iab")
    )


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


def _verify_openfibsem_runtime(assets_root: Path, *, expected_commit: str) -> None:
    wheelhouse = assets_root / "openfibsem-wheelhouse"
    manifest_path = wheelhouse / "manifest.json"
    lock_path = assets_root / "openfibsem-requirements.lock"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lock_lines = lock_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(
            f"cannot load OpenFIBSEM wheel manifest: {exc}"
        ) from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "source_commit",
            "source_requirements_sha256",
            "platform",
            "python_version",
            "files",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("source_commit") != expected_commit
        or manifest.get("platform") != "manylinux_2_28_x86_64"
        or manifest.get("python_version") != "311"
        or not _is_raw_sha256(manifest.get("source_requirements_sha256"))
        or not isinstance(files, dict)
        or not files
    ):
        raise EvaluatorImageError(
            "OpenFIBSEM wheel manifest identity or source commit is invalid"
        )
    expected_storage_names = {"manifest.json"}
    expected_lock: dict[str, tuple[str, str]] = {}
    for filename, record in files.items():
        parts = record.get("parts") if isinstance(record, dict) else None
        record_keys = {
            "normalized_name",
            "version",
            "sha256",
            "bytes",
            "platform",
        }
        if parts is not None:
            record_keys.add("parts")
        if (
            not isinstance(filename, str)
            or not filename.endswith(".whl")
            or not isinstance(record, dict)
            or set(record) != record_keys
            or not isinstance(record.get("normalized_name"), str)
            or not record["normalized_name"]
            or not isinstance(record.get("version"), str)
            or not record["version"]
            or not _is_raw_sha256(record.get("sha256"))
            or isinstance(record.get("bytes"), bool)
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] <= 0
            or record.get("platform") not in {"any", "manylinux_x86_64"}
        ):
            raise EvaluatorImageError("OpenFIBSEM wheel record is invalid")
        paths: list[Path] = []
        if parts is None:
            paths.append(wheelhouse / filename)
            expected_storage_names.add(filename)
        elif not isinstance(parts, list) or len(parts) < 2:
            raise EvaluatorImageError("OpenFIBSEM wheel part records are invalid")
        else:
            for index, part_record in enumerate(parts):
                if (
                    not isinstance(part_record, dict)
                    or set(part_record) != {"filename", "sha256", "bytes"}
                    or part_record.get("filename") != f"{filename}.part{index:03d}"
                    or not _is_raw_sha256(part_record.get("sha256"))
                    or isinstance(part_record.get("bytes"), bool)
                    or not isinstance(part_record.get("bytes"), int)
                    or part_record["bytes"] <= 0
                ):
                    raise EvaluatorImageError("OpenFIBSEM wheel part record is invalid")
                part = wheelhouse / part_record["filename"]
                if part.is_symlink() or not part.is_file():
                    raise EvaluatorImageError(
                        "OpenFIBSEM wheel part is not a regular file"
                    )
                payload = part.read_bytes()
                if (
                    len(payload) != part_record["bytes"]
                    or _sha256(payload) != part_record["sha256"]
                ):
                    raise EvaluatorImageError("OpenFIBSEM wheel part hash mismatch")
                paths.append(part)
                expected_storage_names.add(part.name)
        digest = hashlib.sha256()
        size = 0
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise EvaluatorImageError("OpenFIBSEM wheel is not a regular file")
            payload = path.read_bytes()
            digest.update(payload)
            size += len(payload)
        if size != record["bytes"] or digest.hexdigest() != record["sha256"]:
            raise EvaluatorImageError("OpenFIBSEM wheel hash does not match manifest")
        name = record["normalized_name"]
        if name in expected_lock:
            raise EvaluatorImageError("OpenFIBSEM wheel package is duplicated")
        expected_lock[name] = (record["version"], record["sha256"])
    if _parse_hash_lock(lock_lines) != expected_lock:
        raise EvaluatorImageError("OpenFIBSEM requirement lock does not match wheels")
    actual_storage_names = {path.name for path in wheelhouse.iterdir()}
    if actual_storage_names != expected_storage_names:
        raise EvaluatorImageError("OpenFIBSEM wheel manifest file set is invalid")


def _stage_openfibsem_wheelhouse(source: Path, destination: Path) -> None:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    destination.mkdir()
    staged_manifest = dict(manifest)
    staged_files: dict[str, dict[str, object]] = {}
    for filename, source_record in manifest["files"].items():
        record = dict(source_record)
        parts = record.pop("parts", None)
        target = destination / filename
        if parts is None:
            shutil.copy2(source / filename, target)
        else:
            with target.open("wb") as output:
                for part_record in parts:
                    with (source / part_record["filename"]).open("rb") as part:
                        shutil.copyfileobj(part, output)
        staged_files[filename] = record
    staged_manifest["files"] = staged_files
    (destination / "manifest.json").write_bytes(_canonical_json(staged_manifest))


def _verify_fibsem_system_packages(root: Path) -> None:
    expected_packages = {
        "gcc-12-base",
        "libatomic1",
        "libbsd0",
        "libedit2",
        "libicu72",
        "libllvm15",
        "libxml2",
        "libz3-4",
    }
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(
            f"cannot load FIBSEM system package manifest: {exc}"
        ) from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    packages = manifest.get("packages") if isinstance(manifest, dict) else None
    package_identity = (
        isinstance(packages, dict)
        and set(packages) == expected_packages
        and all(isinstance(value, str) and value for value in packages.values())
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {"schema_version", "distribution", "architecture", "packages", "files"}
        or manifest.get("schema_version") != 1
        or manifest.get("distribution") != "debian-bookworm"
        or manifest.get("architecture") != "amd64"
        or not package_identity
    ):
        raise EvaluatorImageError("FIBSEM system package manifest identity is invalid")
    assert isinstance(packages, dict)
    if not isinstance(files, dict) or not files:
        raise EvaluatorImageError("FIBSEM system package records are invalid")
    actual_names = {path.name for path in root.glob("*.deb")}
    if set(files) != actual_names:
        raise EvaluatorImageError("FIBSEM system package file set is invalid")
    seen: dict[str, str] = {}
    for filename, record in files.items():
        if (
            not isinstance(filename, str)
            or not filename.endswith("_amd64.deb")
            or not isinstance(record, dict)
            or set(record) != {"package", "version", "sha256", "bytes"}
            or not isinstance(record.get("package"), str)
            or not isinstance(record.get("version"), str)
            or not _is_raw_sha256(record.get("sha256"))
            or isinstance(record.get("bytes"), bool)
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] <= 0
        ):
            raise EvaluatorImageError("FIBSEM system package record is invalid")
        path = root / filename
        if path.is_symlink() or not path.is_file():
            raise EvaluatorImageError("FIBSEM system package is not a regular file")
        payload = path.read_bytes()
        if len(payload) != record["bytes"] or _sha256(payload) != record["sha256"]:
            raise EvaluatorImageError("FIBSEM system package hash mismatch")
        seen[record["package"]] = record["version"]
    if seen != packages:
        raise EvaluatorImageError("FIBSEM system package versions are inconsistent")


def _parse_hash_lock(lines: list[str]) -> dict[str, tuple[str, str]]:
    records: dict[str, tuple[str, str]] = {}
    pending: tuple[str, str] | None = None
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line.endswith(" \\") and pending is None:
            requirement = line[:-2]
            if "==" not in requirement:
                raise EvaluatorImageError("OpenFIBSEM requirement is not pinned")
            name, version = requirement.split("==", 1)
            if not name or not version:
                raise EvaluatorImageError("OpenFIBSEM requirement is invalid")
            pending = (name, version)
            continue
        prefix = "    --hash=sha256:"
        if line.startswith(prefix) and pending is not None:
            digest = line.removeprefix(prefix)
            if not _is_raw_sha256(digest):
                raise EvaluatorImageError("OpenFIBSEM requirement hash is invalid")
            name, version = pending
            if name in records:
                raise EvaluatorImageError("OpenFIBSEM requirement is duplicated")
            records[name] = (version, digest)
            pending = None
            continue
        raise EvaluatorImageError("OpenFIBSEM requirement lock is invalid")
    if pending is not None or not records:
        raise EvaluatorImageError("OpenFIBSEM requirement lock is incomplete")
    return records


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


def _verify_docker_buildx(root: Path) -> None:
    manifest_path = root / "manifest.json"
    executable = root / "docker-buildx"
    source = (
        "https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/"
        "amd64/docker-buildx-plugin_0.30.1-1~ubuntu.22.04~jammy_amd64.deb"
    )
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = executable.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorImageError(f"cannot load Docker Buildx asset: {exc}") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "version",
            "platform",
            "source",
            "package",
            "package_sha256",
            "buildx_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("version") != "0.30.1"
        or value.get("platform") != "linux/amd64"
        or value.get("source") != source
        or value.get("package")
        != "docker-buildx-plugin=0.30.1-1~ubuntu.22.04~jammy"
        or value.get("package_sha256")
        != "c550ca2fcca56836605b58c64c6a89e198bb9f757d8978e4060a82227bda9c98"
        or value.get("buildx_sha256") != _sha256(payload)
    ):
        raise EvaluatorImageError("Docker Buildx manifest does not match binary")


def _stage_openfibsem_source(
    checkout: Path,
    destination: Path,
    *,
    expected_commit: str,
) -> str:
    checkout = checkout.resolve()
    if _git(checkout, "rev-parse", "--show-toplevel") != str(checkout):
        raise EvaluatorImageError("OpenFIBSEM checkout is not a repository root")
    if _git(checkout, "rev-parse", "HEAD") != expected_commit:
        raise EvaluatorImageError("OpenFIBSEM checkout commit mismatch")
    _require_tracked_clean(checkout, "OpenFIBSEM")
    allowed_root = {"pyproject.toml", "setup.py", "LICENSE", "MANIFEST.in"}
    selected = tuple(
        relative
        for relative in _tracked_files(checkout)
        if relative.parts[0] == "fibsem" or relative.as_posix() in allowed_root
    )
    required = {"pyproject.toml", "setup.py", "LICENSE"}
    if not required.issubset(relative.as_posix() for relative in selected):
        raise EvaluatorImageError("OpenFIBSEM packaging inputs are incomplete")
    destination.mkdir()
    for relative in selected:
        source = checkout / relative
        if source.is_symlink() or not source.is_file():
            raise EvaluatorImageError(
                f"OpenFIBSEM input is not a regular file: {relative}"
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    records = _file_records(destination, exclude=set())
    if not records:
        raise EvaluatorImageError("OpenFIBSEM source selection is empty")
    return _sha256(_canonical_json(records))


def _require_tracked_clean(repository: Path, label: str) -> None:
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode == 1:
            raise EvaluatorImageError(f"{label} checkout has tracked modifications")
        if completed.returncode != 0:
            raise EvaluatorImageError(
                completed.stderr.strip() or f"cannot verify {label} checkout"
            )


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


def _is_raw_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


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
