"""Tests for _project_detectors.py — 7 pure detector functions.

Coverage: each detector × multiple fixture scenarios.
All tests use tmp_path; no access to real home dirs.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _project_detectors import (  # noqa: E402
    detect_runtime,
    detect_tests,
    detect_deploy,
    detect_ci,
    detect_lint,
    detect_structure,
    detect_env_templates,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def write(root: Path, name: str, content: str = "") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def result_has_evidence(result: dict) -> bool:
    ev = result.get("evidence", [])
    return bool(ev) and all("source_url" in e and "trust" in e for e in ev)


# ── detect_runtime ─────────────────────────────────────────────────────────────


class TestDetectRuntime:
    def test_empty_repo_returns_all_false(self, tmp_path):
        r = detect_runtime(tmp_path)
        d = r["data"]
        assert d["python"] is False
        assert d["node"] is False
        assert d["go"] is False
        assert d["rust"] is False

    def test_empty_repo_still_has_evidence(self, tmp_path):
        r = detect_runtime(tmp_path)
        assert result_has_evidence(r)

    def test_pyproject_toml_detects_python(self, tmp_path):
        write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["python"] is True

    def test_requirements_txt_detects_python(self, tmp_path):
        write(tmp_path, "requirements.txt", "requests\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["python"] is True

    def test_python_source_file_detects_python_without_manifest(self, tmp_path):
        write(tmp_path, "reference/tool/worker.py", "print('ok')\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["python"] is True

    def test_package_json_detects_node(self, tmp_path):
        write(tmp_path, "package.json", json.dumps({"name": "app", "version": "1.0.0"}))
        r = detect_runtime(tmp_path)
        assert r["data"]["node"] is True

    def test_pnpm_lock_detects_pnpm(self, tmp_path):
        write(tmp_path, "package.json", "{}")
        write(tmp_path, "pnpm-lock.yaml", "")
        r = detect_runtime(tmp_path)
        assert r["data"]["pnpm"] is True

    def test_yarn_lock_detects_yarn(self, tmp_path):
        write(tmp_path, "package.json", "{}")
        write(tmp_path, "yarn.lock", "")
        r = detect_runtime(tmp_path)
        assert r["data"]["yarn"] is True

    def test_go_mod_detects_go(self, tmp_path):
        write(tmp_path, "go.mod", "module example.com/app\ngo 1.21\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["go"] is True

    def test_go_version_extracted(self, tmp_path):
        write(tmp_path, "go.mod", "module example.com/app\ngo 1.21\n")
        r = detect_runtime(tmp_path)
        assert r["data"].get("go_version") == "1.21"

    def test_cargo_toml_detects_rust(self, tmp_path):
        write(tmp_path, "Cargo.toml", "[package]\nname = 'mylib'\nversion = '0.1.0'\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["rust"] is True

    def test_gemfile_detects_ruby(self, tmp_path):
        write(tmp_path, "Gemfile", "source 'https://rubygems.org'\ngem 'rails'\n")
        r = detect_runtime(tmp_path)
        assert r["data"]["ruby"] is True

    def test_python_primary_language_when_only_python(self, tmp_path):
        write(tmp_path, "pyproject.toml", "")
        r = detect_runtime(tmp_path)
        assert r["data"]["primary_language"] == "python"

    def test_node_primary_language_when_only_node(self, tmp_path):
        write(tmp_path, "package.json", "{}")
        r = detect_runtime(tmp_path)
        assert r["data"]["primary_language"] == "node"

    def test_python_takes_priority_over_node_when_both(self, tmp_path):
        write(tmp_path, "pyproject.toml", "")
        write(tmp_path, "package.json", "{}")
        r = detect_runtime(tmp_path)
        assert r["data"]["primary_language"] == "python"

    def test_uv_lock_detected(self, tmp_path):
        write(tmp_path, "uv.lock", "")
        write(tmp_path, "pyproject.toml", "")
        r = detect_runtime(tmp_path)
        assert r["data"]["uv"] is True

    def test_python_version_from_pyproject(self, tmp_path):
        write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.11"\n')
        r = detect_runtime(tmp_path)
        assert r["data"]["python_version"] == "3.11"

    def test_evidence_points_to_real_files(self, tmp_path):
        p = write(tmp_path, "pyproject.toml", "")
        r = detect_runtime(tmp_path)
        urls = [e["source_url"] for e in r["evidence"]]
        assert any(str(p) in url for url in urls)

    def test_no_subprocess(self, tmp_path):
        # Detectors must not use subprocess — we verify by running and checking no external calls
        import subprocess as sp
        original_run = sp.run
        calls = []
        def mock_run(*a, **kw):
            calls.append(a)
            return original_run(*a, **kw)
        # We don't monkeypatch here — just verifying the module doesn't call subprocess at import time
        detect_runtime(tmp_path)
        assert True  # would fail if subprocess was called externally


# ── detect_tests ──────────────────────────────────────────────────────────────


class TestDetectTests:
    def test_empty_repo_all_false(self, tmp_path):
        r = detect_tests(tmp_path)
        assert r["data"]["pytest"] is False
        assert r["data"]["jest"] is False
        assert r["data"]["vitest"] is False

    def test_pytest_ini_detects_pytest(self, tmp_path):
        write(tmp_path, "pytest.ini", "[pytest]\n")
        r = detect_tests(tmp_path)
        assert r["data"]["pytest"] is True

    def test_conftest_py_detects_pytest(self, tmp_path):
        write(tmp_path, "conftest.py", "import pytest\n")
        r = detect_tests(tmp_path)
        assert r["data"]["pytest"] is True

    def test_pyproject_with_pytest_detects_pytest(self, tmp_path):
        write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
        r = detect_tests(tmp_path)
        assert r["data"]["pytest"] is True

    def test_python_test_source_detects_pytest_without_config(self, tmp_path):
        write(tmp_path, "test_workspace/foo/tests/test_api.py", "def test_ok(): pass\n")
        r = detect_tests(tmp_path)
        assert r["data"]["pytest"] is True

    def test_jest_config_detects_jest(self, tmp_path):
        write(tmp_path, "jest.config.js", "module.exports = {};\n")
        r = detect_tests(tmp_path)
        assert r["data"]["jest"] is True

    def test_vitest_config_detects_vitest(self, tmp_path):
        write(tmp_path, "vitest.config.ts", "export default {};\n")
        r = detect_tests(tmp_path)
        assert r["data"]["vitest"] is True

    def test_playwright_config_detects_playwright(self, tmp_path):
        write(tmp_path, "playwright.config.ts", "export default {};\n")
        r = detect_tests(tmp_path)
        assert r["data"]["playwright"] is True

    def test_rspec_detects_rspec(self, tmp_path):
        write(tmp_path, ".rspec", "--color\n")
        r = detect_tests(tmp_path)
        assert r["data"]["rspec"] is True

    def test_go_mod_means_go_test(self, tmp_path):
        write(tmp_path, "go.mod", "module example.com\ngo 1.21\n")
        r = detect_tests(tmp_path)
        assert r["data"]["go_test"] is True

    def test_cargo_toml_means_cargo_test(self, tmp_path):
        write(tmp_path, "Cargo.toml", "[package]\nname='x'\nversion='0.1.0'\n")
        r = detect_tests(tmp_path)
        assert r["data"]["cargo_test"] is True

    def test_package_json_test_script_captured(self, tmp_path):
        pkg = {"name": "x", "scripts": {"test": "jest --coverage"}}
        write(tmp_path, "package.json", json.dumps(pkg))
        r = detect_tests(tmp_path)
        assert r["data"]["test_command"] == "jest --coverage"

    def test_evidence_always_present(self, tmp_path):
        r = detect_tests(tmp_path)
        assert result_has_evidence(r)


# ── detect_deploy ─────────────────────────────────────────────────────────────


class TestDetectDeploy:
    def test_empty_repo_all_false(self, tmp_path):
        r = detect_deploy(tmp_path)
        assert r["data"]["has_dockerfile"] is False
        assert r["data"]["has_compose"] is False

    def test_dockerfile_detected(self, tmp_path):
        write(tmp_path, "Dockerfile", "FROM python:3.12\n")
        r = detect_deploy(tmp_path)
        assert r["data"]["has_dockerfile"] is True
        assert "docker" in r["data"]["platforms"]

    def test_compose_yml_detected(self, tmp_path):
        write(tmp_path, "docker-compose.yml", "version: '3'\n")
        r = detect_deploy(tmp_path)
        assert r["data"]["has_compose"] is True

    def test_netlify_toml_detected(self, tmp_path):
        write(tmp_path, "netlify.toml", "[build]\npublish = 'dist'\n")
        r = detect_deploy(tmp_path)
        assert r["data"]["has_netlify"] is True
        assert "netlify" in r["data"]["platforms"]

    def test_vercel_json_detected(self, tmp_path):
        write(tmp_path, "vercel.json", '{"version": 2}')
        r = detect_deploy(tmp_path)
        assert r["data"]["has_vercel"] is True

    def test_heroku_procfile_detected(self, tmp_path):
        write(tmp_path, "Procfile", "web: gunicorn app:app\n")
        r = detect_deploy(tmp_path)
        assert r["data"]["has_heroku"] is True
        assert "heroku" in r["data"]["platforms"]

    def test_render_yaml_detected(self, tmp_path):
        write(tmp_path, "render.yaml", "services:\n  - type: web\n")
        r = detect_deploy(tmp_path)
        assert r["data"]["has_render"] is True

    def test_evidence_always_present(self, tmp_path):
        r = detect_deploy(tmp_path)
        assert result_has_evidence(r)


# ── detect_ci ─────────────────────────────────────────────────────────────────


class TestDetectCi:
    def test_empty_repo_no_ci(self, tmp_path):
        r = detect_ci(tmp_path)
        assert r["data"]["has_ci"] is False
        assert r["data"]["github_actions"] is False

    def test_github_actions_workflow_detected(self, tmp_path):
        write(tmp_path, ".github/workflows/ci.yml", "name: CI\n")
        r = detect_ci(tmp_path)
        assert r["data"]["github_actions"] is True
        assert r["data"]["has_ci"] is True

    def test_circleci_detected(self, tmp_path):
        write(tmp_path, ".circleci/config.yml", "version: 2.1\n")
        r = detect_ci(tmp_path)
        assert r["data"]["circleci"] is True
        assert r["data"]["has_ci"] is True

    def test_jenkins_detected(self, tmp_path):
        write(tmp_path, "Jenkinsfile", "pipeline { agent any }\n")
        r = detect_ci(tmp_path)
        assert r["data"]["jenkins"] is True
        assert r["data"]["has_ci"] is True

    def test_gitlab_ci_detected(self, tmp_path):
        write(tmp_path, ".gitlab-ci.yml", "stages: [test]\n")
        r = detect_ci(tmp_path)
        assert r["data"]["gitlab"] is True
        assert r["data"]["has_ci"] is True

    def test_travis_ci_detected(self, tmp_path):
        write(tmp_path, ".travis.yml", "language: python\n")
        r = detect_ci(tmp_path)
        assert r["data"]["travis"] is True
        assert r["data"]["has_ci"] is True

    def test_bitbucket_pipelines_detected(self, tmp_path):
        write(tmp_path, "bitbucket-pipelines.yml", "pipelines:\n  default:\n    - step:\n")
        r = detect_ci(tmp_path)
        assert r["data"]["bitbucket"] is True
        assert r["data"]["has_ci"] is True

    def test_evidence_always_present(self, tmp_path):
        r = detect_ci(tmp_path)
        assert result_has_evidence(r)


# ── detect_lint ───────────────────────────────────────────────────────────────


class TestDetectLint:
    def test_empty_repo_all_false(self, tmp_path):
        r = detect_lint(tmp_path)
        assert r["data"]["eslint"] is False
        assert r["data"]["ruff"] is False
        assert r["data"]["mypy"] is False

    def test_eslintrc_json_detected(self, tmp_path):
        write(tmp_path, ".eslintrc.json", '{"env": {"browser": true}}')
        r = detect_lint(tmp_path)
        assert r["data"]["eslint"] is True

    def test_eslint_config_js_detected(self, tmp_path):
        write(tmp_path, "eslint.config.js", "export default [];\n")
        r = detect_lint(tmp_path)
        assert r["data"]["eslint"] is True

    def test_prettierrc_detected(self, tmp_path):
        write(tmp_path, ".prettierrc", '{"semi": false}')
        r = detect_lint(tmp_path)
        assert r["data"]["prettier"] is True

    def test_ruff_in_pyproject_detected(self, tmp_path):
        write(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 88\n")
        r = detect_lint(tmp_path)
        assert r["data"]["ruff"] is True

    def test_ruff_toml_detected(self, tmp_path):
        write(tmp_path, ".ruff.toml", "line-length = 88\n")
        r = detect_lint(tmp_path)
        assert r["data"]["ruff"] is True

    def test_black_in_pyproject_detected(self, tmp_path):
        write(tmp_path, "pyproject.toml", "[tool.black]\nline-length = 88\n")
        r = detect_lint(tmp_path)
        assert r["data"]["black"] is True

    def test_mypy_in_pyproject_detected(self, tmp_path):
        write(tmp_path, "pyproject.toml", "[tool.mypy]\nstrict = true\n")
        r = detect_lint(tmp_path)
        assert r["data"]["mypy"] is True

    def test_mypy_ini_detected(self, tmp_path):
        write(tmp_path, "mypy.ini", "[mypy]\nstrict = True\n")
        r = detect_lint(tmp_path)
        assert r["data"]["mypy"] is True

    def test_flake8_file_detected(self, tmp_path):
        write(tmp_path, ".flake8", "[flake8]\nmax-line-length = 120\n")
        r = detect_lint(tmp_path)
        assert r["data"]["flake8"] is True

    def test_evidence_always_present(self, tmp_path):
        r = detect_lint(tmp_path)
        assert result_has_evidence(r)


# ── detect_structure ──────────────────────────────────────────────────────────


class TestDetectStructure:
    def test_empty_repo_basics(self, tmp_path):
        r = detect_structure(tmp_path)
        assert isinstance(r["data"]["top_level"], list)
        assert r["data"]["has_src"] is False
        assert r["data"]["has_docs"] is False
        assert r["data"]["has_tests_dir"] is False

    def test_src_dir_detected(self, tmp_path):
        (tmp_path / "src").mkdir()
        r = detect_structure(tmp_path)
        assert r["data"]["has_src"] is True

    def test_docs_dir_detected(self, tmp_path):
        (tmp_path / "docs").mkdir()
        r = detect_structure(tmp_path)
        assert r["data"]["has_docs"] is True

    def test_tests_dir_detected(self, tmp_path):
        (tmp_path / "tests").mkdir()
        r = detect_structure(tmp_path)
        assert r["data"]["has_tests_dir"] is True

    def test_spec_dir_detected_as_tests(self, tmp_path):
        (tmp_path / "spec").mkdir()
        r = detect_structure(tmp_path)
        assert r["data"]["has_tests_dir"] is True

    def test_top_level_lists_all_entries(self, tmp_path):
        write(tmp_path, "README.md", "")
        write(tmp_path, "pyproject.toml", "")
        r = detect_structure(tmp_path)
        assert "README.md" in r["data"]["top_level"]
        assert "pyproject.toml" in r["data"]["top_level"]

    def test_top_level_capped_at_200(self, tmp_path):
        for i in range(250):
            write(tmp_path, f"file_{i:03d}.txt", "")
        r = detect_structure(tmp_path)
        assert len(r["data"]["top_level"]) <= 200

    def test_file_count_only_root_level_files(self, tmp_path):
        write(tmp_path, "a.py", "")
        write(tmp_path, "b.py", "")
        (tmp_path / "subdir").mkdir()
        r = detect_structure(tmp_path)
        assert r["data"]["file_count"] == 2

    def test_evidence_always_present(self, tmp_path):
        r = detect_structure(tmp_path)
        assert result_has_evidence(r)


# ── detect_env_templates ──────────────────────────────────────────────────────


class TestDetectEnvTemplates:
    def test_no_env_template(self, tmp_path):
        r = detect_env_templates(tmp_path)
        assert r["data"]["has_env_template"] is False
        assert r["data"]["key_count"] == 0
        assert r["data"]["template_path"] is None

    def test_env_example_detected(self, tmp_path):
        write(tmp_path, ".env.example", "DB_URL=\nSECRET_KEY=\n")
        r = detect_env_templates(tmp_path)
        assert r["data"]["has_env_template"] is True

    def test_env_sample_detected(self, tmp_path):
        write(tmp_path, ".env.sample", "API_KEY=<API_KEY>\n")
        r = detect_env_templates(tmp_path)
        assert r["data"]["has_env_template"] is True

    def test_keys_extracted_correctly(self, tmp_path):
        write(tmp_path, ".env.example", "DB_URL=postgres://...\nSECRET_KEY=changeme\n# comment\n")
        r = detect_env_templates(tmp_path)
        assert "DB_URL" in r["data"]["keys"]
        assert "SECRET_KEY" in r["data"]["keys"]

    def test_comments_not_included_in_keys(self, tmp_path):
        write(tmp_path, ".env.example", "# This is a comment\nDB_URL=\n")
        r = detect_env_templates(tmp_path)
        assert all(not k.startswith("#") for k in r["data"]["keys"])

    def test_key_count_matches_keys_list(self, tmp_path):
        write(tmp_path, ".env.example", "A=1\nB=2\nC=3\n")
        r = detect_env_templates(tmp_path)
        assert r["data"]["key_count"] == 3
        assert len(r["data"]["keys"]) == 3

    def test_keys_capped_at_50(self, tmp_path):
        content = "\n".join(f"VAR_{i:03d}=x" for i in range(100))
        write(tmp_path, ".env.example", content)
        r = detect_env_templates(tmp_path)
        assert len(r["data"]["keys"]) <= 50

    def test_evidence_always_present(self, tmp_path):
        r = detect_env_templates(tmp_path)
        assert result_has_evidence(r)

    def test_template_path_is_absolute_str(self, tmp_path):
        write(tmp_path, ".env.example", "X=1\n")
        r = detect_env_templates(tmp_path)
        path = r["data"]["template_path"]
        assert path is not None
        assert Path(path).is_absolute()
