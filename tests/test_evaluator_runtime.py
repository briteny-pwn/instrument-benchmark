from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.evaluator_image import EvaluatorImageEvidence  # noqa: E402
from instrument_benchmark.evaluator_runtime import (  # noqa: E402
    AttachedEvaluatorResult,
    EvaluatorContainerRunner,
    EvaluatorInfrastructureError,
    RuntimeCommandResult,
)


class EvaluatorRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.shared = self.root / "shared"
        self.shared.mkdir()
        self.instance = self.root / "instance"
        self.instance.mkdir()
        self.candidate = self.root / "solution.py"
        self.candidate.write_text("pass\n")
        self.request = self.shared / "request.json"
        self.request.write_text("{}")
        self.report = self.shared / "report.json"
        self.socket_path = self.root / "docker.sock"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.socket_path))
        self.image = EvaluatorImageEvidence(
            reference="iab/evaluator:test",
            image_id="sha256:" + "a" * 64,
            repo_digest=None,
            dockerfile_sha256="b" * 64,
            build_manifest_sha256="c" * 64,
            evaluator_commit="d" * 40,
            platform="linux/amd64",
            user="11001:11001",
        )

    def tearDown(self) -> None:
        self.socket.close()
        self.temporary.cleanup()

    def inspect_payload(self) -> str:
        return json.dumps(
            [
                {
                    "Id": "outer-id",
                    "Image": self.image.image_id,
                    "Created": "2026-07-28T00:00:00Z",
                    "State": {
                        "Status": "exited",
                        "ExitCode": 0,
                        "OOMKilled": False,
                        "StartedAt": "2026-07-28T00:00:01Z",
                        "FinishedAt": "2026-07-28T00:00:02Z",
                    },
                    "Config": {
                        "User": "11001:11001",
                        "Labels": {
                            "iab.managed": "true",
                            "iab.kind": "evaluator",
                            "iab.owner": "run-1",
                            "iab.run_id": "run-1",
                        },
                    },
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges"],
                        "PidsLimit": 256,
                        "Memory": 2147483648,
                        "MemorySwap": 2147483648,
                        "NanoCpus": 2000000000,
                        "GroupAdd": [str(self.socket_path.stat().st_gid)],
                        "Tmpfs": {
                            "/tmp": "rw,noexec,nosuid,nodev,size=268435456"
                        },
                        "Binds": [],
                    },
                    "Mounts": [
                        {
                            "Type": "bind",
                            "Source": str(self.shared),
                            "Destination": str(self.shared),
                            "RW": True,
                        },
                        {
                            "Type": "bind",
                            "Source": str(self.instance),
                            "Destination": str(self.instance),
                            "RW": False,
                        },
                        {
                            "Type": "bind",
                            "Source": str(self.candidate),
                            "Destination": str(self.candidate),
                            "RW": False,
                        },
                        {
                            "Type": "bind",
                            "Source": str(self.socket_path),
                            "Destination": "/var/run/docker.sock",
                            "RW": True,
                        },
                    ],
                }
            ]
        )

    def test_completed_run_uses_hardening_mounts_and_collects_evidence(self) -> None:
        calls: list[list[str]] = []

        def execute(arguments: list[str]) -> RuntimeCommandResult:
            calls.append(arguments)
            if arguments[:2] == ["docker", "create"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            if arguments[:2] == ["docker", "inspect"]:
                return RuntimeCommandResult(0, self.inspect_payload(), "")
            if arguments[:2] == ["docker", "rm"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            raise AssertionError(arguments)

        def attach(*args, **kwargs) -> AttachedEvaluatorResult:
            self.report.write_text(json.dumps({"schema_version": 1, "score": 100}))
            return AttachedEvaluatorResult(0, "out", "err", False, False)

        result = EvaluatorContainerRunner(
            docker_socket=self.socket_path,
            executor=execute,
            attach_executor=attach,
        ).run(
            image=self.image,
            request_path=self.request,
            report_path=self.report,
            instance_path=self.instance,
            candidate_path=self.candidate,
            shared_run_root=self.shared,
            run_id="run-1",
            timeout=30,
            stdout_limit=65536,
            stderr_limit=65536,
        )

        create = next(call for call in calls if call[:2] == ["docker", "create"])
        for expected in (
            "--network=none",
            "--read-only",
            "--user=11001:11001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=256",
            "--memory=2g",
            "--memory-swap=2g",
            "--cpus=2.0",
        ):
            self.assertIn(expected, create)
        self.assertIn(f"--group-add={self.socket_path.stat().st_gid}", create)
        self.assertIn("--label=iab.run_id=run-1", create)
        self.assertTrue(any(f"src={self.shared},dst={self.shared}" in x for x in create))
        self.assertFalse(any(str(ROOT / ".git") in x for x in create))
        self.assertEqual(result.report["score"], 100)
        self.assertEqual(result.evidence.network_mode, "none")
        self.assertTrue(result.evidence.cleanup_succeeded)

    def test_rejects_report_outside_shared_root(self) -> None:
        runner = EvaluatorContainerRunner(
            docker_socket=self.socket_path,
            executor=lambda args: RuntimeCommandResult(0, "", ""),
            attach_executor=lambda *a, **k: AttachedEvaluatorResult(0, "", "", False, False),
        )
        with self.assertRaisesRegex(EvaluatorInfrastructureError, "shared root"):
            runner.run(
                image=self.image,
                request_path=self.request,
                report_path=self.root / "outside.json",
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run",
                timeout=1,
                stdout_limit=1,
                stderr_limit=1,
            )

    def test_rejects_non_socket_docker_path(self) -> None:
        runner = EvaluatorContainerRunner(
            docker_socket=self.root / "not-a-socket",
            executor=lambda args: RuntimeCommandResult(0, "", ""),
            attach_executor=lambda *a, **k: AttachedEvaluatorResult(0, "", "", False, False),
        )
        (self.root / "not-a-socket").write_text("x")
        with self.assertRaisesRegex(EvaluatorInfrastructureError, "socket"):
            runner.run(
                image=self.image,
                request_path=self.request,
                report_path=self.report,
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run",
                timeout=1,
                stdout_limit=1,
                stderr_limit=1,
            )

    def test_rejects_symlinked_report(self) -> None:
        target = self.shared / "target.json"
        target.write_text("{}")

        def execute(arguments: list[str]) -> RuntimeCommandResult:
            if arguments[:2] == ["docker", "create"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            if arguments[:2] == ["docker", "inspect"]:
                return RuntimeCommandResult(0, self.inspect_payload(), "")
            return RuntimeCommandResult(0, "", "")

        def attach(*args, **kwargs) -> AttachedEvaluatorResult:
            self.report.symlink_to(target)
            return AttachedEvaluatorResult(0, "", "", False, False)

        with self.assertRaisesRegex(EvaluatorInfrastructureError, "report"):
            EvaluatorContainerRunner(
                docker_socket=self.socket_path,
                executor=execute,
                attach_executor=attach,
            ).run(
                image=self.image,
                request_path=self.request,
                report_path=self.report,
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run",
                timeout=30,
                stdout_limit=65536,
                stderr_limit=65536,
            )

    def test_rejects_runtime_security_drift_from_inspect(self) -> None:
        def execute(arguments: list[str]) -> RuntimeCommandResult:
            if arguments[:2] == ["docker", "create"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            if arguments[:2] == ["docker", "inspect"]:
                value = json.loads(self.inspect_payload())
                value[0]["HostConfig"]["NetworkMode"] = "bridge"
                return RuntimeCommandResult(0, json.dumps(value), "")
            return RuntimeCommandResult(0, "", "")

        def attach(*args, **kwargs) -> AttachedEvaluatorResult:
            self.report.write_text("{}")
            return AttachedEvaluatorResult(0, "", "", False, False)

        with self.assertRaisesRegex(EvaluatorInfrastructureError, "runtime policy"):
            EvaluatorContainerRunner(
                docker_socket=self.socket_path,
                executor=execute,
                attach_executor=attach,
            ).run(
                image=self.image,
                request_path=self.request,
                report_path=self.report,
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run",
                timeout=30,
                stdout_limit=65536,
                stderr_limit=65536,
            )

    def test_cleanup_failure_does_not_replace_primary_runtime_error(self) -> None:
        def execute(arguments: list[str]) -> RuntimeCommandResult:
            if arguments[:2] == ["docker", "create"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            if arguments[:2] == ["docker", "inspect"]:
                return RuntimeCommandResult(0, self.inspect_payload(), "")
            if arguments[:2] == ["docker", "rm"]:
                return RuntimeCommandResult(1, "", "remove denied")
            raise AssertionError(arguments)

        with self.assertRaisesRegex(EvaluatorInfrastructureError, "timed out") as caught:
            EvaluatorContainerRunner(
                docker_socket=self.socket_path,
                executor=execute,
                attach_executor=lambda *a, **k: AttachedEvaluatorResult(
                    137, "", "", True, False
                ),
            ).run(
                image=self.image,
                request_path=self.request,
                report_path=self.report,
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run-1",
                timeout=1,
                stdout_limit=1,
                stderr_limit=1,
            )
        self.assertTrue(
            any("remove denied" in note for note in getattr(caught.exception, "__notes__", []))
        )

    def test_rejects_additional_tmpfs_mount(self) -> None:
        def execute(arguments: list[str]) -> RuntimeCommandResult:
            if arguments[:2] == ["docker", "create"]:
                return RuntimeCommandResult(0, "outer-id\n", "")
            if arguments[:2] == ["docker", "inspect"]:
                value = json.loads(self.inspect_payload())
                value[0]["HostConfig"]["Tmpfs"]["/extra"] = "rw,size=1m"
                return RuntimeCommandResult(0, json.dumps(value), "")
            return RuntimeCommandResult(0, "", "")

        def attach(*args, **kwargs) -> AttachedEvaluatorResult:
            self.report.write_text("{}")
            return AttachedEvaluatorResult(0, "", "", False, False)

        with self.assertRaisesRegex(EvaluatorInfrastructureError, "runtime policy"):
            EvaluatorContainerRunner(
                docker_socket=self.socket_path,
                executor=execute,
                attach_executor=attach,
            ).run(
                image=self.image,
                request_path=self.request,
                report_path=self.report,
                instance_path=self.instance,
                candidate_path=self.candidate,
                shared_run_root=self.shared,
                run_id="run-1",
                timeout=1,
                stdout_limit=1,
                stderr_limit=1,
            )


if __name__ == "__main__":
    unittest.main()
