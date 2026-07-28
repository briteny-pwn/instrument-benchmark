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

    def make_assets(self, root: Path) -> Path:
        assets = root / "assets"
        wheels = assets / "wheelhouse"
        wheels.mkdir(parents=True)
        dockerfile = assets / "evaluator.Dockerfile"
        dockerfile.write_text("FROM scratch\n")
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
