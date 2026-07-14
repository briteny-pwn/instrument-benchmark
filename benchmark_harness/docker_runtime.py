from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from evaluations.common import grader_core, import_guard

from .agents import get_adapter
from .paths import ROOT, evaluation_dir
from .run_store import load_manifest, update_hashes, update_manifest, write_json


IMAGES = {
    "simulator": ("instrument-benchmark-simulator:local", ROOT / "docker/simulator.Dockerfile"),
    "runner": ("instrument-benchmark-runner:local", ROOT / "docker/runner.Dockerfile"),
    "agent": ("instrument-benchmark-agent:local", ROOT / "docker/agent.Dockerfile"),
    "proxy": ("instrument-benchmark-proxy:local", ROOT / "docker/proxy.Dockerfile"),
}


class DockerError(RuntimeError):
    pass


def _run(command: list[str], *, check: bool = True, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, text=True, **kwargs)
    if check and process.returncode != 0:
        raise DockerError(process.stderr.strip() or process.stdout.strip() or "docker command failed")
    return process


def require_docker() -> None:
    if shutil.which("docker") is None:
        raise DockerError("docker CLI is not installed")
    _run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def ensure_images(names: tuple[str, ...]) -> dict[str, str]:
    require_docker()
    digests: dict[str, str] = {}
    for name in names:
        image, dockerfile = IMAGES[name]
        _run(
            ["docker", "build", "-f", str(dockerfile), "-t", image, str(ROOT)],
            stdout=None,
            stderr=None,
        )
        inspected = _run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True
        )
        digests[name] = inspected.stdout.strip()
    return digests


def _name(prefix: str) -> str:
    return f"lab-{prefix}-{uuid.uuid4().hex[:10]}"


def _remove_container(name: str) -> None:
    _run(["docker", "rm", "-f", name], check=False, capture_output=True)


def _remove_network(name: str) -> None:
    _run(["docker", "network", "rm", name], check=False, capture_output=True)


def _wait_for(path: Path, container: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        inspected = _run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            check=False,
            capture_output=True,
        )
        if inspected.returncode != 0 or inspected.stdout.strip() != "true":
            logs = _run(["docker", "logs", container], check=False, capture_output=True)
            raise DockerError(f"container {container} exited before readiness: {logs.stderr}{logs.stdout}")
        time.sleep(0.1)
    raise DockerError(f"timed out waiting for {container}")


def _start_simulator(
    *,
    network: str,
    eval_dir: Path,
    simulator: str,
    control: Path,
    authoring_seed: str | None = None,
    scenario_spec: dict[str, Any] | None = None,
) -> str:
    name = _name("device")
    control.mkdir(parents=True, exist_ok=True)
    spec_argument = "/evaluation/spec.json"
    if scenario_spec is not None:
        write_json(control / "scenario-spec.json", scenario_spec)
        spec_argument = "/control/scenario-spec.json"
    image = IMAGES["simulator"][0]
    command = [
        "docker", "run", "-d", "--name", name, "--network", network,
        "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "1g", "--cpus", "2",
        "--mount", f"type=bind,src={eval_dir.resolve()},dst=/evaluation,readonly",
        "--mount", f"type=bind,src={control.resolve()},dst=/control",
        image, "--spec", spec_argument, "--scenario", f"/evaluation/{simulator}",
        "--host", "0.0.0.0", "--port", "9000",
    ]
    if authoring_seed:
        command.extend(["--authoring-seed", authoring_seed])
    _run(command, capture_output=True)
    _wait_for(control / "ready.json", name)
    return name


