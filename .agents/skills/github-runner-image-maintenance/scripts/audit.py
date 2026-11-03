#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6,<7"]
# ///
"""Read-only PyPI/GitHub runner inventory. Run with uv run --script audit.py --help.

Candidates are catalog-derived, NOT verified compatible replacements. Complex
expressions, custom runners, and referenced workflows require manual inspection.
"""
from __future__ import annotations

import argparse
import base64
import itertools
import json
import re
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

import yaml

IMAGE_REPO = "actions/runner-images"
LABEL = re.compile(r"^(ubuntu|macos|windows)-(latest|\d+(?:\.\d+)*)(.*)$")


def label_parts(label):
    match = LABEL.fullmatch(label)
    if not match:
        return None
    family, version, suffix = match.groups()
    return family, (() if version == "latest" else tuple(map(int, version.split(".")))), suffix


def parse_catalog(text, sha):
    """Fail closed if the official Available Images table changes shape."""
    match = re.search(r"^## Available Images\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError("Available Images section missing")
    rows = [line.strip() for line in match[1].splitlines() if line.strip().startswith("|")]
    if not rows or [v.strip() for v in rows[0].strip("|").split("|")] != [
        "Image", "Architecture", "YAML Label", "Included Software"
    ]:
        raise ValueError("unrecognized catalog table schema")
    separators = rows[1].strip("|").split("|") if len(rows) > 1 else []
    if len(rows) < 3 or len(separators) != 4 or not all(
            re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in separators):
        raise ValueError("catalog table separator missing")
    refs = dict(re.findall(r"^\[([^\]]+)\]:\s*(https://\S+)", text, re.M))
    catalog = {}
    for row in rows[2:]:
        cells = [v.strip() for v in row.strip("|").split("|")]
        if len(cells) != 4 or cells[1] not in {"x64", "arm64"}:
            raise ValueError(f"unrecognized catalog row: {row}")
        labels = re.findall(r"`([^`]+)`", cells[2])
        remainder = re.sub(r"`[^`]+`|\bor\b|[,\s]", "", cells[2])
        if not labels or remainder or any(not re.fullmatch(r"[a-z0-9.-]+", label) for label in labels):
            raise ValueError(f"unparseable catalog labels: {row}")
        software = re.fullmatch(r"\[([^\]]+)\]", cells[3])
        if not software or software[1] not in refs:
            raise ValueError(f"missing included software reference: {row}")
        url = refs[software[1]].replace("/blob/main/", f"/blob/{sha}/")
        status = "deprecated" if "![deprecated]" in cells[0].lower() else (
            "preview" if re.search(r"!\[(preview|beta)\]", cells[0], re.I) else "ga")
        for label in labels:
            if label in catalog:
                raise ValueError(f"duplicate catalog label: {label}")
            catalog[label] = {"architecture": cells[1], "status": status,
                              "software_url": url, "image": cells[0],
                              "issues": sorted(set(re.findall(
                                  r"https://github.com/actions/runner-images/issues/\d+", cells[0])))}
    if not catalog:
        raise ValueError("empty image catalog")
    return catalog


def classify_label(label, catalog):
    result = {"literal": label, "status": "unknown_manual_review", "candidate": None,
              "requires_review": True}
    source = catalog.get(label)
    parts = label_parts(label)
    if not source or not parts:
        return result
    family, version, suffix = parts
    options = []
    for other, image in catalog.items():
        parsed = label_parts(other)
        if (parsed and parsed[0] == family and parsed[1] and parsed[2] == suffix
                and (family != "windows" or not version or
                     (parsed[1][0] >= 2000) == (version[0] >= 2000))
                and image["architecture"] == source["architecture"] and image["status"] == "ga"
                and not image.get("announcement_review")):
            options.append((parsed[1], other))
    result.update(catalog_status=source["status"], architecture=source["architecture"],
                  software_url=source["software_url"], announcement_urls=source["issues"])
    if options:
        newest, candidate = max(options)
        if not version or newest > version or source["status"] != "ga":
            result.update(status="candidate_requires_review", candidate=candidate,
                          candidate_software_url=catalog[candidate]["software_url"])
        else:
            result["status"] = "catalog_current" if source["status"] == "ga" else "manual_review"
    else:
        result["status"] = "manual_review"
    if source.get("announcement_review"):
        result.update(status="announcement_review_required",
                      announcement_urls=sorted(set(source["issues"] + source["announcement_review"])))
    return result


class WorkflowLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError(f"duplicate or nonscalar YAML key: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def matrix_rows(job):
    """Resolve bounded literal scalar matrices only; include merges original axes."""
    strategy = job.get("strategy", {})
    if not isinstance(strategy, dict):
        raise ValueError("dynamic strategy")
    matrix = strategy.get("matrix", {})
    if not isinstance(matrix, dict):
        raise ValueError("dynamic matrix")
    axes = {key: value for key, value in matrix.items() if key not in {"include", "exclude"}}
    if any(not isinstance(v, list) or not v or any(not isinstance(x, str) or "${{" in x for x in v)
           for v in axes.values()):
        raise ValueError("unsupported matrix axes")
    count = 1
    for values in axes.values():
        count *= len(values)
    if count > 256:
        raise ValueError("matrix expansion exceeds 256")
    include, exclude = matrix.get("include", []), matrix.get("exclude", [])
    for entries in (include, exclude):
        if (not isinstance(entries, list) or len(entries) > 256 or
                any(not isinstance(e, dict) or any(not isinstance(v, str) or "${{" in v
                                                  for v in e.values()) for e in entries)):
            raise ValueError("unsupported matrix include/exclude")
    originals = [dict(zip(axes, vals)) for vals in itertools.product(*axes.values())] if axes else []
    originals = [r for r in originals if not any(all(r.get(k) == v for k, v in e.items()) for e in exclude)]
    rows = [dict(r) for r in originals]
    extras = []
    for entry in include:
        matched = False
        for original, row in zip(originals, rows):
            if all(k not in original or original[k] == v for k, v in entry.items()):
                row.update(entry)
                matched = True
        if not matched:
            extras.append(dict(entry))
    if not matrix:
        return [{}]
    return rows + extras


def inventory(text, catalog):
    if len(text) > 2_000_000:
        raise ValueError("workflow exceeds 2 MB limit")
    # Reject anchors/aliases: recursive YAML structures are not a workflow resolver.
    try:
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
            raise ValueError("YAML anchors/aliases require manual review")
        document = yaml.load(text, Loader=WorkflowLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
        raise ValueError("workflow/jobs must be a mapping")
    findings = []
    for name, job in document["jobs"].items():
        if not isinstance(job, dict):
            raise ValueError(f"job {name} must be a mapping")
        base = {"job": name, "source_path": f"jobs.{name}.runs-on", "candidate": None,
                "requires_review": True, "original_selector": job.get("runs-on")}
        if "uses" in job:
            findings.append(dict(base, status="reference_manual_review", reference=job["uses"],
                                 source_path=f"jobs.{name}.uses"))
            continue
        try:
            rows = matrix_rows(job)
        except ValueError as exc:
            findings.append(dict(base, status="unresolved_manual_review", reason=str(exc)))
            continue
        for row in rows:
            selector = job.get("runs-on")
            source = base["source_path"]
            if isinstance(selector, list) and len(selector) == 1:
                selector = selector[0]
            expr = re.fullmatch(r"\s*\$\{\{\s*matrix\.([\w-]+)\s*\}\}\s*", selector or "") if isinstance(selector, str) else None
            if expr:
                selector = row.get(expr[1])
                source = f"jobs.{name}.strategy.matrix.{expr[1]}"
                matrix = job["strategy"]["matrix"]
                if isinstance(matrix.get(expr[1]), list) and selector in matrix[expr[1]]:
                    source += f"[{matrix[expr[1]].index(selector)}]"
                for i, addition in enumerate(matrix.get("include", [])):
                    if expr[1] in addition and all(row.get(k) == v for k, v in addition.items()):
                        source = f"jobs.{name}.strategy.matrix.include[{i}].{expr[1]}"
            entry = dict(base, source_path=source, matrix=row, resolved_selector=selector)
            if isinstance(selector, (dict, list)):
                entry.update(status="custom_runner_manual_review", reason="group or AND-label constraints")
            elif not isinstance(selector, str) or "${{" in selector:
                entry.update(status="unresolved_manual_review", reason="nonliteral runner expression")
            elif selector == "self-hosted":
                entry.update(status="custom_runner_manual_review", literal=selector)
            else:
                entry.update(classify_label(selector, catalog))
            findings.append(entry)
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            findings.append(dict(base, status="unresolved_manual_review", reason="nonliteral steps"))
        else:
            for i, step in enumerate(steps):
                if isinstance(step, dict) and isinstance(step.get("uses"), str) and step["uses"].startswith("./"):
                    findings.append(dict(base, status="reference_manual_review", reference=step["uses"],
                                         source_path=f"jobs.{name}.steps[{i}].uses"))
    return findings


class TimeoutTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 45
        return connection


class Client:
    """Only PyPI reads and GitHub REST GETs; no checkout or remote mutations."""
    def gh(self, endpoint):
        if endpoint.startswith(("-", "http")):
            raise ValueError("expected relative GitHub API endpoint")
        result = subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint],
            check=True, capture_output=True, text=True, timeout=45)
        return json.loads(result.stdout)

    def pages(self, endpoint, per_page=100, max_pages=10):
        result = []
        for page in range(1, max_pages + 1):
            separator = "&" if "?" in endpoint else "?"
            rows = self.gh(f"{endpoint}{separator}per_page={per_page}&page={page}")
            if not isinstance(rows, list):
                raise ValueError("expected paginated list")
            result.extend(rows)
            if len(rows) < per_page:
                return result
        raise ValueError(f"pagination bound reached: {endpoint}; inventory incomplete")

    def packages(self, username):
        with xmlrpc.client.ServerProxy("https://pypi.org/pypi", transport=TimeoutTransport()) as proxy:
            return proxy.user_packages(username)

    def pypi(self, name):
        request = urllib.request.Request(
            f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/json",
            headers={"User-Agent": "read-only-runner-audit/1"})
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000:
            raise ValueError("PyPI response exceeds 20 MB")
        return json.loads(data)

    def blob(self, repo, sha):
        data = self.gh(f"repos/{repo}/git/blobs/{sha}")
        if data.get("encoding") != "base64":
            raise ValueError("unsupported Git blob encoding")
        return base64.b64decode(data["content"]).decode("utf-8")


def repo_from_url(url):
    if not isinstance(url, str):
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() != "github.com":
        return None
    match = re.match(r"^/([\w.-]+)/([\w.-]+)(?:/|$)", parsed.path)
    if not match:
        return None
    return f"{match[1]}/{match[2].removesuffix('.git')}"


def unique_repositories(candidates):
    """Compare GitHub repo identities case-insensitively, preserving source tokens."""
    return set({repo.casefold(): repo for repo in sorted(candidates, reverse=True)}.values())


def description_sources(client, info, package):
    """Use published README links only with matching, SHA-pinned package metadata.

    Name similarity narrows API requests; it is not publication/source proof.
    An ambiguous or unreadable manifest remains an explicit discovery failure.
    """
    normalize = lambda value: re.sub(r"[-_.]+", "-", value).lower()
    name = normalize(info.get("name") or package)
    urls = re.findall(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
                      info.get("description") or "")
    candidates = unique_repositories({repo for url in urls if (repo := repo_from_url(url)) and
                  normalize(repo.rsplit("/", 1)[-1]) == name})
    if len(candidates) > 20:
        raise ValueError("too many published-description source candidates; manual review required")
    verified, failures = {}, []
    for repo in sorted(candidates):
        try:
            metadata = client.gh(f"repos/{repo}")
            if metadata.get("full_name", "").lower() != repo.lower():
                raise ValueError("canonical name differs; manual verification required")
            branch = urllib.parse.quote(metadata["default_branch"], safe="")
            sha = client.gh(f"repos/{repo}/commits/{branch}")["sha"]
            blob = client.gh(f"repos/{repo}/contents/pyproject.toml?ref={sha}")
            if blob.get("encoding") != "base64":
                raise ValueError("manifest is not base64")
            manifest = tomllib.loads(base64.b64decode(blob["content"]).decode())
            declared = manifest.get("project", {}).get("name") or manifest.get(
                "tool", {}).get("poetry", {}).get("name")
            if not isinstance(declared, str) or normalize(declared) != name:
                raise ValueError("source manifest package name does not match published package")
            verified[repo] = {"kind": "published_description_and_source_manifest",
                              "description_repository_url": f"https://github.com/{repo}",
                              "manifest_url": f"https://github.com/{repo}/blob/{sha}/pyproject.toml",
                              "manifest_name": declared, "sha": sha}
        except Exception as exc:
            failures.append(f"{repo}: {exc}")
    if not verified:
        raise ValueError(f"no verified published-description source: {failures or 'no matching links'}")
    return verified


def discover(client, username, requested):
    repositories, excluded, errors = {}, [], []
    try:
        packages = sorted(set(tuple(entry) for entry in client.packages(username)))
    except Exception as exc:
        return {}, [], [f"PyPI user discovery: {exc}"]
    for role, name in packages:
        if role not in {"Owner", "Maintainer"}:
            excluded.append({"package": name, "reason": f"unsupported PyPI role: {role}"})
            continue
        try:
            data = client.pypi(name)
            info = data["info"]
            if not info.get("version") or not data.get("urls"):
                excluded.append({"package": name, "reason": "no published release files for registry version"})
                continue
            urls = dict(info.get("project_urls") or {})
            if info.get("home_page"):
                urls["home_page"] = info["home_page"]
            candidates = unique_repositories({candidate for url in urls.values()
                                               if (candidate := repo_from_url(url))})
            source_proofs = {}
            if not candidates:
                source_proofs = description_sources(client, info, name)
                candidates = set(source_proofs)
            if len(candidates) != 1:
                raise ValueError(f"unmapped/ambiguous published GitHub project URLs: {sorted(candidates)}")
            repo = candidates.pop()
            metadata = client.gh(f"repos/{repo}")
            if metadata.get("full_name", "").lower() != repo.lower():
                raise ValueError("canonical GitHub full_name differs from registry source; manual verification required")
            if any(not isinstance(metadata.get(flag), bool) for flag in ("archived", "fork")):
                raise ValueError("unverified archived/fork metadata")
            if metadata.get("archived") or metadata.get("fork"):
                excluded.append({"package": name, "repository": repo,
                                 "reason": "archived" if metadata.get("archived") else "fork"})
                continue
            if not metadata.get("default_branch"):
                raise ValueError("missing default branch")
            repo = metadata["full_name"]
            entry = repositories.setdefault(repo, {"default_branch": metadata["default_branch"], "packages": []})
            entry["packages"].append({"name": name, "role": role, "version": info["version"],
                "registry_url": f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/json",
                "project_urls": urls, "verified_repository_url": f"https://github.com/{repo}",
                "source_evidence": source_proofs.get(repo, {"kind": "published_project_urls"}),
                "release_files": [file.get("filename") for file in data["urls"]]})
        except Exception as exc:
            excluded.append({"package": name, "reason": str(exc)})
            errors.append(f"package {name}: {exc}")
    selected = {r.lower() for r in requested}
    for repo in selected - {r.lower() for r in repositories}:
        errors.append(f"unmatched --repo (not verified published/nonarchived/nonfork): {repo}")
    if selected:
        for repo in list(repositories):
            if repo.lower() not in selected:
                excluded.append({"repository": repo, "reason": "outside explicit --repo filter"})
                del repositories[repo]
    return dict(sorted(repositories.items())), excluded, errors


def apply_announcements(catalog, issues):
    """Associate positive impact/title label mentions, never platform checkboxes.

    Dates and brownout intervals intentionally remain raw source: contradictory
    announcement times must not be silently repaired by this inventory helper.
    """
    for issue in issues:
        body = issue.get("body") or ""
        impact = re.search(r"^#{1,6}\s*Possible impact\s*\n(.*?)(?=^#{1,6}\s|\Z)", body, re.M | re.S | re.I)
        scoped = (issue.get("title") or "") + "\n" + (impact[1] if impact else "")
        labels = set(re.findall(r"(?<![\w-])(?:ubuntu|macos|windows|xcode)-[a-z0-9.-]+", scoped, re.I))
        for label in labels:
            label = label.rstrip(".").lower()
            if label in catalog:
                catalog[label].setdefault("announcement_review", []).append(issue["html_url"])


def official_evidence(client):
    metadata = client.gh(f"repos/{IMAGE_REPO}")
    branch = urllib.parse.quote(metadata["default_branch"], safe="")
    sha = client.gh(f"repos/{IMAGE_REPO}/commits/{branch}")["sha"]
    readme = client.gh(f"repos/{IMAGE_REPO}/contents/README.md?ref={sha}")
    if readme.get("encoding") != "base64":
        raise ValueError("catalog README not base64")
    catalog = parse_catalog(base64.b64decode(readme["content"]).decode(), sha)
    evidence = {"sha": sha, "catalog_url": f"https://github.com/{IMAGE_REPO}/blob/{sha}/README.md",
                "announcements": [], "errors": [], "dates": "raw source only; manual review required"}
    try:
        evidence["announcements"] = client.pages(
            f"repos/{IMAGE_REPO}/issues?labels=Announcement&state=open&sort=updated&direction=desc")
    except Exception as exc:
        evidence["errors"].append(f"announcements: {exc}")
    linked = {url for image in catalog.values() for url in image["issues"]}
    known = {issue["html_url"] for issue in evidence["announcements"]}
    for url in sorted(linked - known):
        try:
            evidence["announcements"].append(client.gh(f"repos/{IMAGE_REPO}/issues/{url.rsplit('/', 1)[-1]}"))
        except Exception as exc:
            evidence["errors"].append(f"linked announcement {url}: {exc}")
    evidence["announcements"] = [{k: issue.get(k) for k in
        ("number", "title", "body", "html_url", "updated_at", "state")} for issue in evidence["announcements"]]
    apply_announcements(catalog, evidence["announcements"])
    return catalog, evidence


def audit_repos(client, repositories, catalog):
    results = []
    for repo, metadata in repositories.items():
        entry = dict(repository=repo, packages=metadata["packages"], findings=[], errors=[])
        results.append(entry)
        try:
            branch = urllib.parse.quote(metadata["default_branch"], safe="")
            sha = client.gh(f"repos/{repo}/commits/{branch}")["sha"]
            entry["sha"] = sha
            tree = client.gh(f"repos/{repo}/git/trees/{sha}?recursive=1")
            if tree.get("truncated"):
                entry["errors"].append("recursive tree truncated; workflow inventory incomplete")
            for item in tree["tree"]:
                path = item["path"]
                if not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", path) or item["type"] != "blob":
                    continue
                try:
                    findings = inventory(client.blob(repo, item["sha"]), catalog)
                    for finding in findings:
                        finding.update(workflow=path, repository=repo, sha=sha,
                            source_url=f"https://github.com/{repo}/blob/{sha}/{path}")
                    entry["findings"].extend(findings)
                except Exception as exc:
                    entry["errors"].append(f"{path}: {exc}")
        except Exception as exc:
            entry["errors"].append(str(exc))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pypi-user", required=True, help="PyPI Owner/Maintainer username (for example d33bs)")
    parser.add_argument("--repo", action="append", default=[], help="owner/repo FILTER of published mappings; repeatable")
    parser.add_argument("--output", type=Path, help="optional local JSON report; otherwise stdout only")
    args = parser.parse_args(argv)
    for repo in args.repo:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            parser.error(f"invalid --repo: {repo}")
    client = Client()
    repositories, excluded, errors = discover(client, args.pypi_user, args.repo)
    evidence, catalog = {}, {}
    try:
        catalog, evidence = official_evidence(client)
        errors.extend(evidence["errors"])
    except Exception as exc:
        errors.append(f"official evidence: {exc}")
    results = audit_repos(client, repositories, catalog)
    findings = [finding for repo in results for finding in repo["findings"]]
    report = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "pypi_user": args.pypi_user, "repositories": results, "excluded": excluded,
        "official_evidence": evidence, "errors": errors,
        "complete": not errors and not any(repo["errors"] for repo in results),
        "counts": {"repositories": len(results), "excluded": len(excluded), "findings": len(findings),
                   "candidates": sum(bool(f.get("candidate")) for f in findings)},
        "limitations": "Catalog-derived candidates require official announcement and compatibility review. "
                       "No edits, CI execution, or transitive reference resolution. Dynamic/custom selectors "
                       "remain manual review. Dates/intervals are raw and may conflict. Open announcements "
                       "plus catalog-linked issues only; closed unlinked announcements are not exhaustive."}
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        sys.stdout.write(encoded)
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
