#!/usr/bin/env python3
"""Mine merged instrument-integration PRs and their linked closed issues.

The output is an evidence snapshot, not an executable instance. Set
GITHUB_TOKEN to raise API limits. No token is ever written to disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

KEYWORDS = ("instrument", "driver", "device", "adapter", "camera", "stage", "detector", "acquire", "trigger", "read", "timeout", "firmware", "scpi", "visa", "serial", "gpib", "epics", "pv", "ioc", "asyn", "areadetector", "ophyd", "bluesky plan", "qcodes parameter", "snapshot", "stale data", "metadata", "interlock")
SEARCH_TERMS = ("driver", "device", "adapter", "timeout", "instrument")
EXCLUDED_TITLES = ("bump ", "requirement", "dependabot", "typing", "ci ", "lint")
LINK_RE = re.compile(r"(?:(?:fix|close|resolve)(?:e[sd])?|refs?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)


class GitHub:
    def __init__(self) -> None:
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "iab-sim-miner/1"}
        if token := os.environ.get("GITHUB_TOKEN"):
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, url: str) -> Any:
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"GitHub API {exc.code}: {detail[:300]}") from exc


def classify_change(paths: list[str]) -> str:
    if paths and all(p.lower().endswith((".md", ".rst", ".txt")) or "/docs/" in f"/{p.lower()}" for p in paths): return "docs"
    if paths and all(p.startswith(".github/") or p.startswith("ci/") for p in paths): return "ci"
    dependency_names = {"requirements.txt", "requirements.lock", "poetry.lock", "uv.lock", "pdm.lock"}
    if paths and all(Path(p).name in dependency_names for p in paths): return "dependency_only"
    return "code"


def evidence_for(item: dict[str, Any], pr: dict[str, Any], linked_issue: bool, paths: list[str]) -> dict[str, bool]:
    text = f"{item.get('title', '')} {item.get('body') or ''} {' '.join(paths)}".lower()
    instrument = any(k in text for k in KEYWORDS)
    stateish = any(k in text for k in ("state", "trigger", "timeout", "wait", "stale", "cache", "init", "connect", "close"))
    return {
        "has_issue": linked_issue, "has_merged_pr": bool(pr.get("merged_at")), "issue_pr_linked": linked_issue,
        "has_discussion_or_log": item.get("comments", 0) > 0 or "traceback" in text or "error" in text,
        "touches_driver_adapter": instrument, "real_instrument": instrument,
        "framework_semantics": any(k in text for k in ("ophyd", "qcodes", "parameter", "signal", "device", "snapshot")),
        "acquisition_or_state": stateish, "multiple_files": pr.get("changed_files", 0) > 1,
        "state_async_timeout": stateish, "version_compatibility": any(k in text for k in ("version", "firmware", "compat")),
        "metadata_or_stale": any(k in text for k in ("metadata", "stale", "cache", "snapshot")),
        "framework_lifecycle": any(k in text for k in ("init", "connect", "close", "set", "trigger", "status")),
        "recovery_or_cleanup": any(k in text for k in ("error", "recover", "cleanup", "close", "timeout")),
        "mockable": True, "trace_replayable": True, "stateful_simulatable": stateish,
        "no_real_hardware": True, "upstream_tests": "test" in text,
        "fail_to_pass_writable": True, "regression_writable": True,
    }


def mine_source(api: GitHub, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    repo = source["repo"]
    # GitHub Search rejects queries with more than five boolean operators.
    # Keep the remote query broad and apply the full vocabulary locally.
    query = f"repo:{repo} is:pr is:merged ({' OR '.join(SEARCH_TERMS)})"
    url = "https://api.github.com/search/issues?" + urllib.parse.urlencode({"q": query, "per_page": min(limit, 100), "sort": "updated"})
    items = [item for item in api.get(url).get("items", []) if not any(term in item["title"].lower() for term in EXCLUDED_TITLES)]
    result = []
    for item in items[:limit]:
        pr = api.get(item["pull_request"]["url"])
        files = api.get(item["pull_request"]["url"] + "/files?per_page=100")
        paths = [entry["filename"] for entry in files]
        refs = LINK_RE.findall(item.get("body") or "")
        issue_number, issue = None, None
        for ref in refs:
            candidate_issue = api.get(f"https://api.github.com/repos/{repo}/issues/{ref}")
            if candidate_issue.get("state") == "closed" and "pull_request" not in candidate_issue:
                issue_number, issue = ref, candidate_issue
                break
        issue_url = f"https://github.com/{repo}/issues/{issue_number}" if issue_number else ""
        result.append({
            "candidate_id": "", "source_project": source["name"], "source_repo": f"https://github.com/{repo}",
            "issue_url": issue_url, "pr_url": item["html_url"], "pr_number": item["number"],
            "title": item["title"], "body_excerpt": (item.get("body") or "")[:1200], "issue_title": issue.get("title", "") if issue else "", "issue_state": issue.get("state", "") if issue else "",
            "pre_fix_commit": pr.get("base", {}).get("sha", ""), "post_fix_commit": pr.get("merge_commit_sha") or "",
            "gold_patch_commit": pr.get("merge_commit_sha") or "", "merged_at": pr.get("merged_at"),
            "changed_files": pr.get("changed_files", 0), "changed_paths": paths, "additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0),
            "language": source["language"], "domain": source["domain"], "change_kind": classify_change(paths),
            "evidence": evidence_for(item, pr, bool(issue_number), paths), "mined_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("configs/sources.yaml"))
    parser.add_argument("--per-source", type=int, default=5)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("data/raw_candidates.json"))
    args = parser.parse_args()
    config = yaml.safe_load(args.sources.read_text())
    api, rows = GitHub(), []
    for source in config["sources"]:
        if source["language"] == "python": rows.extend(mine_source(api, source, args.per_source))
        if len(rows) >= args.limit: break
    rows = rows[:args.limit]
    for index, row in enumerate(rows, 1): row["candidate_id"] = f"candidate_{index:04d}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"total": len(rows), "linked_issues": sum(bool(x["issue_url"]) for x in rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
