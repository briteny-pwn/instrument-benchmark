from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.evaluator_image import (  # noqa: E402
    EvaluatorImageBuilder,
    EvaluatorImageError,
    ImageCommandResult,
    stage_evaluator_build_context,
    verify_build_manifest,
)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def file_records(root: Path) -> dict[str, dict[str, int | str]]:
    records: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            records[path.relative_to(root).as_posix()] = {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
    return records


class EvaluatorImageTests(unittest.TestCase):
    PYVISA_SOURCE = "pyvisa"
    PYVISA_EVALUATOR = "pyvisa_dut_validation_v2"
    FIBSEM_SOURCE = "openfibsem"
    FIBSEM_EVALUATOR = "fibsem_liftout_v1"

    def stage(
        self,
        evaluator: Path,
        assets: Path,
        destination: Path,
        *,
        source_id: str = PYVISA_SOURCE,
        evaluator_id: str = PYVISA_EVALUATOR,
        openfibsem_checkout: Path | None = None,
        openfibsem_commit: str | None = None,
    ):
        return stage_evaluator_build_context(
            evaluator,
            assets,
            destination,
            source_id=source_id,
            evaluator_id=evaluator_id,
            openfibsem_checkout=openfibsem_checkout,
            openfibsem_commit=openfibsem_commit,
        )

    def make_openfibsem(self, root: Path) -> tuple[Path, str]:
        checkout = root / "openfibsem"
        checkout.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=checkout, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=checkout,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=checkout,
            check=True,
        )
        package = checkout / "fibsem" / "model3d"
        package.mkdir(parents=True)
        (checkout / "fibsem" / "__init__.py").write_text("")
        (package / "simulator.py").write_text("PINNED = True\n")
        (package / "sample.stl").write_bytes(b"solid sample\nendsolid sample\n")
        (checkout / "pyproject.toml").write_text("[project]\nname='fibsem'\nversion='1'\n")
        (checkout / "setup.py").write_text("from setuptools import setup\nsetup()\n")
        (checkout / "LICENSE").write_text("fixture")
        (checkout / "README.md").write_text("not staged")
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=checkout, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        return checkout, commit

    def test_fibsem_context_stages_only_pinned_tracked_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            context = self.stage(
                self.make_evaluator(root),
                self.make_assets(root, source_commit=commit),
                root / "context",
                source_id=self.FIBSEM_SOURCE,
                evaluator_id=self.FIBSEM_EVALUATOR,
                openfibsem_checkout=checkout,
                openfibsem_commit=commit,
            )

            staged = context.root / "openfibsem"
            self.assertTrue((staged / "fibsem/model3d/simulator.py").is_file())
            self.assertTrue((staged / "fibsem/model3d/sample.stl").is_file())
            self.assertFalse((staged / "README.md").exists())
            self.assertEqual(context.openfibsem_commit, commit)
            self.assertEqual(len(context.openfibsem_source_sha256), 64)
            profile = json.loads(
                (context.root / "runtime-profile.json").read_text()
            )
            self.assertEqual(profile["profile"], "fibsem")
            self.assertEqual(profile["openfibsem_commit"], commit)
            self.assertFalse((context.root / "evaluator-requirements.lock").exists())
            self.assertFalse((context.root / "wheelhouse").exists())
            self.assertTrue((context.root / "openfibsem-requirements.lock").is_file())
            self.assertTrue(
                (context.root / "openfibsem-wheelhouse" / "manifest.json").is_file()
            )
            self.assertTrue(
                (context.root / "fibsem-system-packages" / "manifest.json").is_file()
            )
            verify_build_manifest(
                context.root,
                context.manifest_path,
                expected_evaluator_commit=context.evaluator_commit,
            )

    def test_fibsem_context_rejects_commit_mismatch_and_tracked_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root, source_commit=commit)

            with self.assertRaisesRegex(EvaluatorImageError, "commit"):
                self.stage(
                    evaluator,
                    assets,
                    root / "wrong-context",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit="0" * 40,
                )

            (checkout / "fibsem/model3d/simulator.py").write_text("changed\n")
            with self.assertRaisesRegex(EvaluatorImageError, "tracked"):
                self.stage(
                    evaluator,
                    assets,
                    root / "dirty-context",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )

    def test_stage_requires_openfibsem_inputs_for_exact_fibsem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(EvaluatorImageError, "required"):
                self.stage(
                    self.make_evaluator(root),
                    self.make_assets(root),
                    root / "context",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                )

    def test_stage_forbids_openfibsem_inputs_for_non_fibsem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            with self.assertRaisesRegex(EvaluatorImageError, "only valid"):
                self.stage(
                    self.make_evaluator(root),
                    self.make_assets(root, source_commit=commit),
                    root / "context",
                    source_id=self.PYVISA_SOURCE,
                    evaluator_id=self.PYVISA_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )

    def test_fibsem_context_rejects_tampered_runtime_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            assets = self.make_assets(root, source_commit=commit)
            wheel = next((assets / "openfibsem-wheelhouse").glob("*.whl"))
            wheel.write_bytes(wheel.read_bytes() + b"tampered")

            with self.assertRaisesRegex(EvaluatorImageError, "OpenFIBSEM wheel"):
                self.stage(
                    self.make_evaluator(root),
                    assets,
                    root / "context",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )

    def test_fibsem_context_reassembles_split_runtime_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            assets = self.make_assets(root, source_commit=commit)
            wheelhouse = assets / "openfibsem-wheelhouse"
            wheel = next(wheelhouse.glob("*.whl"))
            payload = wheel.read_bytes()
            split_at = len(payload) // 2
            part_records = []
            for index, data in enumerate((payload[:split_at], payload[split_at:])):
                part = wheelhouse / f"{wheel.name}.part{index:03d}"
                part.write_bytes(data)
                part_records.append(
                    {
                        "filename": part.name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                )
            manifest_path = wheelhouse / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"][wheel.name]["parts"] = part_records
            manifest_path.write_text(json.dumps(manifest, sort_keys=True))
            wheel.unlink()

            context = self.stage(
                self.make_evaluator(root),
                assets,
                root / "context",
                source_id=self.FIBSEM_SOURCE,
                evaluator_id=self.FIBSEM_EVALUATOR,
                openfibsem_checkout=checkout,
                openfibsem_commit=commit,
            )

            staged = context.root / "openfibsem-wheelhouse" / wheel.name
            self.assertEqual(staged.read_bytes(), payload)
            self.assertFalse(
                any((context.root / "openfibsem-wheelhouse").glob("*.part*"))
            )

    def test_fibsem_context_rejects_tampered_system_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            assets = self.make_assets(root, source_commit=commit)
            package = next((assets / "fibsem-system-packages").glob("*.deb"))
            package.write_bytes(package.read_bytes() + b"tampered")

            with self.assertRaisesRegex(EvaluatorImageError, "system package"):
                self.stage(
                    self.make_evaluator(root),
                    assets,
                    root / "context",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )

    def test_real_context_installs_hooked_sim_fork_before_evaluator(self) -> None:
        evaluator = ROOT.parent / "evaluator"
        if not evaluator.is_dir():
            evaluator = ROOT.parents[2] / "evaluator" / ".worktrees" / ROOT.name
        evaluator = evaluator.resolve()
        with tempfile.TemporaryDirectory() as directory:
            context = self.stage(
                evaluator,
                ROOT / "container",
                Path(directory) / "context",
                source_id=self.PYVISA_SOURCE,
                evaluator_id=self.PYVISA_EVALUATOR,
            )
            vendor = context.root / "evaluator" / "vendor" / "pyvisa-sim-iab"
            self.assertTrue((vendor / "pyproject.toml").is_file())
            self.assertTrue((vendor / "pyvisa_sim" / "hooks.py").is_file())

        dockerfile = (ROOT / "container" / "evaluator.Dockerfile").read_text()
        normalized = " ".join(dockerfile.replace("\\", "").split())
        fork_install = (
            "python -m pip install --no-index --no-deps --no-build-isolation "
            "/build/evaluator/vendor/pyvisa-sim-iab"
        )
        evaluator_install = (
            "python -m pip install --no-index --no-deps --no-build-isolation "
            "/build/evaluator"
        )
        self.assertIn(fork_install, normalized)
        self.assertIn(evaluator_install, normalized)
        fork_index = normalized.index(fork_install)
        evaluator_index = normalized.index(
            evaluator_install, fork_index + len(fork_install)
        )
        self.assertLess(fork_index, evaluator_index)

    def make_evaluator(self, root: Path) -> Path:
        evaluator = root / "evaluator"
        evaluator.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=evaluator, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=evaluator,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=evaluator,
            check=True,
        )
        (evaluator / "pyproject.toml").write_text("[project]\nname='fake'\nversion='1'\n")
        package = evaluator / "instrument_benchmark_evaluator"
        package.mkdir()
        (package / "__init__.py").write_text("")
        sources = evaluator / "sources"
        sources.mkdir()
        (sources / "__init__.py").write_text("")
        pyvisa = sources / self.PYVISA_SOURCE
        pyvisa.mkdir()
        (pyvisa / "__init__.py").write_text("")
        (pyvisa / "source.yaml").write_text(
            "schema_version: 1\n"
            "source_id: pyvisa\n"
            "display_name: PyVISA\n"
            "description: Trusted PyVISA evaluators\n"
            "evaluators:\n"
            "  - pyvisa_dut_validation_v1\n"
            "  - pyvisa_dut_validation_v2\n"
        )
        for evaluator_id in (
            "pyvisa_dut_validation_v1",
            "pyvisa_dut_validation_v2",
        ):
            leaf = pyvisa / evaluator_id
            leaf.mkdir()
            (leaf / "__init__.py").write_text("")
            (leaf / "evaluator.yaml").write_text(
                "schema_version: 2\n"
                "source_id: pyvisa\n"
                f"evaluator_id: {evaluator_id}\n"
                "protocol_version: 2\n"
                "container_protocol_version: 1\n"
                "supported_instances:\n"
                f"  - {evaluator_id}\n"
            )
            (leaf / "implementation.py").write_text(
                f"EVALUATOR_ID = {evaluator_id!r}\n"
            )
        openfibsem = sources / self.FIBSEM_SOURCE
        openfibsem.mkdir()
        (openfibsem / "__init__.py").write_text("")
        (openfibsem / "source.yaml").write_text(
            "schema_version: 1\n"
            "source_id: openfibsem\n"
            "display_name: OpenFIBSEM\n"
            "description: Trusted FIBSEM evaluators\n"
            "evaluators:\n"
            "  - fibsem_liftout_v1\n"
        )
        fibsem_leaf = openfibsem / self.FIBSEM_EVALUATOR
        fibsem_leaf.mkdir()
        (fibsem_leaf / "__init__.py").write_text("")
        (fibsem_leaf / "evaluator.yaml").write_text(
            "schema_version: 2\n"
            "source_id: openfibsem\n"
            "evaluator_id: fibsem_liftout_v1\n"
            "protocol_version: 2\n"
            "container_protocol_version: 1\n"
            "supported_instances:\n"
            "  - fibsem_liftout_v1\n"
        )
        (fibsem_leaf / "implementation.py").write_text("FIBSEM = True\n")
        vendor = evaluator / "vendor" / "pyvisa-sim-iab" / "pyvisa_sim"
        vendor.mkdir(parents=True)
        (vendor.parent / "pyproject.toml").write_text(
            "[project]\nname='pyvisa-sim-iab'\nversion='1'\n"
        )
        (vendor / "__init__.py").write_text("")
        (vendor / "hooks.py").write_text("HOOKED = True\n")
        (evaluator / ".gitignore").write_text("__pycache__/\nreports/\n")
        subprocess.run(["git", "add", "."], cwd=evaluator, check=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=evaluator, check=True)
        (package / "__pycache__").mkdir()
        (package / "__pycache__" / "ignored.pyc").write_bytes(b"cache")
        (evaluator / "reports").mkdir()
        (evaluator / "reports" / "ignored.json").write_text("{}")
        return evaluator

    def make_assets(self, root: Path, *, source_commit: str = "fixture") -> Path:
        assets = root / "assets"
        wheels = assets / "wheelhouse"
        wheels.mkdir(parents=True)
        dockerfile = assets / "evaluator.Dockerfile"
        dockerfile.write_text("FROM scratch\n")
        (assets / "fibsem-evaluator.Dockerfile").write_text("FROM scratch\n")
        lock = assets / "evaluator-requirements.lock"
        lock.write_text("fake==1 --hash=sha256:" + "1" * 64 + "\n")
        wheel = wheels / "fake-1-py3-none-any.whl"
        wheel.write_bytes(b"wheel")
        manifest = {
            "schema_version": 1,
            "files": {
                wheel.name: {
                    "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    "bytes": len(wheel.read_bytes()),
                }
            },
        }
        (wheels / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
        openfibsem_wheels = assets / "openfibsem-wheelhouse"
        openfibsem_wheels.mkdir()
        runtime_wheel = openfibsem_wheels / "numpy-1.0-py3-none-any.whl"
        runtime_wheel.write_bytes(b"runtime-wheel")
        runtime_digest = hashlib.sha256(runtime_wheel.read_bytes()).hexdigest()
        (openfibsem_wheels / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "python_version": "311",
                    "platform": "manylinux_2_28_x86_64",
                    "source_commit": source_commit,
                    "source_requirements_sha256": "2" * 64,
                    "files": {
                        runtime_wheel.name: {
                            "normalized_name": "numpy",
                            "version": "1.0",
                            "sha256": runtime_digest,
                            "bytes": len(runtime_wheel.read_bytes()),
                            "platform": "any",
                        }
                    },
                },
                sort_keys=True,
            )
        )
        lock_text = (
            "numpy==1.0 \\\n"
            f"    --hash=sha256:{runtime_digest}\n"
        )
        (assets / "openfibsem-requirements.lock").write_text(lock_text)
        system_packages = assets / "fibsem-system-packages"
        system_packages.mkdir()
        package_records = {}
        required_system_packages = (
            "gcc-12-base",
            "libatomic1",
            "libbsd0",
            "libedit2",
            "libicu72",
            "libllvm15",
            "libxml2",
            "libz3-4",
        )
        for package in required_system_packages:
            deb = system_packages / f"{package}_1.0_amd64.deb"
            deb.write_bytes(f"system-package:{package}".encode())
            package_records[deb.name] = {
                "package": package,
                "version": "1.0",
                "sha256": hashlib.sha256(deb.read_bytes()).hexdigest(),
                "bytes": len(deb.read_bytes()),
            }
        (system_packages / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "distribution": "debian-bookworm",
                    "architecture": "amd64",
                    "packages": {
                        package: "1.0" for package in required_system_packages
                    },
                    "files": package_records,
                },
                sort_keys=True,
            )
        )
        docker_cli = assets / "docker-cli"
        docker_cli.mkdir()
        docker = docker_cli / "docker"
        docker.write_bytes(b"fake-static-docker")
        (docker_cli / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "platform": "linux/amd64",
                    "docker_sha256": hashlib.sha256(docker.read_bytes()).hexdigest(),
                }
            )
        )
        docker_buildx = assets / "docker-buildx"
        docker_buildx.mkdir()
        buildx = docker_buildx / "docker-buildx"
        buildx.write_bytes(b"fake-static-buildx")
        (docker_buildx / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "version": "0.30.1",
                    "platform": "linux/amd64",
                    "source": (
                        "https://download.docker.com/linux/ubuntu/dists/jammy/"
                        "pool/stable/amd64/docker-buildx-plugin_"
                        "0.30.1-1~ubuntu.22.04~jammy_amd64.deb"
                    ),
                    "package": (
                        "docker-buildx-plugin=0.30.1-1~ubuntu.22.04~jammy"
                    ),
                    "package_sha256": (
                        "c550ca2fcca56836605b58c64c6a89e198bb9f757d8978e4060a82227bda9c98"
                    ),
                    "buildx_sha256": hashlib.sha256(
                        buildx.read_bytes()
                    ).hexdigest(),
                }
            )
        )
        return assets

    def test_stage_contains_only_tracked_evaluator_and_verified_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            destination = root / "context"

            context = self.stage(
                evaluator,
                assets,
                destination,
            )

            self.assertTrue((destination / "evaluator" / "pyproject.toml").is_file())
            self.assertFalse((destination / "evaluator" / ".git").exists())
            self.assertFalse(
                (destination / "evaluator" / "instrument_benchmark_evaluator" / "__pycache__").exists()
            )
            self.assertFalse((destination / "evaluator" / "reports").exists())
            self.assertTrue((destination / "docker-cli" / "docker").is_file())
            self.assertTrue(
                (destination / "docker-buildx" / "docker-buildx").is_file()
            )
            self.assertEqual(len(context.evaluator_commit), 40)
            verify_build_manifest(
                context.root,
                context.manifest_path,
                expected_evaluator_commit=context.evaluator_commit,
            )

    def test_source_selection_and_provenance_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            openfibsem_checkout, openfibsem_commit = self.make_openfibsem(root)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root, source_commit=openfibsem_commit)

            pyvisa = self.stage(evaluator, assets, root / "pyvisa-context")
            pyvisa_root = pyvisa.root / "evaluator"
            self.assertTrue((pyvisa_root / "pyproject.toml").is_file())
            self.assertTrue((pyvisa_root / "instrument_benchmark_evaluator").is_dir())
            self.assertTrue((pyvisa_root / "sources" / "__init__.py").is_file())
            self.assertTrue((pyvisa_root / "sources" / "pyvisa").is_dir())
            self.assertTrue(
                (
                    pyvisa_root
                    / "sources/pyvisa/pyvisa_dut_validation_v1/implementation.py"
                ).is_file()
            )
            self.assertTrue((pyvisa_root / "vendor" / "pyvisa-sim-iab").is_dir())
            self.assertFalse((pyvisa_root / "sources" / "openfibsem").exists())

            manifest = json.loads(pyvisa.manifest_path.read_text())
            expected_source = pyvisa_root / "sources" / "pyvisa"
            expected_source_manifest = hashlib.sha256(
                (expected_source / "source.yaml").read_bytes()
            ).hexdigest()
            expected_source_tree = hashlib.sha256(
                canonical_json(file_records(expected_source))
            ).hexdigest()
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["evaluator_commit"], pyvisa.evaluator_commit)
            self.assertEqual(manifest["source_id"], self.PYVISA_SOURCE)
            self.assertEqual(manifest["evaluator_id"], self.PYVISA_EVALUATOR)
            self.assertIsNotNone(
                re.fullmatch(r"[0-9a-f]{64}", manifest["source_manifest_sha256"])
            )
            self.assertIsNotNone(
                re.fullmatch(r"[0-9a-f]{64}", manifest["source_tree_sha256"])
            )
            self.assertEqual(
                manifest["source_manifest_sha256"], expected_source_manifest
            )
            self.assertEqual(manifest["source_tree_sha256"], expected_source_tree)
            self.assertIsInstance(manifest["files"], dict)
            self.assertTrue(manifest["files"])
            self.assertEqual(pyvisa.source_id, self.PYVISA_SOURCE)
            self.assertEqual(pyvisa.evaluator_id, self.PYVISA_EVALUATOR)
            self.assertEqual(
                pyvisa.source_manifest_sha256, expected_source_manifest
            )
            self.assertEqual(pyvisa.source_tree_sha256, expected_source_tree)

            fibsem = self.stage(
                evaluator,
                assets,
                root / "fibsem-context",
                source_id=self.FIBSEM_SOURCE,
                evaluator_id=self.FIBSEM_EVALUATOR,
                openfibsem_checkout=openfibsem_checkout,
                openfibsem_commit=openfibsem_commit,
            )
            fibsem_root = fibsem.root / "evaluator"
            self.assertTrue(
                (
                    fibsem_root
                    / "sources/openfibsem/fibsem_liftout_v1/implementation.py"
                ).is_file()
            )
            self.assertFalse((fibsem_root / "sources" / "pyvisa").exists())
            self.assertFalse((fibsem_root / "vendor" / "pyvisa-sim-iab").exists())

    def test_source_resolution_rejects_missing_unregistered_and_symlinked_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = self.make_assets(root)

            with self.assertRaisesRegex(EvaluatorImageError, "source"):
                self.stage(
                    self.make_evaluator(root),
                    assets,
                    root / "missing",
                    source_id="missing",
                    evaluator_id="missing_evaluator",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            with self.assertRaisesRegex(EvaluatorImageError, "registered|leaf"):
                self.stage(
                    evaluator,
                    self.make_assets(root),
                    root / "unregistered",
                    evaluator_id="unregistered_evaluator",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            source = evaluator / "sources" / self.PYVISA_SOURCE
            target = evaluator / "real-pyvisa"
            source.rename(target)
            source.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(EvaluatorImageError, "symlink"):
                self.stage(
                    evaluator,
                    self.make_assets(root),
                    root / "symlink",
                )

    def test_evaluator_checkout_must_be_clean_even_for_other_source_content(self) -> None:
        for untracked in (False, True):
            with (
                self.subTest(untracked=untracked),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                evaluator = self.make_evaluator(root)
                other_source = evaluator / "sources" / self.FIBSEM_SOURCE
                if untracked:
                    (other_source / "untracked.txt").write_text("untracked\n")
                else:
                    tracked = other_source / self.FIBSEM_EVALUATOR / "implementation.py"
                    tracked.write_text("DIRTY = True\n")
                with self.assertRaisesRegex(
                    EvaluatorImageError, "evaluator checkout must be clean"
                ):
                    self.stage(
                        evaluator,
                        self.make_assets(root),
                        root / "dirty",
                    )

    def test_selected_tracked_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            link = evaluator / "sources" / self.PYVISA_SOURCE / "linked.py"
            link.symlink_to("../../instrument_benchmark_evaluator/__init__.py")
            subprocess.run(["git", "add", str(link)], cwd=evaluator, check=True)
            subprocess.run(
                ["git", "commit", "-m", "tracked symlink"], cwd=evaluator, check=True
            )
            with self.assertRaisesRegex(EvaluatorImageError, "regular file"):
                self.stage(evaluator, self.make_assets(root), root / "context")

    def test_manifest_verification_recomputes_commit_and_source_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self.stage(
                self.make_evaluator(root),
                self.make_assets(root),
                root / "context",
            )
            with self.assertRaisesRegex(EvaluatorImageError, "commit"):
                verify_build_manifest(
                    context.root,
                    context.manifest_path,
                    expected_evaluator_commit="0" * 40,
                )

            selected = (
                context.root
                / "evaluator"
                / "sources"
                / self.PYVISA_SOURCE
                / self.PYVISA_EVALUATOR
                / "implementation.py"
            )
            selected.write_text("TAMPERED = True\n")
            manifest = json.loads(context.manifest_path.read_text())
            manifest["files"] = file_records(context.root)
            manifest["files"].pop(context.manifest_path.name)
            context.manifest_path.write_bytes(canonical_json(manifest))
            with self.assertRaisesRegex(EvaluatorImageError, "source tree"):
                verify_build_manifest(
                    context.root,
                    context.manifest_path,
                    expected_evaluator_commit=context.evaluator_commit,
                )

    def test_build_manifest_detects_staged_input_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self.stage(
                self.make_evaluator(root),
                self.make_assets(root),
                root / "context",
            )
            staged = context.root / "evaluator" / "pyproject.toml"
            staged.write_text(staged.read_text() + "# changed\n")

            with self.assertRaisesRegex(EvaluatorImageError, "manifest"):
                verify_build_manifest(
                    context.root,
                    context.manifest_path,
                    expected_evaluator_commit=context.evaluator_commit,
                )

    def test_wheel_manifest_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            (assets / "wheelhouse" / "fake-1-py3-none-any.whl").write_bytes(b"changed")

            with self.assertRaisesRegex(EvaluatorImageError, "wheel"):
                self.stage(evaluator, assets, root / "context")

    def test_docker_cli_manifest_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            (assets / "docker-cli" / "docker").write_bytes(b"changed")

            with self.assertRaisesRegex(EvaluatorImageError, "Docker CLI"):
                self.stage(evaluator, assets, root / "context")

    def test_docker_buildx_manifest_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            (assets / "docker-buildx" / "docker-buildx").write_bytes(b"changed")

            with self.assertRaisesRegex(EvaluatorImageError, "Buildx"):
                self.stage(evaluator, assets, root / "context")

    def test_trusted_dockerfiles_install_verified_buildx_plugin(self) -> None:
        expected_hash = (
            "a5a4fbd515283ebf05c450bc5b5fabaeeea3f7ac55c322ec310a016005df45a0"
        )
        for name in ("evaluator.Dockerfile", "fibsem-evaluator.Dockerfile"):
            with self.subTest(name=name):
                text = (ROOT / "container" / name).read_text(encoding="utf-8")
                self.assertIn(
                    "COPY docker-buildx/docker-buildx "
                    "/usr/libexec/docker/cli-plugins/docker-buildx",
                    text,
                )
                self.assertIn(expected_hash, text)
                self.assertIn("docker buildx version", text)

    def test_builder_uses_offline_linux_build_and_validates_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            calls: list[list[str]] = []

            def execute(arguments: list[str]) -> ImageCommandResult:
                calls.append(arguments)
                if arguments[:2] == ["docker", "build"]:
                    return ImageCommandResult(0, "", "")
                if arguments[:3] == ["docker", "image", "inspect"]:
                    return ImageCommandResult(
                        0,
                        json.dumps(
                            [
                                {
                                    "Id": "sha256:" + "a" * 64,
                                    "RepoDigests": [],
                                    "Architecture": "amd64",
                                    "Os": "linux",
                                    "Config": {"User": "11001:11001"},
                                }
                            ]
                        ),
                        "",
                    )
                if arguments[:3] == ["docker", "image", "rm"]:
                    return ImageCommandResult(0, "removed", "")
                raise AssertionError(arguments)

            evidence = EvaluatorImageBuilder(
                assets_root=assets,
                executor=execute,
            ).build(
                evaluator,
                run_id="run 1",
                source_id=self.PYVISA_SOURCE,
                evaluator_id=self.PYVISA_EVALUATOR,
            )

            build = next(call for call in calls if call[:2] == ["docker", "build"])
            self.assertIn("--network=none", build)
            self.assertIn("--platform=linux/amd64", build)
            self.assertIn("--pull=false", build)
            self.assertTrue(evidence.reference.startswith("iab/evaluator:run-1-"))
            self.assertEqual(evidence.image_id, "sha256:" + "a" * 64)
            self.assertEqual(evidence.user, "11001:11001")
            self.assertEqual(evidence.source_id, self.PYVISA_SOURCE)
            self.assertEqual(evidence.evaluator_id, self.PYVISA_EVALUATOR)
            self.assertRegex(evidence.source_manifest_sha256, r"^[0-9a-f]{64}$")
            self.assertRegex(evidence.source_tree_sha256, r"^[0-9a-f]{64}$")
            self.assertIn("iab.source_id=pyvisa", build)
            self.assertIn("iab.evaluator_id=pyvisa_dut_validation_v2", build)
            EvaluatorImageBuilder(
                assets_root=assets,
                executor=execute,
            ).remove(evidence)
            self.assertIn(["docker", "image", "rm", evidence.reference], calls)

    def test_builder_requires_openfibsem_inputs_for_exact_fibsem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(EvaluatorImageError, "required"):
                EvaluatorImageBuilder(
                    assets_root=self.make_assets(root),
                    executor=lambda _: ImageCommandResult(1, "", "must not execute"),
                ).build(
                    self.make_evaluator(root),
                    run_id="run",
                    source_id=self.FIBSEM_SOURCE,
                    evaluator_id=self.FIBSEM_EVALUATOR,
                )

    def test_builder_forbids_openfibsem_inputs_for_non_fibsem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            with self.assertRaisesRegex(EvaluatorImageError, "only valid"):
                EvaluatorImageBuilder(
                    assets_root=self.make_assets(root, source_commit=commit),
                    executor=lambda _: ImageCommandResult(1, "", "must not execute"),
                ).build(
                    self.make_evaluator(root),
                    run_id="run",
                    source_id=self.PYVISA_SOURCE,
                    evaluator_id=self.PYVISA_EVALUATOR,
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )

    def test_builder_rejects_wrong_platform_or_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)

            def execute(arguments: list[str]) -> ImageCommandResult:
                if arguments[:2] == ["docker", "build"]:
                    return ImageCommandResult(0, "", "")
                return ImageCommandResult(
                    0,
                    json.dumps(
                        [
                            {
                                "Id": "sha256:" + "a" * 64,
                                "RepoDigests": [],
                                "Architecture": "arm64",
                                "Os": "linux",
                                "Config": {"User": "0:0"},
                            }
                        ]
                    ),
                    "",
                )

            with self.assertRaisesRegex(EvaluatorImageError, "platform|user"):
                EvaluatorImageBuilder(
                    assets_root=assets,
                    executor=execute,
                ).build(
                    evaluator,
                    run_id="run",
                    source_id=self.PYVISA_SOURCE,
                    evaluator_id=self.PYVISA_EVALUATOR,
                )


if __name__ == "__main__":
    unittest.main()
