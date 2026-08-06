from __future__ import annotations

import hashlib
import json
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


class EvaluatorImageTests(unittest.TestCase):
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
            context = stage_evaluator_build_context(
                self.make_evaluator(root),
                self.make_assets(root, source_commit=commit),
                root / "context",
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
            verify_build_manifest(context.root, context.manifest_path)

    def test_fibsem_context_rejects_commit_mismatch_and_tracked_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, commit = self.make_openfibsem(root)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root, source_commit=commit)

            with self.assertRaisesRegex(EvaluatorImageError, "commit"):
                stage_evaluator_build_context(
                    evaluator,
                    assets,
                    root / "wrong-context",
                    openfibsem_checkout=checkout,
                    openfibsem_commit="0" * 40,
                )

            (checkout / "fibsem/model3d/simulator.py").write_text("changed\n")
            with self.assertRaisesRegex(EvaluatorImageError, "tracked"):
                stage_evaluator_build_context(
                    evaluator,
                    assets,
                    root / "dirty-context",
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
                stage_evaluator_build_context(
                    self.make_evaluator(root),
                    assets,
                    root / "context",
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

            context = stage_evaluator_build_context(
                self.make_evaluator(root),
                assets,
                root / "context",
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
                stage_evaluator_build_context(
                    self.make_evaluator(root),
                    assets,
                    root / "context",
                    openfibsem_checkout=checkout,
                    openfibsem_commit=commit,
                )
    def test_real_context_installs_hooked_sim_fork_before_evaluator(self) -> None:
        evaluator = (ROOT.parent / "evaluator").resolve()
        with tempfile.TemporaryDirectory() as directory:
            context = stage_evaluator_build_context(
                evaluator,
                ROOT / "container",
                Path(directory) / "context",
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
        return assets

    def test_stage_contains_only_tracked_evaluator_and_verified_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            destination = root / "context"

            context = stage_evaluator_build_context(
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
            self.assertEqual(len(context.evaluator_commit), 40)
            verify_build_manifest(context.root, context.manifest_path)

    def test_build_manifest_detects_staged_input_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = stage_evaluator_build_context(
                self.make_evaluator(root),
                self.make_assets(root),
                root / "context",
            )
            staged = context.root / "evaluator" / "pyproject.toml"
            staged.write_text(staged.read_text() + "# changed\n")

            with self.assertRaisesRegex(EvaluatorImageError, "manifest"):
                verify_build_manifest(context.root, context.manifest_path)

    def test_wheel_manifest_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            (assets / "wheelhouse" / "fake-1-py3-none-any.whl").write_bytes(b"changed")

            with self.assertRaisesRegex(EvaluatorImageError, "wheel"):
                stage_evaluator_build_context(evaluator, assets, root / "context")

    def test_docker_cli_manifest_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = self.make_evaluator(root)
            assets = self.make_assets(root)
            (assets / "docker-cli" / "docker").write_bytes(b"changed")

            with self.assertRaisesRegex(EvaluatorImageError, "Docker CLI"):
                stage_evaluator_build_context(evaluator, assets, root / "context")

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
            ).build(evaluator, run_id="run 1")

            build = next(call for call in calls if call[:2] == ["docker", "build"])
            self.assertIn("--network=none", build)
            self.assertIn("--platform=linux/amd64", build)
            self.assertIn("--pull=false", build)
            self.assertTrue(evidence.reference.startswith("iab/evaluator:run-1-"))
            self.assertEqual(evidence.image_id, "sha256:" + "a" * 64)
            self.assertEqual(evidence.user, "11001:11001")
            EvaluatorImageBuilder(
                assets_root=assets,
                executor=execute,
            ).remove(evidence)
            self.assertIn(["docker", "image", "rm", evidence.reference], calls)

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
                ).build(evaluator, run_id="run")


if __name__ == "__main__":
    unittest.main()
