from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

from .docker_runtime import IMAGES, _remove_network, _run, ensure_images
from .linting import VISIBLE_FILES
from .paths import ROOT


PROBE = r'''
import json, os, pathlib, socket
workspace = pathlib.Path('/workspace')
files = sorted(str(path.relative_to(workspace)) for path in workspace.rglob('*') if path.is_file())
forbidden_paths = ['/evaluation', '/repo', '/workspace/.git', '/root/.claude', '/var/run/docker.sock']
outbound_blocked = False
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1).close()
except OSError:
    outbound_blocked = True
print(json.dumps({
    'workspace_files': files,
    'forbidden_paths_absent': all(not os.path.exists(path) for path in forbidden_paths),
    'host_secret_absent': not any(name in os.environ for name in ('UPSTREAM_API_KEY', 'BENCHMARK_MODEL_API_KEY')),
    'docker_socket_absent': not os.path.exists('/var/run/docker.sock'),
    'outbound_blocked': outbound_blocked,
}))
'''


def run_security_check(source: str, instance_id: str) -> dict[str, object]:
    ensure_images(("agent",))
    network = f"lab-security-{uuid.uuid4().hex[:10]}"
    with tempfile.TemporaryDirectory(prefix="ib-security-") as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        for relative in VISIBLE_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "instances" / source / instance_id / relative, target)
        _run(["docker", "network", "create", "--internal", network], capture_output=True)
        try:
            process = _run(
                [
                    "docker", "run", "--rm", "--network", network, "--read-only",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "128m",
                    "--mount", f"type=bind,src={workspace.resolve()},dst=/workspace,readonly",
                    "--entrypoint", "python3", IMAGES["agent"][0], "-c", PROBE,
                ],
                capture_output=True,
            )
        finally:
            _remove_network(network)
    report = json.loads(process.stdout)
    expected_files = sorted(str(path) for path in VISIBLE_FILES)
    report["workspace_allowlist"] = report["workspace_files"] == expected_files
    report["pass"] = all(
        bool(report[key])
        for key in (
            "workspace_allowlist", "forbidden_paths_absent", "host_secret_absent",
            "docker_socket_absent", "outbound_blocked",
        )
    )
    return report
