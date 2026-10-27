"""Deterministic read-only runner auditor tests; no live network or gh calls."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import base64
import json
import io
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit", ROOT / "scripts/audit.py")
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
CATALOG_TEXT = (ROOT / "tests/fixtures/catalog.md").read_text()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = audit.parse_catalog(CATALOG_TEXT, "abc123")

    def test_architecture_size_and_explicit_version(self):
        for old, new in {"macos-14": "macos-26", "macos-14-large": "macos-26-large",
                         "macos-14-xlarge": "macos-26-xlarge",
                         "ubuntu-latest": "ubuntu-26.04",
                         "windows-latest": "windows-2025"}.items():
            with self.subTest(old=old):
                result = audit.classify_label(old, self.catalog)
                self.assertEqual(result["candidate"], new)
                self.assertTrue(result["requires_review"])
        self.assertEqual(audit.classify_label("macos-26-intel", self.catalog)["candidate"], None)
        self.assertEqual(audit.classify_label("windows-11-vs2026-arm", self.catalog)["status"], "catalog_current")
        self.assertNotIn("ubuntu-99.04", self.catalog)
        self.assertIn("/blob/abc123/", self.catalog["ubuntu-26.04"]["software_url"])


    def test_windows_client_and_server_versions_stay_distinct(self):
        source = {"architecture": "x64", "status": "ga", "software_url": "source", "issues": []}
        catalog = {name: dict(source) for name in ("windows-11", "windows-12", "windows-2022", "windows-2025")}
        self.assertEqual(audit.classify_label("windows-11", catalog)["candidate"], "windows-12")
        self.assertEqual(audit.classify_label("windows-2022", catalog)["candidate"], "windows-2025")

    def test_catalog_schema_failures(self):
        for text in ("", CATALOG_TEXT.replace("YAML Label", "Labels"),
                     CATALOG_TEXT.replace("`ubuntu-26.04`", "ubuntu-26.04", 1),
                     CATALOG_TEXT.replace("[ubuntu26] |", "[missing] |", 1),
                     CATALOG_TEXT.replace("`ubuntu-24.04-arm`", "`ubuntu-26.04-arm`", 1)):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                audit.parse_catalog(text, "sha")

    def test_preview_unknown_slim_and_arm(self):
        for label in ("unknown", "ubuntu-slim", "ubuntu-20.04"):
            self.assertIsNone(audit.classify_label(label, self.catalog)["candidate"])
            self.assertNotEqual(audit.classify_label(label, self.catalog)["status"], "catalog_current")
        self.assertEqual(audit.classify_label("ubuntu-24.04", self.catalog)["candidate"], "ubuntu-26.04")
        self.assertEqual(audit.classify_label("ubuntu-24.04-arm", self.catalog)["candidate"], "ubuntu-26.04-arm")
        self.assertEqual(audit.classify_label("ubuntu-28.04", self.catalog)["catalog_status"], "preview")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.catalog = audit.parse_catalog(CATALOG_TEXT, "sha")

    def test_inventory_matrix_constraints_and_references(self):
        rows = audit.inventory((ROOT / "tests/fixtures/workflow.yml").read_text(), self.catalog)
        by_job = {}
        for row in rows:
            by_job.setdefault(row["job"], []).append(row)
        self.assertEqual(by_job["scalar"][0]["candidate"], "macos-26")
        self.assertEqual([r["literal"] for r in by_job["matrix"]], ["macos-14", "macos-14", "macos-26"])
        self.assertIn("matrix.runner", by_job["matrix"][0]["source_path"])
        for name in ("mixed", "constrained", "group"):
            self.assertEqual(by_job[name][0]["status"], "custom_runner_manual_review")
            self.assertIsNone(by_job[name][0]["candidate"])
        self.assertEqual(by_job["dynamic"][0]["status"], "unresolved_manual_review")
        self.assertEqual(by_job["reuse"][0]["status"], "reference_manual_review")
        self.assertEqual(by_job["local"][-1]["reference"], "./.github/actions/install")

    def test_invalid_yaml_fails_closed(self):
        for text in ("", "[]", "jobs: []", "jobs: {}\njobs: {}", "jobs: {a: {runs-on: ubuntu-24.04, runs-on: macos-14}}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                audit.inventory(text, self.catalog)

    def test_pure_include_and_unresolved_matrix(self):
        text = 'jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        include:\n          - os: macos-14\n          - os: ubuntu-24.04\n'
        self.assertEqual(len(audit.inventory(text, self.catalog)), 2)
        text = text.replace('include:\n          - os: macos-14\n          - os: ubuntu-24.04', '${{ fromJSON(inputs.matrix) }}')
        self.assertEqual(audit.inventory(text, self.catalog)[0]["status"], "unresolved_manual_review")


    def test_matrix_include_merges_only_original_axes(self):
        rows = audit.matrix_rows({"strategy": {"matrix": {"os": ["a", "b"],
            "include": [{"extra": "green"}, {"os": "a", "extra": "pink"}, {"os": "c"}]}}})
        self.assertEqual(rows, [{"os": "a", "extra": "pink"}, {"os": "b", "extra": "green"}, {"os": "c"}])
        self.assertEqual(audit.matrix_rows({"strategy": {"matrix": {"os": ["a"], "exclude": [{"os": "a"}]}}}), [])

    def test_matrix_limits_and_nested_objects_remain_manual(self):
        for matrix in ({"os": [{"name": "ubuntu-24.04"}]}, {"os": ["${{ inputs.os }}"]},
                       {"os": [str(i) for i in range(257)]}, {"include": "dynamic"}):
            with self.subTest(matrix=str(matrix)[:50]), self.assertRaises(ValueError):
                audit.matrix_rows({"strategy": {"matrix": matrix}})

    def test_on_key_is_not_boolean_and_aliases_are_rejected(self):
        document = audit.yaml.load("on: push\njobs: {}", Loader=audit.WorkflowLoader)
        self.assertIn("on", document)
        with self.assertRaises(ValueError):
            audit.inventory("jobs: {a: &a {runs-on: ubuntu-24.04}, b: *a}", self.catalog)

    def test_nonliteral_selector_and_singleton_array(self):
        for selector in ("${{ env.OS }}", "${{ matrix.os || 'ubuntu-24.04' }}"):
            rows = audit.inventory("jobs: {a: {runs-on: \"" + selector + "\"}}", self.catalog)
            self.assertEqual(rows[0]["status"], "unresolved_manual_review")
        rows = audit.inventory("jobs: {a: {runs-on: [ubuntu-24.04]}}", self.catalog)
        self.assertEqual(rows[0]["candidate"], "ubuntu-26.04")


class DiscoveryTests(unittest.TestCase):
    def test_publication_and_repository_filters(self):
        client = Mock()
        client.packages.return_value = [("Owner", "good"), ("Maintainer", "archived"),
            ("Owner", "fork"), ("Owner", "unpublished"), ("Owner", "ambiguous"),
            ("Owner", "error"), ("Owner", "redirect")]
        def pypi(name):
            if name == "error":
                raise OSError("offline")
            return {"info": {"version": "1.2.3", "project_urls": {
                "Source": f"https://github.com/o/{name}",
                **({"Other": "https://github.com/o/other"} if name == "ambiguous" else {})}},
                "urls": [] if name == "unpublished" else [{"filename": "package.whl"}]}
        client.pypi.side_effect = pypi
        client.gh.side_effect = lambda path: {"full_name": "o/renamed" if path == "repos/o/redirect" else path[6:],
            "archived": path.endswith("archived"), "fork": path.endswith("fork"), "default_branch": "main"}
        repos, excluded, errors = audit.discover(client, "owner", [])
        self.assertEqual(list(repos), ["o/good"])
        self.assertEqual(repos["o/good"]["packages"][0]["version"], "1.2.3")
        self.assertEqual(len(excluded), 6)
        self.assertEqual(len(errors), 3)  # ambiguous, failed network, canonical mismatch
        repos, _, errors = audit.discover(client, "owner", ["o/missing"])
        self.assertEqual(repos, {})
        self.assertTrue(any("unmatched --repo" in e for e in errors))

    def test_github_source_casing_is_not_false_ambiguity(self):
        self.assertEqual(audit.unique_repositories({"O/Repo", "o/repo"}), {"O/Repo"})
        client = Mock()
        client.packages.return_value = [("Owner", "good")]
        client.pypi.return_value = {"info": {"version": "1", "project_urls": {
            "Source": "https://github.com/O/Repo", "Issues": "https://github.com/o/repo/issues"}},
            "urls": [{"filename": "good.whl"}]}
        client.gh.return_value = {"full_name": "O/Repo", "archived": False, "fork": False, "default_branch": "main"}
        repos, _, errors = audit.discover(client, "owner", [])
        self.assertEqual(list(repos), ["O/Repo"])
        self.assertFalse(errors)

    def test_description_fallback_requires_matching_pinned_manifest(self):
        client = Mock()
        client.packages.return_value = [("Owner", "some-package")]
        client.pypi.return_value = {"info": {"name": "some-package", "version": "1.0",
            "description": "Source: https://github.com/o/some_package and https://github.com/tool/unrelated"},
            "urls": [{"filename": "some_package.whl"}]}
        def gh(path):
            if path == "repos/o/some_package":
                return {"full_name": "o/some_package", "archived": False, "fork": False, "default_branch": "main"}
            if "/commits/" in path:
                return {"sha": "manifestsha"}
            self.assertIn("pyproject.toml?ref=manifestsha", path)
            return {"encoding": "base64", "content": base64.b64encode(b'[project]\nname="some-package"\n').decode()}
        client.gh.side_effect = gh
        repos, excluded, errors = audit.discover(client, "owner", [])
        self.assertFalse(errors)
        self.assertFalse(excluded)
        proof = repos["o/some_package"]["packages"][0]["source_evidence"]
        self.assertEqual(proof["kind"], "published_description_and_source_manifest")
        self.assertEqual(proof["sha"], "manifestsha")
        client.gh.side_effect = lambda path: gh(path) if "/contents/" not in path else {
            "encoding": "base64", "content": base64.b64encode(b'[project]\nname="wrong-package"\n').decode()}
        repos, excluded, errors = audit.discover(client, "owner", [])
        self.assertFalse(repos)
        self.assertTrue(errors)
        self.assertIn("does not match", errors[0])

    def test_repo_parser_never_guesses_external_or_malformed_urls(self):
        for url in ("https://example.com/o/r", "https://github.com/o", "https://github.com/o/r%2Fbad"):
            self.assertIsNone(audit.repo_from_url(url))
        self.assertEqual(audit.repo_from_url("https://github.com/o/r.git/tree/main"), "o/r")


class TransportTests(unittest.TestCase):
    @patch.object(audit.subprocess, "run")
    def test_gh_is_get_with_timeout_and_json(self, run):
        run.return_value.stdout = '{"ok": true}'
        self.assertEqual(audit.Client().gh("repos/o/r"), {"ok": True})
        args, kwargs = run.call_args
        self.assertIn("GET", args[0])
        self.assertEqual(kwargs["timeout"], 45)
        self.assertIn("github.com", args[0])

    def test_bounded_pages_and_blob(self):
        client = audit.Client()
        client.gh = Mock(side_effect=[[{"n": 1}], []])
        self.assertEqual(client.pages("repos/o/r/issues", per_page=1), [{"n": 1}])
        client.gh = Mock(return_value=[{"n": 1}])
        with self.assertRaises(ValueError):
            client.pages("repos/o/r/issues", per_page=1, max_pages=2)
        client.gh = Mock(return_value={"encoding": "base64", "content": base64.b64encode(b"hello").decode()})
        self.assertEqual(client.blob("o/r", "abc"), "hello")


class ReportTests(unittest.TestCase):
    @patch.object(audit.xmlrpc.client, "ServerProxy")
    @patch.object(audit.urllib.request, "urlopen")
    @patch.object(audit.subprocess, "run")
    def test_end_to_end_cli_mocking_only_network_boundaries(self, run, urlopen, proxy):
        proxy.return_value.__enter__.return_value.user_packages.return_value = [("Owner", "package")]
        package = {"info": {"version": "1.0", "project_urls": {"Source": "https://github.com/o/r"}},
                   "urls": [{"filename": "package.whl"}]}
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(package).encode()
        def respond(command, **kwargs):
            path = command[-1]
            if path == "repos/o/r":
                data = {"full_name": "o/r", "archived": False, "fork": False, "default_branch": "main"}
            elif path == "repos/actions/runner-images":
                data = {"default_branch": "main"}
            elif "/commits/" in path:
                data = {"sha": "fixedsha"}
            elif "/contents/" in path:
                data = {"encoding": "base64", "content": base64.b64encode(CATALOG_TEXT.encode()).decode()}
            elif "/git/trees/" in path:
                data = {"truncated": False, "tree": [{"type": "blob", "path": ".github/workflows/ci.yml", "sha": "blob"}]}
            elif "/git/blobs/" in path:
                data = {"encoding": "base64", "content": base64.b64encode(b"jobs: {ci: {runs-on: ubuntu-latest}}").decode()}
            elif "/issues?" in path:
                data = []
            elif "/issues/" in path:
                data = {"number": 13518, "title": "macos-14", "body": "raw", "html_url": "issue", "updated_at": "now"}
            else:
                raise AssertionError(path)
            self.assertEqual(command[command.index("--method") + 1], "GET")
            return subprocess.CompletedProcess(command, 0, json.dumps(data), "")
        run.side_effect = respond
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(audit.main(["--pypi-user", "owner", "--repo", "o/r"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["repositories"][0]["packages"][0]["version"], "1.0")
        self.assertEqual(report["repositories"][0]["findings"][0]["candidate"], "ubuntu-26.04")
        self.assertEqual(report["counts"]["repositories"], 1)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 45)
        proxy.return_value.__enter__.return_value.user_packages.assert_called_once_with("owner")

    def test_official_catalog_and_linked_announcements(self):
        client = Mock()
        issue = {"number": 13518, "title": "macos-14 retirement", "body": "Raw inconsistent intervals",
                 "html_url": "https://github.com/actions/runner-images/issues/13518", "updated_at": "source timestamp"}
        def gh(path):
            if path == "repos/actions/runner-images":
                return {"default_branch": "main"}
            if "/commits/" in path:
                return {"sha": "catalogsha"}
            if "/contents/" in path:
                self.assertIn("ref=catalogsha", path)
                return {"encoding": "base64", "content": base64.b64encode(CATALOG_TEXT.encode()).decode()}
            return issue
        client.gh.side_effect = gh
        client.pages.return_value = []
        catalog, evidence = audit.official_evidence(client)
        self.assertEqual(evidence["sha"], "catalogsha")
        self.assertEqual(evidence["announcements"][0]["body"], issue["body"])
        self.assertEqual(evidence["announcements"][0]["updated_at"], "source timestamp")
        self.assertEqual(evidence["errors"], [])
        client.pages.side_effect = OSError("announcements unavailable")
        _, evidence = audit.official_evidence(client)
        self.assertIn("announcements unavailable", evidence["errors"][0])
        self.assertIn("macos-14", catalog)

    def test_platform_checkboxes_and_mitigation_are_not_affected_labels(self):
        catalog = audit.parse_catalog(CATALOG_TEXT, "sha")
        audit.apply_announcements(catalog, [{"title": "A change", "html_url": "issue", "body":
            "### Affected platforms\n- [ ] `macos-26`\n### Possible impact\n`ubuntu-24.04`\n### Mitigation\n`ubuntu-26.04`"}])
        self.assertNotIn("announcement_review", catalog["macos-26"])
        self.assertNotIn("announcement_review", catalog["ubuntu-26.04"])
        self.assertIn("announcement_review", catalog["ubuntu-24.04"])

    def test_cli_success_counts_and_optional_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            rows = [{"repository": "o/a", "errors": [], "findings": [{"candidate": "ubuntu-26.04"}]}]
            with patch.object(audit, "discover", return_value=({"o/a": {}}, [], [])), \
                 patch.object(audit, "official_evidence", return_value=({}, {"errors": []})), \
                 patch.object(audit, "audit_repos", return_value=rows):
                self.assertEqual(audit.main(["--pypi-user", "owner", "--output", str(output)]), 0)
            data = json.loads(output.read_text())
            self.assertTrue(data["complete"])
            self.assertEqual(data["counts"], {"repositories": 1, "excluded": 0, "findings": 1, "candidates": 1})

    def test_multi_repo_pinned_workflows_and_individual_errors(self):
        client = Mock()
        def gh(path):
            if "/commits/" in path:
                return {"sha": "pinned"}
            return {"truncated": True, "tree": [
                {"path": ".github/workflows/good.yml", "type": "blob", "sha": "good"},
                {"path": ".github/workflows/bad.yaml", "type": "blob", "sha": "bad"},
                {"path": "other.yml", "type": "blob", "sha": "ignored"}]}
        client.gh.side_effect = gh
        client.blob.side_effect = lambda repo, sha: "jobs: {test: {runs-on: macos-14}}" if sha == "good" else "[]"
        repos = {r: {"default_branch": "main", "packages": []} for r in ("o/a", "o/b")}
        report = audit.audit_repos(client, repos, audit.parse_catalog(CATALOG_TEXT, "catalog"))
        self.assertEqual(len(report), 2)
        for row in report:
            self.assertEqual(row["sha"], "pinned")
            self.assertEqual(len(row["errors"]), 2)
            self.assertEqual(row["findings"][0]["candidate"], "macos-26")
            self.assertIn("/blob/pinned/", row["findings"][0]["source_url"])
        self.assertTrue(all("pinned?recursive=1" in c.args[0] for c in client.gh.call_args_list if "/git/trees/" in c.args[0]))

    def test_announcement_scope_preserves_raw_uncertainty(self):
        catalog = audit.parse_catalog(CATALOG_TEXT, "sha")
        issues = [{"number": 42, "title": "Ubuntu deprecation", "body":
            "### Possible impact\n`ubuntu-24.04` will be affected.\n### Mitigation\nUse `ubuntu-26.04`.\nEnd before start: raw source.",
            "html_url": "https://github.com/actions/runner-images/issues/42", "updated_at": "raw"}]
        audit.apply_announcements(catalog, issues)
        self.assertEqual(catalog["ubuntu-24.04"]["announcement_review"], [issues[0]["html_url"]])
        self.assertNotIn("announcement_review", catalog["ubuntu-26.04"])
        result = audit.classify_label("ubuntu-24.04", catalog)
        self.assertEqual(result["status"], "announcement_review_required")
        self.assertEqual(result["candidate"], "ubuntu-26.04")

    @patch.object(audit, "audit_repos", return_value=[])
    @patch.object(audit, "official_evidence", side_effect=OSError("catalog unavailable"))
    @patch.object(audit, "discover", return_value=({}, [], ["discovery failed"]))
    def test_cli_failure_still_json_and_nonzero(self, *_):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(audit.main(["--pypi-user", "owner"]), 1)
        data = json.loads(output.getvalue())
        self.assertFalse(data["complete"])
        self.assertEqual(data["repositories"], [])
        self.assertEqual(len(data["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
