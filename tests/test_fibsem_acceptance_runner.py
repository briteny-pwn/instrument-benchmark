from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "container" / "fibsem-validation-runner.Dockerfile"
DOCKERIGNORE = ROOT / "container" / "fibsem-validation-runner.Dockerfile.dockerignore"
RUNNER = ROOT / "scripts" / "run_fibsem_linux_acceptance.sh"


def test_validation_runner_has_a_pinned_python_and_bounded_tools() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    wheel = (
        "pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64."
        "manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl"
    )

    assert (
        "FROM python:3.11.9-slim-bookworm@sha256:"
        "2856e6af199e8128161abd320575eb9b341f3b76f017b5d0c9cd364f60d8a050"
        in text
    )
    assert "apt-get" not in text
    assert "COPY git" not in text
    assert "COPY wheelhouse/pyyaml-6.0.3-" in text
    assert f"/build/{wheel}" in text
    assert "/build/pyyaml.whl" not in text
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
    assert "--network=none" in text
    assert "git_bin=$(command -v git)" in text
    assert "git_exec_path=$(git --exec-path)" in text
    assert 'ldd "$git_bin"' in text
    assert '$3 !~ /\\/libc\\.so\\./' in text
    assert '$1 !~ /\\/ld-linux/' in text
    assert 'src="$git_bin",dst="$git_bin",readonly' in text
    assert 'src="$git_exec_path",dst="$git_exec_path",readonly' in text
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
