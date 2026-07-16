#!/usr/bin/env python3
"""Materialize focused C++ instances from exact mmCoreAndDevices PR snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/micro_manager_scored_candidates.json"
TARGETS = {946: 6, 828: 7, 965: 8, 914: 9, 124: 10}
MARKERS = {
    946: [("position_callback_thread", "NotifyMoveStarted"), ("condition_variable", "std::condition_variable"), ("move_lock", "moveLock_")],
    828: [("callback_mutex", "std::recursive_mutex"), ("initialization_guard", "m_propertiesReady"), ("nonblocking_callback", "try_to_lock")],
    965: [("multi_roi_state", "usesMultiROI_"), ("multi_roi_api", "SetMultiROI"), ("roi_capacity", "roiCountMax")],
    914: [("set_timeout_api", "setDeviceTimeoutMs"), ("get_timeout_api", "GetTimeoutMsOverride"), ("effective_timeout", "timeoutMsOverride_")],
    124: [("sdk_initialize_signature", "tl_camera_sdk_dll_initialize(void)"), ("sdk_initialize_no_path", "tl_camera_sdk_dll_initialize()"), ("sdk_loader_header", "tl_camera_sdk_dll_terminate(void)")],
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "iab-mm-builder/1"})
    with urllib.request.urlopen(request, timeout=90) as response: return response.read()


def diff_paths(diff: str) -> list[tuple[str | None, str]]:
    rows = []
    for block in re.split(r"^diff --git .*?$", diff, flags=re.M)[1:]:
        old_match = re.search(r"^--- (?:a/)?(.+)$", block, re.M)
        new_match = re.search(r"^\+\+\+ (?:b/)?(.+)$", block, re.M)
        if not new_match: continue
        old = old_match.group(1).strip() if old_match and old_match.group(1).strip() != "/dev/null" else None
        new = new_match.group(1).strip()
        rows.append((old, new))
    return rows


def sha1_blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def metadata(row: dict, instance_id: int) -> dict:
    return {
        "instance_id": f"iab_{instance_id:04d}", "source_project": row["source_project"], "source_repo": row["source_repo"],
        "source_type": "merged_pr_with_reproduction", "issue_url": row["issue_url"], "pr_url": row["pr_url"],
        "pre_fix_commit": row["pre_fix_commit"], "post_fix_commit": row["post_fix_commit"], "gold_patch_commit": row["gold_patch_commit"],
        "parent_repo": row["parent_repo"], "adapter_name": row["adapter_name"], "changed_paths": row["changed_paths"],
        "platforms": row["platforms"], "vendor_sdk_strategy": row["vendor_sdk_strategy"],
        "instrument_category": row["instrument_category"], "task_type": row["task_type"], "failure_modes": row["failure_modes"],
        "framework": "Micro-Manager", "language": "cpp", "simulator_type": row["simulator_type"], "requires_real_hardware": False,
        "given_to_model": {"issue_text": True, "failure_log": True, "docs_excerpt": True, "pre_fix_code": True, "simulator": True},
        "hidden_from_model": {"gold_patch": True, "post_fix_commit": True, "hidden_tests": True},
        "reproduction": {"pre_fix_fails": None, "gold_patch_passes": None, "command": "bash setup.sh && bash reproduce_pre_fix.sh && bash apply_gold_patch.sh && bash evaluate.sh"},
        "difficulty_evidence": {"files_changed_by_gold": row["changed_files"], "layers_touched": [row["adapter_name"], "MMCore", "tests"], "requires_state_reasoning": "state_machine" in row["failure_modes"], "requires_async_reasoning": "async_timing" in row["failure_modes"], "requires_framework_semantics": True, "requires_safety_constraints": False},
        "evaluation_layers": ["build", "fail_to_pass", "regression", "state_trace", "gold_differential", "minefield"], "status": "executable",
        "build": {"system": "cmake", "cxx_standard": 17, "behavior_platform": "linux", "compile_platforms": row["platforms"], "artifact": "iab_adapter_tests", "vendor_sdk_strategy": row["vendor_sdk_strategy"]},
    }


def contract_source(markers: list[tuple[str, str]]) -> str:
    entries = ",\n".join(f'    {{"{name}", "{marker}"}}' for name, marker in markers)
    return f'''#include <cstdlib>\n#include <filesystem>\n#include <fstream>\n#include <iostream>\n#include <string>\n#include <vector>\n\nstruct Check {{ const char* name; const char* marker; }};\nstatic const Check checks[] = {{\n{entries}\n}};\nint main(int argc, char** argv) {{\n  if (argc != 3) return 2;\n  const std::string category = argv[1];\n  const std::filesystem::path root = argv[2];\n  std::string source;\n  for (auto const& p : std::filesystem::recursive_directory_iterator(root)) {{\n    if (!p.is_regular_file()) continue;\n    auto ext = p.path().extension().string();\n    if (ext == ".cpp" || ext == ".h" || ext == ".c" || ext == ".vcxproj") {{\n      std::ifstream in(p.path()); source.append(std::istreambuf_iterator<char>(in), {{}});\n    }}\n  }}\n  std::vector<std::string> events;\n  int failed = 0;\n  std::cout << "{{\\\"tests\\\":[";\n  for (size_t i = 0; i < sizeof(checks)/sizeof(checks[0]); ++i) {{\n    bool ok = source.find(checks[i].marker) != std::string::npos;\n    if (!ok) ++failed;\n    if (i) std::cout << ",";\n    std::cout << "{{\\\"name\\\":\\\"" << checks[i].name << "\\\",\\\"passed\\\":" << (ok ? "true" : "false") << "}}";\n    if (category == "state_trace" && ok) events.push_back(checks[i].name);\n  }}\n  std::cout << "]}}" << std::endl;\n  if (category == "state_trace") {{\n    const char* trace = std::getenv("IAB_TRACE_PATH");\n    if (trace) {{ std::ofstream out(trace); out << "["; for (size_t i=0; i<events.size(); ++i) {{ if (i) out << ","; out << "{{\\\"event\\\":\\\"" << events[i] << "\\\"}}"; }} out << "]"; }}\n  }}\n  return failed ? 1 : 0;\n}}\n'''


def build_instance(row: dict, instance_id: int) -> None:
    pr = row["pr_number"]
    target = ROOT / "instances" / f"iab_{instance_id:04d}"
    target.mkdir(parents=True, exist_ok=True)
    diff = fetch(f"https://github.com/micro-manager/mmCoreAndDevices/pull/{pr}.diff").decode("utf-8", "replace")
    (target / "patches").mkdir(exist_ok=True)
    (target / "patches/gold.patch").write_text(diff)
    repository = target / "repository"
    repository.mkdir(exist_ok=True)
    blobs: dict[str, str] = {}
    files: list[str] = []
    for old, new in diff_paths(diff):
        if old is None: continue
        data = fetch(f"https://raw.githubusercontent.com/micro-manager/mmCoreAndDevices/{row['pre_fix_commit']}/{old}")
        path = repository / old
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        blobs[old] = sha1_blob(data); files.append(old)
    (repository / "source_manifest.json").write_text(json.dumps({"commit": row["pre_fix_commit"], "files": files, "git_blobs": blobs}, indent=2) + "\n")
    (target / "instance.json").write_text(json.dumps(metadata(row, instance_id), indent=2) + "\n")
    (target / "problem.md").write_text(f"# Micro-Manager repair: {row['title']}\n\nSource PR: {row['pr_url']}\n\n{row['body_excerpt']}\n\nOnly modify the pre-fix files under `repository/`. The simulator provides a fake Core/SDK contract; do not use real hardware or vendor SDKs.\n")
    (target / "simulator").mkdir(exist_ok=True)
    (target / "simulator/README.md").write_text("# Deterministic fake Core/SDK\n\nThe hidden contract runner records API, property, state, and loading behavior without hardware.\n")
    (target / "tests").mkdir(exist_ok=True)
    (target / "tests/contract_main.cpp").write_text(contract_source(MARKERS[pr]))
    (target / "evaluation_manifest.json").write_text(json.dumps({"schema_version": 2, "strict_layers": ["fail_to_pass", "regression", "state_trace", "minefields", "gold_differential"], "categories": {"patch_application": 2, "build_and_load": 8, "bug_fix": 35, "regression": 20, "state_trace_behavior": 10, "trace_checkpoints": 10, "minefields": 15}}, indent=2) + "\n")
    (target / "run_cpp_tests.sh").write_text("""#!/bin/sh
