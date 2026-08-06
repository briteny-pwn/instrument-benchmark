from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "container" / "fibsem-validation-runner.Dockerfile"
DOCKERIGNORE = ROOT / "container" / "fibsem-validation-runner.Dockerfile.dockerignore"
RUNNER = ROOT / "scripts" / "run_fibsem_linux_acceptance.sh"


def test_validation_runner_has_a_pinned_python_and_bounded_tools() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert (
        "FROM python:3.11.9-slim-bookworm@sha256:"
        "2856e6af199e8128161abd320575eb9b341f3b76f017b5d0c9cd364f60d8a050"
        in text
    )
    assert "apt-get install -y --no-install-recommends" in text
    assert re.search(r"\bgit\b", text)
    assert "COPY wheelhouse/pyyaml-6.0.3-" in text
    assert "python -m pip install --no-index" in text
    assert "COPY docker-cli/docker /usr/local/bin/docker" in text
    assert "242c7a8de606afba2acada7c7af00d77f92c3601678b2f3a60911b49a892c722" in text
    assert 'ENTRYPOINT ["python"]' in text

    ignored = DOCKERIGNORE.read_text(encoding="utf-8")
    assert ignored.splitlines()[0] == "**"
    assert "!docker-cli/docker" in ignored
    assert "!wheelhouse/pyyaml-6.0.3-" in ignored
    assert "!openfibsem-wheelhouse" not in ignored


def test_native_linux_runner_preserves_daemon_visible_paths_and_identity() -> None:
    text = RUNNER.read_text(encoding="utf-8")

    assert 'test "$(uname -s)" = "Linux"' in text
    assert 'test "$(uname -m)" = "x86_64"' in text
    assert "docker build" in text
    assert "--platform linux/amd64" in text
    assert '--user "$(id -u):$(id -g)"' in text
    assert '--group-add "$socket_gid"' in text
    assert "src=/var/run/docker.sock,dst=/var/run/docker.sock" in text
    assert 'src=/tmp,dst=/tmp' in text
    assert 'src="$checkout_parent",dst="$checkout_parent"' in text
    assert 'python scripts/validate_fibsem_benchmark.py' not in text
    assert 'scripts/validate_fibsem_benchmark.py --config "$config_path"' in text


def test_readme_publishes_the_portable_native_linux_entrypoint() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "scripts/run_fibsem_linux_acceptance.sh" in text
    assert "Python 3.11" in text
    assert "identical absolute path" in text
