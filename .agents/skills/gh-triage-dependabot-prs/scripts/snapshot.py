#!/usr/bin/env python3
"""Read-only snapshot of open Dependabot PRs requesting review from the current gh user."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any


ALLOWED_CHECK_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
DEPENDENCY_FILES = {
    ".pre-commit-config.yaml",
    "cargo.lock",
    "cargo.toml",
    "composer.json",
    "composer.lock",
    "gemfile",
    "gemfile.lock",
    "go.mod",
    "go.sum",
    "package-lock.json",
    "package.json",
    "pipfile",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}


def gh_json(arguments: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(completed.stdout)


def is_dependency_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in DEPENDENCY_FILES or name.startswith("requirements") and name.endswith(".txt")


def fetch_check_runs(repository: str, head_sha: str) -> list[dict[str, Any]]:
    """Read-only fetch of a commit's check runs with each run's owning app.

    The pull request rollup omits which app created a check run, so query the
    commit's check runs directly; ``app`` distinguishes GitHub Actions from
    other check-reporting apps (for example CodeQL under "GitHub Advanced
    Security"). Statuses are normalized to the uppercase spellings the rollup
    uses. If the page truncates the result, a sentinel incomplete run keeps
    the classification non-passing.
    """
    data = gh_json(
        ["api", f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100"]
    )
    runs: list[dict[str, Any]] = []
    for run in data.get("check_runs", []):
        runs.append(
            {
                "name": run.get("name"),
                "app": (run.get("app") or {}).get("name"),
                "status": (run.get("status") or "").upper() or None,
                "conclusion": (run.get("conclusion") or "").upper() or None,
            }
        )
    if data.get("total_count", 0) > len(runs):
        runs.append({"name": None, "app": None, "status": "QUEUED", "conclusion": None})
    return runs


def classify_ci(checks: list[dict[str, Any]], check_runs: list[dict[str, Any]]) -> str:
    """Classify CI state from the PR rollup and the head commit's check runs.

    "passing" requires at least one completed run owned by the GitHub
    Actions app; green check runs from other apps, or statuses alone,
    classify as "no_checks" rather than "passing".
    """
    if not checks:
        return "no_checks"
    contexts = [check for check in checks if check.get("__typename") == "StatusContext"]
    if len(check_runs) + len(contexts) != len(checks):
        return "pending"
    if any(
        run.get("status") == "COMPLETED"
        and run.get("conclusion") not in ALLOWED_CHECK_CONCLUSIONS
        for run in check_runs
    ) or any(check.get("state") in {"FAILURE", "ERROR"} for check in contexts):
        return "failing"
    if any(run.get("status") != "COMPLETED" for run in check_runs) or any(
        check.get("state") != "SUCCESS" for check in contexts
    ):
        return "pending"
    if not any(run.get("app") == "GitHub Actions" for run in check_runs):
        return "no_checks"
    return "passing"


def risk_hints(title: str, paths: list[str], body: str = "") -> list[str]:
    hints: list[str] = []
    lowered = [path.lower() for path in paths]
    if any(path.startswith(".github/workflows/") for path in lowered):
        hints.append("workflow_change")
    if any(path.startswith(".github/dependabot") for path in lowered):
        hints.append("dependabot_config_change")
    if any(not is_dependency_file(path) for path in paths):
        hints.append("non_dependency_file_change")
    version_match = re.search(r"\bfrom\s+v?(\d+)(?:\.\d+)*\s+to\s+v?(\d+)(?:\.\d+)*\b", title, re.I)
    if version_match and int(version_match.group(2)) > int(version_match.group(1)):
        hints.append("possible_major_update")
    if "group" in title.lower() or "updates" in title.lower():
        hints.append("grouped_update_requires_inspection")
    body_match = re.search(r"\|\s*\S+\s+\|\s*`?v?(\d+)(?:\.\d+)*`?\s+\|\s*`?v?(\d+)(?:\.\d+)*`?\s*\|", body or "")
    if body_match and int(body_match.group(2)) > int(body_match.group(1)):
        hints.append("possible_major_update_in_group")
    return hints


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    user = gh_json(["api", "user"])["login"]
    results = gh_json(
        [
            "search",
            "prs",
            "--review-requested",
            user,
            "--state",
            "open",
            "--limit",
            str(args.limit),
            "--json",
            "number,title,url,repository,author,isDraft,updatedAt",
        ]
    )

    candidates = []
    for result in results:
        if result.get("author", {}).get("login", "").lower() not in {"dependabot[bot]", "app/dependabot"}:
            continue
        details = gh_json(
            [
                "pr",
                "view",
                result["url"],
                "--json",
                "url,number,title,state,isDraft,author,reviewRequests,headRefName,headRefOid,headRepository,baseRefName,mergeStateStatus,reviewDecision,files,statusCheckRollup,body",
            ]
        )
        review_requests = {item["login"].lower() for item in details.get("reviewRequests", [])}
        if user.lower() not in review_requests:
            continue
        paths = [item["path"] for item in details.get("files", [])]
        checks = details.get("statusCheckRollup") or []
        check_runs = fetch_check_runs(
            result["repository"]["nameWithOwner"], details["headRefOid"]
        )
        apps_by_name = {run["name"]: run["app"] for run in check_runs}
        candidates.append(
            {
                "url": details["url"],
                "repository": result["repository"]["nameWithOwner"],
                "number": details["number"],
                "title": details["title"],
                "head_sha": details["headRefOid"],
                "head_branch": details["headRefName"],
                "base_branch": details["baseRefName"],
                "draft": details["isDraft"],
                "merge_state": details["mergeStateStatus"],
                "review_decision": details.get("reviewDecision"),
                "review_requests": sorted(review_requests),
                "ci": classify_ci(checks, check_runs),
                "risk_hints": risk_hints(details["title"], paths, details.get("body") or ""),
                "changed_paths": paths,
                "checks": [
                    {
                        "name": check.get("name") or check.get("context"),
                        "type": check.get("__typename"),
                        "app": apps_by_name.get(check.get("name"))
                        if check.get("__typename") == "CheckRun"
                        else None,
                        "status": check.get("status"),
                        "conclusion": check.get("conclusion"),
                        "state": check.get("state"),
                        "workflow": check.get("workflowName"),
                    }
                    for check in checks
                ],
            }
        )

    indent = None if args.compact else 2
    print(json.dumps({"user": user, "candidates": candidates}, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        raise SystemExit(error.returncode) from error