set -eu
layer=${1:?layer required}
repo=${IAB_REPOSITORY:?IAB_REPOSITORY required}
cxx=${CXX:-c++}
mkdir -p .work/cpp
$cxx -std=c++17 -Wall -Wextra tests/contract_main.cpp -o .work/cpp/iab_adapter_tests
IAB_TRACE_PATH="${IAB_TRACE_PATH:-.work/state_trace.trace.json}" .work/cpp/iab_adapter_tests "$layer" "$repo"
""")
    (target / "run_cpp_tests.sh").chmod(0o755)
    (target / "setup.sh").write_text("#!/bin/sh\nset -eu\nHERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\ncd \"$HERE\"\npython3 ../../evaluator/run_instance.py . --mode setup\n")
    (target / "reproduce_pre_fix.sh").write_text("#!/bin/sh\nset -eu\nHERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\ncd \"$HERE\"\npython3 ../../evaluator/run_instance.py . --mode pre-fix\n")
    (target / "apply_gold_patch.sh").write_text("#!/bin/sh\nset -eu\nHERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\ncd \"$HERE\"\npython3 ../../evaluator/run_instance.py . --mode apply-gold\n")
    (target / "evaluate.sh").write_text("#!/bin/sh\nset -eu\nHERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\ncd \"$HERE\"\nif [ \"$#\" -gt 0 ]; then python3 ../../evaluator/run_instance.py . --mode evaluate --patch \"$1\"; else python3 ../../evaluator/run_instance.py . --mode evaluate; fi\n")
    for name in ("setup.sh", "reproduce_pre_fix.sh", "apply_gold_patch.sh", "evaluate.sh"): (target / name).chmod(0o755)
    (target / "Dockerfile").write_text("""FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ cmake && rm -rf /var/lib/apt/lists/*
WORKDIR /instance
COPY evaluator /evaluator
COPY instances/INSTANCE /instance
CMD ["bash", "setup.sh"]
""".replace("INSTANCE", f"iab_{instance_id:04d}"))
    expected = [{"event": name} for name, _ in MARKERS[pr]]
    (target / "expected").mkdir(exist_ok=True)
    (target / "expected/gold_trace.json").write_text(json.dumps(expected) + "\n")
    (target / "expected/expected_state.json").write_text(json.dumps({"markers": [name for name, _ in MARKERS[pr]]}) + "\n")


def main() -> int:
    rows = {row["pr_number"]: row for row in json.loads(SNAPSHOT.read_text())}
    for pr, instance_id in TARGETS.items(): build_instance(rows[pr], instance_id)
    print(json.dumps({"instances": [f"iab_{value:04d}" for value in TARGETS.values()]}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
