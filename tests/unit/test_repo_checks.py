"""Repository checks reject navigational drift and runtime authority leaks."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location(
        "repo_checks", ROOT / "scripts/check-repo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_navigation_supports_nested_docs_references_and_duplicate_headings(
    tmp_path, checker
):
    files = [
        write(
            tmp_path, "docs/index.md", "[Guide][guide]\n\n[guide]: guide.md#repeat-1\n"
        ),
        write(
            tmp_path,
            "docs/guide.md",
            "# Repeat\n# Repeat\n[Details](nested/details.md#details)\n"
            "```md\n[Example](not-a-real-file.md)\n```\n",
        ),
        write(tmp_path, "docs/nested/details.md", "# Details\n"),
    ]
    assert checker.check_docs(tmp_path, files) == []


@pytest.mark.parametrize(
    "link,problem",
    [
        ("missing.md", "missing repository target"),
        ("guide.md#old", "missing heading anchor"),
    ],
)
def test_navigation_reports_broken_targets_with_a_remedy(
    tmp_path, checker, link, problem
):
    files = [
        write(tmp_path, "docs/index.md", f"[Guide]({link})\n"),
        write(tmp_path, "docs/guide.md", "# Current\n"),
    ]
    errors = checker.check_docs(tmp_path, files)
    assert any(problem in error and "docs/index.md" in error for error in errors)


def test_unindexed_doc_is_reported_even_when_all_its_links_are_valid(tmp_path, checker):
    files = [
        write(tmp_path, "docs/index.md", "# Index\n"),
        write(tmp_path, "docs/orphan.md", "[Index](index.md)\n"),
    ]
    assert any(
        "docs/orphan.md: unindexed" in error
        for error in checker.check_docs(tmp_path, files)
    )


def test_transitive_import_cannot_hide_livepeer_or_controller_authority(
    tmp_path, checker
):
    write(tmp_path, "engines.py", "import helper\n")
    write(tmp_path, "helper.py", "from livepeer_gateway import live_runner\n")
    write(tmp_path, "runner.py", "import bridge\n")
    write(tmp_path, "bridge.py", "import controller\n")
    write(tmp_path, "controller.py", "import aiohttp\n")
    errors = checker.check_imports(tmp_path)
    assert any("engines -> helper -> livepeer_gateway" in error for error in errors)
    assert any("runner -> bridge -> controller" in error for error in errors)


@pytest.mark.parametrize("tool", ["operator_io", "sync_config", "evidence"])
def test_configuration_helpers_do_not_gain_application_authority(
    tmp_path, checker, tool
):
    write(
        tmp_path,
        f"src/video_runners/tools/{tool}.py",
        "from livepeer_gateway import live_runner\n",
    )
    errors = checker.check_imports(tmp_path)
    assert any(
        f"video_runners.tools.{tool} -> livepeer_gateway" in error for error in errors
    )


def test_application_and_operator_tools_can_use_their_required_integrations(
    tmp_path, checker
):
    write(tmp_path, "engines.py", "import aiohttp\n")
    write(tmp_path, "lifecycle.py", "from engines import EngineError\n")
    write(tmp_path, "controller.py", "from lifecycle import engine_url\n")
    write(tmp_path, "runner.py", "import lifecycle\nimport livepeer_gateway\n")
    write(tmp_path, "client.py", "import livepeer_gateway\n")
    write(
        tmp_path, "scripts/recovery.py", "import controller\nimport livepeer_gateway\n"
    )
    assert checker.check_imports(tmp_path) == []


def test_package_relative_imports_cannot_hide_controller_access(tmp_path, checker):
    write(tmp_path, "src/video_runners/__init__.py", "")
    write(tmp_path, "src/video_runners/runner/__init__.py", "")
    write(tmp_path, "src/video_runners/runner/http.py", "from . import bridge\n")
    write(tmp_path, "src/video_runners/runner/bridge.py", "from .. import controller\n")
    write(tmp_path, "src/video_runners/controller/__init__.py", "")
    errors = checker.check_imports(tmp_path)
    assert any(
        "video_runners.runner.http -> video_runners.runner.bridge -> video_runners.controller"
        in error
        for error in errors
    )


def test_package_initializers_are_part_of_dependency_checks(tmp_path, checker):
    write(tmp_path, "src/video_runners/__init__.py", "")
    write(
        tmp_path, "src/video_runners/backends/__init__.py", "import livepeer_gateway\n"
    )
    write(tmp_path, "src/video_runners/backends/openai.py", "")
    write(
        tmp_path,
        "src/video_runners/lifecycle/external.py",
        "import video_runners.backends.openai\n",
    )
    errors = checker.check_imports(tmp_path)
    assert any(
        "video_runners.lifecycle.external" in error and "livepeer_gateway" in error
        for error in errors
    )
