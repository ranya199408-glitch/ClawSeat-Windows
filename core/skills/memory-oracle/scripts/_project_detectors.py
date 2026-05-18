#!/usr/bin/env python3
"""
_project_detectors.py — pure-function project detectors for scan_project.py.

Each detector takes a repo_root Path and returns:
    {
        "data": {...},                          # detector-specific fields
        "evidence": [{"source_url": "...", "trust": "high|medium|low"}, ...]
    }

All detectors are pure functions: static file reads only.
NO subprocess calls (§D20). NO writes to disk.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────


def _file_url(path: Path) -> str:
    return f"file://{path}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _has_toml_section(content: str, section: str) -> bool:
    """Return True if a TOML-like content has a [section] or [section.sub] header."""
    pattern = re.compile(
        r"^\s*\[" + re.escape(section) + r"(?:\]|\.)",
        re.MULTILINE,
    )
    return bool(pattern.search(content))


def _extract_python_version(pyproject_content: str) -> str | None:
    """Extract minimum Python version from requires-python or python_requires."""
    for line in pyproject_content.splitlines():
        stripped = line.strip()
        if "requires-python" in stripped or "python_requires" in stripped:
            m = re.search(r'[">= \']*(\d+\.\d+)', stripped)
            if m:
                return m.group(1)
    return None


def _find_python_source(repo_root: Path) -> Path | None:
    """Return one Python source file without walking bulky dependency output."""
    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".turbo",
        "__pycache__",
    }
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        for filename in files:
            if filename.endswith(".py"):
                return Path(root) / filename
    return None


def _find_python_test_source(repo_root: Path) -> Path | None:
    """Return one Python test file without walking bulky dependency output."""
    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".turbo",
        "__pycache__",
    }
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        for filename in files:
            if filename.endswith(".py") and (filename.startswith("test_") or filename.endswith("_test.py")):
                return Path(root) / filename
    return None


# ── detect_runtime ─────────────────────────────────────────────────────────────


def detect_runtime(repo_root: Path) -> dict:
    """Detect language runtimes and dependency managers."""
    evidence: list[dict] = []
    data: dict = {
        "python": False,
        "python_version": None,
        "node": False,
        "pnpm": False,
        "yarn": False,
        "npm": False,
        "go": False,
        "rust": False,
        "ruby": False,
        "java": False,
        "uv": False,
        "poetry": False,
        "primary_language": None,
    }

    # ── Python ───────────────────────────────────────────────────────────────
    py_indicators = [
        "pyproject.toml", "setup.py", "setup.cfg",
        "requirements.txt", "Pipfile", "poetry.lock", "uv.lock",
    ]
    for name in py_indicators:
        p = repo_root / name
        if p.is_file():
            data["python"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})
    if not data["python"]:
        source_file = _find_python_source(repo_root)
        if source_file is not None:
            data["python"] = True
            evidence.append({"source_url": _file_url(source_file), "trust": "medium"})

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        content = _read_text(pyproject)
        ver = _extract_python_version(content)
        if ver:
            data["python_version"] = ver
        if _has_toml_section(content, "tool.uv") or "[tool.uv]" in content:
            data["uv"] = True
        if _has_toml_section(content, "tool.poetry"):
            data["poetry"] = True

    if (repo_root / "uv.lock").is_file():
        data["uv"] = True
    if (repo_root / "poetry.lock").is_file():
        data["poetry"] = True

    # ── Node ─────────────────────────────────────────────────────────────────
    pkg_json = repo_root / "package.json"
    if pkg_json.is_file():
        data["node"] = True
        evidence.append({"source_url": _file_url(pkg_json), "trust": "high"})
        pkg = _read_json(pkg_json)
        engines = pkg.get("engines", {})
        node_ver = engines.get("node")
        if node_ver:
            data["node_version"] = node_ver

    if (repo_root / "pnpm-lock.yaml").is_file():
        data["pnpm"] = True
        evidence.append({"source_url": _file_url(repo_root / "pnpm-lock.yaml"), "trust": "high"})
    elif (repo_root / "yarn.lock").is_file():
        data["yarn"] = True
        evidence.append({"source_url": _file_url(repo_root / "yarn.lock"), "trust": "high"})
    elif (repo_root / "package-lock.json").is_file():
        data["npm"] = True

    # ── Go ───────────────────────────────────────────────────────────────────
    go_mod = repo_root / "go.mod"
    if go_mod.is_file():
        data["go"] = True
        evidence.append({"source_url": _file_url(go_mod), "trust": "high"})
        content = _read_text(go_mod)
        m = re.search(r"^go\s+(\d+\.\d+)", content, re.MULTILINE)
        if m:
            data["go_version"] = m.group(1)

    # ── Rust ─────────────────────────────────────────────────────────────────
    cargo = repo_root / "Cargo.toml"
    if cargo.is_file():
        data["rust"] = True
        evidence.append({"source_url": _file_url(cargo), "trust": "high"})

    # ── Ruby ─────────────────────────────────────────────────────────────────
    gemfile = repo_root / "Gemfile"
    if gemfile.is_file():
        data["ruby"] = True
        evidence.append({"source_url": _file_url(gemfile), "trust": "high"})

    # ── Java ─────────────────────────────────────────────────────────────────
    pom = repo_root / "pom.xml"
    build_gradle = repo_root / "build.gradle"
    if pom.is_file():
        data["java"] = True
        evidence.append({"source_url": _file_url(pom), "trust": "high"})
    elif build_gradle.is_file():
        data["java"] = True
        evidence.append({"source_url": _file_url(build_gradle), "trust": "high"})

    # ── Primary language ─────────────────────────────────────────────────────
    if data["python"] and not data["node"]:
        data["primary_language"] = "python"
    elif data["node"] and not data["python"]:
        data["primary_language"] = "node"
    elif data["python"] and data["node"]:
        data["primary_language"] = "python"
    elif data["go"]:
        data["primary_language"] = "go"
    elif data["rust"]:
        data["primary_language"] = "rust"
    elif data["ruby"]:
        data["primary_language"] = "ruby"
    elif data["java"]:
        data["primary_language"] = "java"

    if not evidence:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})

    return {"data": data, "evidence": evidence}


# ── detect_tests ──────────────────────────────────────────────────────────────


def detect_tests(repo_root: Path) -> dict:
    """Detect test frameworks in use."""
    evidence: list[dict] = []
    data: dict = {
        "pytest": False,
        "jest": False,
        "vitest": False,
        "playwright": False,
        "rspec": False,
        "mocha": False,
        "cypress": False,
        "go_test": False,
        "cargo_test": False,
        "test_command": None,
    }

    # ── pytest ────────────────────────────────────────────────────────────────
    pytest_indicators = ["pytest.ini", "conftest.py", ".pytest.ini"]
    for name in pytest_indicators:
        p = repo_root / name
        if p.is_file():
            data["pytest"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        content = _read_text(pyproject)
        if _has_toml_section(content, "tool.pytest") or "pytest" in content.lower():
            if "pytest" in content.lower():
                data["pytest"] = True
                if pyproject not in [Path(e["source_url"][7:]) for e in evidence]:
                    evidence.append({"source_url": _file_url(pyproject), "trust": "high"})
    if not data["pytest"]:
        test_source = _find_python_test_source(repo_root)
        if test_source is not None:
            data["pytest"] = True
            evidence.append({"source_url": _file_url(test_source), "trust": "medium"})

    # ── jest ─────────────────────────────────────────────────────────────────
    jest_configs = ["jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs"]
    for name in jest_configs:
        p = repo_root / name
        if p.is_file():
            data["jest"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})
    pkg_json = repo_root / "package.json"
    if pkg_json.is_file():
        pkg = _read_json(pkg_json)
        if "jest" in pkg.get("devDependencies", {}) or "jest" in pkg.get("dependencies", {}):
            data["jest"] = True
            evidence.append({"source_url": _file_url(pkg_json), "trust": "medium"})
        scripts = pkg.get("scripts", {})
        test_script = scripts.get("test", "")
        if "jest" in test_script:
            data["jest"] = True
        if "vitest" in test_script or "vitest" in pkg.get("devDependencies", {}):
            data["vitest"] = True
        if "mocha" in test_script or "mocha" in pkg.get("devDependencies", {}):
            data["mocha"] = True
        if test_script:
            data["test_command"] = test_script

    # ── vitest ────────────────────────────────────────────────────────────────
    vitest_configs = ["vitest.config.js", "vitest.config.ts", "vitest.config.mts"]
    for name in vitest_configs:
        p = repo_root / name
        if p.is_file():
            data["vitest"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})

    # ── playwright ────────────────────────────────────────────────────────────
    playwright_configs = [
        "playwright.config.js", "playwright.config.ts",
        "playwright.config.mjs", "playwright.config.cjs",
    ]
    for name in playwright_configs:
        p = repo_root / name
        if p.is_file():
            data["playwright"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})

    # ── cypress ───────────────────────────────────────────────────────────────
    cypress_configs = ["cypress.config.js", "cypress.config.ts", "cypress.json"]
    for name in cypress_configs:
        p = repo_root / name
        if p.is_file():
            data["cypress"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})

    # ── rspec ─────────────────────────────────────────────────────────────────
    rspec = repo_root / ".rspec"
    if rspec.is_file():
        data["rspec"] = True
        evidence.append({"source_url": _file_url(rspec), "trust": "high"})

    # ── go test ───────────────────────────────────────────────────────────────
    if (repo_root / "go.mod").is_file():
        data["go_test"] = True
        evidence.append({"source_url": _file_url(repo_root / "go.mod"), "trust": "medium"})

    # ── cargo test ────────────────────────────────────────────────────────────
    if (repo_root / "Cargo.toml").is_file():
        data["cargo_test"] = True
        evidence.append({"source_url": _file_url(repo_root / "Cargo.toml"), "trust": "medium"})

    if not evidence:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})

    return {"data": data, "evidence": evidence}


# ── detect_deploy ─────────────────────────────────────────────────────────────


def detect_deploy(repo_root: Path) -> dict:
    """Detect deployment configuration files."""
    evidence: list[dict] = []
    data: dict = {
        "has_dockerfile": False,
        "has_compose": False,
        "has_netlify": False,
        "has_vercel": False,
        "has_heroku": False,
        "has_render": False,
        "platforms": [],
    }
    platforms: list[str] = []

    # ── Dockerfile ────────────────────────────────────────────────────────────
    dockerfile = repo_root / "Dockerfile"
    if dockerfile.is_file():
        data["has_dockerfile"] = True
        platforms.append("docker")
        evidence.append({"source_url": _file_url(dockerfile), "trust": "high"})
    else:
        dockerfiles = list(repo_root.glob("Dockerfile.*"))
        if dockerfiles:
            data["has_dockerfile"] = True
            platforms.append("docker")
            evidence.append({"source_url": _file_url(dockerfiles[0]), "trust": "high"})

    # ── Docker Compose ────────────────────────────────────────────────────────
    compose_names = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    for name in compose_names:
        p = repo_root / name
        if p.is_file():
            data["has_compose"] = True
            if "docker" not in platforms:
                platforms.append("docker")
            evidence.append({"source_url": _file_url(p), "trust": "high"})
            break

    # ── Netlify ───────────────────────────────────────────────────────────────
    netlify = repo_root / "netlify.toml"
    if netlify.is_file():
        data["has_netlify"] = True
        platforms.append("netlify")
        evidence.append({"source_url": _file_url(netlify), "trust": "high"})

    # ── Vercel ────────────────────────────────────────────────────────────────
    vercel = repo_root / "vercel.json"
    if vercel.is_file():
        data["has_vercel"] = True
        platforms.append("vercel")
        evidence.append({"source_url": _file_url(vercel), "trust": "high"})

    # ── Heroku ────────────────────────────────────────────────────────────────
    procfile = repo_root / "Procfile"
    if procfile.is_file():
        data["has_heroku"] = True
        platforms.append("heroku")
        evidence.append({"source_url": _file_url(procfile), "trust": "high"})

    # ── Render ────────────────────────────────────────────────────────────────
    render = repo_root / "render.yaml"
    if render.is_file():
        data["has_render"] = True
        platforms.append("render")
        evidence.append({"source_url": _file_url(render), "trust": "high"})

    data["platforms"] = platforms

    if not evidence:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})

    return {"data": data, "evidence": evidence}


# ── detect_ci ─────────────────────────────────────────────────────────────────


def detect_ci(repo_root: Path) -> dict:
    """Detect CI/CD pipeline configuration."""
    evidence: list[dict] = []
    data: dict = {
        "has_ci": False,
        "github_actions": False,
        "circleci": False,
        "jenkins": False,
        "gitlab": False,
        "travis": False,
        "bitbucket": False,
    }

    # ── GitHub Actions ────────────────────────────────────────────────────────
    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir():
        workflow_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
        if workflow_files:
            data["github_actions"] = True
            data["has_ci"] = True
            evidence.append({"source_url": _file_url(workflow_files[0]), "trust": "high"})

    # ── CircleCI ──────────────────────────────────────────────────────────────
    circleci = repo_root / ".circleci" / "config.yml"
    if circleci.is_file():
        data["circleci"] = True
        data["has_ci"] = True
        evidence.append({"source_url": _file_url(circleci), "trust": "high"})

    # ── Jenkins ───────────────────────────────────────────────────────────────
    jenkinsfile = repo_root / "Jenkinsfile"
    if jenkinsfile.is_file():
        data["jenkins"] = True
        data["has_ci"] = True
        evidence.append({"source_url": _file_url(jenkinsfile), "trust": "high"})

    # ── GitLab CI ─────────────────────────────────────────────────────────────
    gitlab_ci = repo_root / ".gitlab-ci.yml"
    if gitlab_ci.is_file():
        data["gitlab"] = True
        data["has_ci"] = True
        evidence.append({"source_url": _file_url(gitlab_ci), "trust": "high"})

    # ── Travis CI ─────────────────────────────────────────────────────────────
    travis = repo_root / ".travis.yml"
    if travis.is_file():
        data["travis"] = True
        data["has_ci"] = True
        evidence.append({"source_url": _file_url(travis), "trust": "high"})

    # ── Bitbucket Pipelines ───────────────────────────────────────────────────
    bitbucket = repo_root / "bitbucket-pipelines.yml"
    if bitbucket.is_file():
        data["bitbucket"] = True
        data["has_ci"] = True
        evidence.append({"source_url": _file_url(bitbucket), "trust": "high"})

    if not evidence:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})

    return {"data": data, "evidence": evidence}


# ── detect_lint ───────────────────────────────────────────────────────────────


def detect_lint(repo_root: Path) -> dict:
    """Detect lint and format tool configuration."""
    evidence: list[dict] = []
    data: dict = {
        "eslint": False,
        "prettier": False,
        "ruff": False,
        "black": False,
        "mypy": False,
        "flake8": False,
        "pylint": False,
        "isort": False,
    }

    # ── ESLint ────────────────────────────────────────────────────────────────
    eslint_configs = [
        ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
        ".eslintrc.yaml", ".eslintrc.yml",
        "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    ]
    for name in eslint_configs:
        p = repo_root / name
        if p.is_file():
            data["eslint"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})
            break

    # ── Prettier ──────────────────────────────────────────────────────────────
    prettier_configs = [
        ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs",
        ".prettierrc.yaml", ".prettierrc.yml", ".prettierrc.toml",
        "prettier.config.js", "prettier.config.cjs",
    ]
    for name in prettier_configs:
        p = repo_root / name
        if p.is_file():
            data["prettier"] = True
            evidence.append({"source_url": _file_url(p), "trust": "high"})
            break

    # ── Python linters (from pyproject.toml) ─────────────────────────────────
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        content = _read_text(pyproject)
        if _has_toml_section(content, "tool.ruff"):
            data["ruff"] = True
            evidence.append({"source_url": _file_url(pyproject), "trust": "high"})
        if _has_toml_section(content, "tool.black"):
            data["black"] = True
            if pyproject not in [Path(e["source_url"][7:]) for e in evidence]:
                evidence.append({"source_url": _file_url(pyproject), "trust": "high"})
        if _has_toml_section(content, "tool.mypy"):
            data["mypy"] = True
            if pyproject not in [Path(e["source_url"][7:]) for e in evidence]:
                evidence.append({"source_url": _file_url(pyproject), "trust": "high"})
        if _has_toml_section(content, "tool.isort"):
            data["isort"] = True
        if _has_toml_section(content, "tool.pylint"):
            data["pylint"] = True

    # ── Standalone config files ────────────────────────────────────────────────
    if (repo_root / ".ruff.toml").is_file():
        data["ruff"] = True
        evidence.append({"source_url": _file_url(repo_root / ".ruff.toml"), "trust": "high"})
    if (repo_root / "mypy.ini").is_file() or (repo_root / ".mypy.ini").is_file():
        data["mypy"] = True
        ini = repo_root / "mypy.ini" if (repo_root / "mypy.ini").is_file() else repo_root / ".mypy.ini"
        evidence.append({"source_url": _file_url(ini), "trust": "high"})
    if (repo_root / ".flake8").is_file():
        data["flake8"] = True
        evidence.append({"source_url": _file_url(repo_root / ".flake8"), "trust": "high"})

    setup_cfg = repo_root / "setup.cfg"
    if setup_cfg.is_file():
        content = _read_text(setup_cfg)
        if "[flake8]" in content:
            data["flake8"] = True
            evidence.append({"source_url": _file_url(setup_cfg), "trust": "medium"})

    if not evidence:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})

    return {"data": data, "evidence": evidence}


# ── detect_structure ──────────────────────────────────────────────────────────


def detect_structure(repo_root: Path) -> dict:
    """Detect repository top-level structure (≤200 entries)."""
    evidence: list[dict] = []
    data: dict = {
        "has_src": False,
        "has_docs": False,
        "has_tests_dir": False,
        "has_scripts": False,
        "top_level": [],
        "file_count": 0,
    }

    try:
        top_level: list[str] = sorted(p.name for p in repo_root.iterdir())
    except OSError:
        top_level = []
    data["top_level"] = top_level[:200]

    data["has_src"] = any(n in {"src", "lib"} for n in top_level)
    data["has_docs"] = any(n in {"docs", "doc", "documentation"} for n in top_level)
    data["has_tests_dir"] = any(n in {"tests", "test", "spec", "__tests__"} for n in top_level)
    data["has_scripts"] = any(n in {"scripts", "bin", "tools"} for n in top_level)

    # Shallow file count (only root-level files, not recursive to keep it fast)
    try:
        file_count = sum(1 for p in repo_root.iterdir() if p.is_file())
    except OSError:
        file_count = 0
    data["file_count"] = file_count

    evidence.append({"source_url": _file_url(repo_root), "trust": "high"})

    return {"data": data, "evidence": evidence}


# ── detect_env_templates ──────────────────────────────────────────────────────


def detect_env_templates(repo_root: Path) -> dict:
    """Detect .env template files and extract key names."""
    evidence: list[dict] = []
    data: dict = {
        "has_env_template": False,
        "template_path": None,
        "key_count": 0,
        "keys": [],
    }

    template_names = [".env.example", ".env.sample", ".env.template", ".env.dist"]
    found: Path | None = None
    for name in template_names:
        p = repo_root / name
        if p.is_file():
            found = p
            break

    if found is None:
        evidence.append({"source_url": _file_url(repo_root), "trust": "low"})
        return {"data": data, "evidence": evidence}

    data["has_env_template"] = True
    data["template_path"] = str(found)
    evidence.append({"source_url": _file_url(found), "trust": "high"})

    keys: list[str] = []
    for line in _read_text(found).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if key and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                keys.append(key)

    data["keys"] = keys[:50]
    data["key_count"] = len(keys)

    return {"data": data, "evidence": evidence}
