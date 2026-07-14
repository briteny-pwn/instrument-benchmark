from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path
from typing import Any

from evaluations.common import raw_trace
from evaluations.common.grader_core import _make_gateway
from .authoring import materialize


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, default=Path("/control"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--authoring-seed")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    raw_trace.reset_trace()
    scenario = args.scenario
    if args.authoring_seed:
        scenario = materialize(args.scenario, Path("/tmp/authoring-scenario"), args.authoring_seed)
    gateway = _make_gateway(spec, scenario)
    host, port = gateway.start(args.host, args.port)
    _write_json(args.control_dir / "ready.json", {"host": host, "port": port})

    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    stopped.wait()

    state = gateway.snapshot_state()
    gateway.stop()
    _write_json(
        args.control_dir / "evidence.json",
        {"trace": raw_trace.serializable_trace(), "sim_state": state},
    )


if __name__ == "__main__":
    main()