def _stop_simulator(name: str, control: Path) -> dict[str, Any]:
    _run(["docker", "stop", "--time", "10", name], check=False, capture_output=True)
    deadline = time.monotonic() + 3.0
    while not (control / "evidence.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not (control / "evidence.json").exists():
        raise DockerError(f"simulator {name} produced no evidence")
    evidence = json.loads((control / "evidence.json").read_text(encoding="utf-8"))
    _remove_container(name)
    return evidence


def generate(run_dir: Path) -> None:
    manifest = load_manifest(run_dir)
    source, instance_id = manifest["instance"].split("/", 1)
    spec_path = evaluation_dir(source, instance_id) / "spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    authoring = spec.get("authoring", {})
    simulator = authoring.get("base_simulator")
    if not simulator:
        raise DockerError(f"{manifest['instance']} has no dedicated authoring simulator")

    api_key = (
        os.environ.get("BENCHMARK_MODEL_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    if not api_key:
        raise DockerError("set BENCHMARK_MODEL_API_KEY or an Anthropic API credential")
    image_digests = ensure_images(("simulator", "agent", "proxy"))
    network = _name("authoring-net")
    proxy = _name("model-api")
    agent = _name("agent")
    simulator_name = ""
    control = run_dir / ".control" / "authoring"
    workspace = run_dir / "workspace"
    events = run_dir / "agent/events.jsonl"
    summary_path = run_dir / "agent/summary.json"
    proxy_env = run_dir / ".control" / "proxy.env"
    _run(["docker", "network", "create", "--internal", network], capture_output=True)
    try:
        simulator_name = _start_simulator(
            network=network,
            eval_dir=spec_path.parent,
            simulator=simulator,
            control=control,
            authoring_seed=str(authoring["seed"]),
        )
        proxy_env.parent.mkdir(parents=True, exist_ok=True)
        proxy_env.write_text(
            "\n".join(
                [
                    f"UPSTREAM_API_KEY={api_key}",
                    f"UPSTREAM_API_BASE={os.environ.get('BENCHMARK_MODEL_API_BASE_URL', os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com'))}",
                    f"UPSTREAM_AUTH_HEADER={os.environ.get('BENCHMARK_MODEL_API_AUTH_HEADER', 'x-api-key')}",
                    f"UPSTREAM_AUTH_SCHEME={os.environ.get('BENCHMARK_MODEL_API_AUTH_SCHEME', '')}",
                ]
            ) + "\n",
            encoding="utf-8",
        )
        proxy_env.chmod(0o600)
        proxy_command = [
            "docker", "run", "-d", "--name", proxy, "--network", network,
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "256m",
            "--env-file", str(proxy_env),
            IMAGES["proxy"][0],
        ]
        _run(proxy_command, capture_output=True)
        proxy_env.unlink(missing_ok=True)
        _run(["docker", "network", "connect", "bridge", proxy], capture_output=True)

        invocation = get_adapter(manifest["agent"]).invocation(workspace, manifest["model"])
        agent_command = [
            "docker", "run", "--rm", "-i", "--name", agent, "--network", network,
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "2g", "--cpus", "2",
            "-e", "HOME=/tmp/home", "-e", "CLAUDE_CONFIG_DIR=/tmp/home/.claude",
            "-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
            "-e", "ANTHROPIC_BASE_URL=http://" + proxy + ":8080",
            "-e", "ANTHROPIC_API_KEY=isolated-placeholder",
            "-e", "INSTRUMENT_SIM_HOST=" + simulator_name,
            "-e", "INSTRUMENT_SIM_PORT=9000",
            "--mount", f"type=bind,src={workspace.resolve()},dst=/workspace",
            IMAGES["agent"][0], *invocation.command,
        ]
        started = time.monotonic()
        process = subprocess.run(
            agent_command,
            input=invocation.stdin,
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("BENCHMARK_AGENT_TIMEOUT", "1800")),
        )
        events.write_text(process.stdout, encoding="utf-8")
        write_json(
            summary_path,
            {
                "returncode": process.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stderr": process.stderr,
            },
        )
        solution = workspace / "solution.py"
        if process.returncode != 0 or not solution.is_file():
            raise DockerError("agent failed or did not produce solution.py; inspect agent/summary.json")
        shutil.copy2(solution, run_dir / "candidate/solution.py")
        update_manifest(
            run_dir,
            status="generated",
            generated_at=time.time(),
            image_digests={**manifest.get("image_digests", {}), **image_digests},
        )
        update_hashes(run_dir)
    finally:
        proxy_env.unlink(missing_ok=True)
        _remove_container(agent)
        _remove_container(proxy)
        if simulator_name:
            _run(["docker", "stop", "--time", "5", simulator_name], check=False, capture_output=True)
            _remove_container(simulator_name)
        _remove_network(network)


def evaluate(run_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(run_dir)
    source, instance_id = manifest["instance"].split("/", 1)
    eval_dir = evaluation_dir(source, instance_id)
    spec = json.loads((eval_dir / "spec.json").read_text(encoding="utf-8"))
    candidate = run_dir / "candidate/solution.py"
    if not candidate.is_file():
        raise DockerError("candidate/solution.py is missing; run generate first")
    image_digests = ensure_images(("simulator", "runner"))
    forbidden = import_guard.check_candidate_imports(candidate)
    forbidden_score = 0.0 if forbidden else 1.0
    scenario_reports: list[dict[str, Any]] = []
    repetitions = max(1, int(spec.get("suite", {}).get("repetitions", 1)))

    with tempfile.TemporaryDirectory(prefix="ib-eval-", dir=run_dir / "evaluation") as temporary:
        temp_root = Path(temporary)
        scenarios = spec.get("scenarios")
        if not scenarios:
            scenarios = [{"id": "default", "simulator": spec["simulator"]}]
        for index, scenario in enumerate(scenarios):
            scenario_id = scenario.get("id", f"scenario-{index + 1}")
            for repetition in range(1, repetitions + 1):
                network = _name("evaluation-net")
                control = temp_root / f"{scenario_id}-{repetition}" / "control"
                output = temp_root / f"{scenario_id}-{repetition}" / "output"
                output.mkdir(parents=True)
                output.chmod(0o777)
                simulator_name = ""
                _run(["docker", "network", "create", "--internal", network], capture_output=True)
                try:
                    scenario_spec = grader_core._build_scenario_spec(spec, scenario) if spec.get("scenarios") else spec
                    simulator_name = _start_simulator(
                        network=network,
                        eval_dir=eval_dir,
                        simulator=scenario["simulator"],
                        control=control,
                        scenario_spec=scenario_spec,
                    )
                    runner_name = _name("runner")
                    runner_command = [
                        "docker", "run", "--name", runner_name, "--network", network, "--read-only",
                        "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m", "--cap-drop", "ALL",
                        "--security-opt", "no-new-privileges", "--pids-limit", "128",
                        "--memory", "512m", "--cpus", "1", "--network-alias", "solution-runner",
                        "-e", f"INSTRUMENT_SIM_HOST={simulator_name}", "-e", "INSTRUMENT_SIM_PORT=9000",
                        "--mount", f"type=bind,src={candidate.resolve()},dst=/workspace/solution.py,readonly",
                        "--mount", f"type=bind,src={output.resolve()},dst=/output",
                        IMAGES["runner"][0],
                    ]
                    try:
                        process = _run(
                            runner_command,
                            check=False,
                            capture_output=True,
                            timeout=int(os.environ.get("BENCHMARK_SOLUTION_TIMEOUT", "120")),
                        )
                    except subprocess.TimeoutExpired:
                        _remove_container(runner_name)
                        process = subprocess.CompletedProcess(runner_command, 124, "", "solution runner timed out")
                    else:
                        _remove_container(runner_name)
                    evidence = _stop_simulator(simulator_name, control)
                    simulator_name = ""
                    status = json.loads((output / "execution.json").read_text(encoding="utf-8")) if (output / "execution.json").exists() else {"ok": False, "error": "runner produced no status"}
                    result = json.loads((output / "result.json").read_text(encoding="utf-8")) if (output / "result.json").exists() else {}
                    feedback = []
                    if forbidden:
                        feedback.append(f"Forbidden instrument/framework imports observed: {', '.join(forbidden)}.")
                    if not status.get("ok"):
                        feedback.append(f"Candidate failed in isolated runner: {status.get('error', process.stderr)}")
                    report = grader_core.grade_collected_scenario(
                        spec=scenario_spec,
                        result=result,
                        trace=evidence.get("trace", []),
                        sim_state=evidence.get("sim_state", {}),
                        execution_score=1.0 if status.get("ok") else 0.0,
                        forbidden_score=forbidden_score,
                        feedback=feedback,
                    )
                    report.update(
                        scenario_id=scenario_id,
                        repetition=repetition,
                        run_id=f"{scenario_id}#{repetition}" if repetitions > 1 else scenario_id,
                    )
                    scenario_reports.append(report)
                finally:
                    if simulator_name:
                        _run(["docker", "stop", "--time", "5", simulator_name], check=False, capture_output=True)
                        _remove_container(simulator_name)
                    _remove_network(network)

    report = grader_core.aggregate_scenario_reports(spec, scenario_reports) if spec.get("scenarios") else scenario_reports[0]
    write_json(run_dir / "evaluation/report.json", report)
    update_manifest(
        run_dir,
        status="evaluated",
        evaluated_at=time.time(),
        image_digests={**manifest.get("image_digests", {}), **image_digests},
    )
    update_hashes(run_dir)
    return report
