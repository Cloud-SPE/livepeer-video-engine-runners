#!/usr/bin/env python3
"""Check repository navigation and current static runtime dependency boundaries."""

import ast
from collections import Counter
from importlib.util import resolve_name
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/index.md",
    "docs/reference/checks.md",
    "docs/validation/index.md",
)
FORBIDDEN = {
    "engines": {"livepeer_gateway", "runner", "client", "controller"},
    "lifecycle": {"livepeer_gateway", "runner", "client", "controller"},
    "controller": {"livepeer_gateway", "runner", "client"},
    "runner": {"controller"},
    "engine_entrypoint": {"livepeer_gateway", "runner", "client", "controller"},
    "stub_engine": {"livepeer_gateway", "runner", "client", "controller"},
}
APPLICATION = {
    "livepeer_gateway",
    "video_runners.runner",
    "video_runners.client",
    "runner",
    "client",
}
PACKAGE_FORBIDDEN = {
    "video_runners.contracts": APPLICATION
    | {
        "video_runners.controller",
        "video_runners.lifecycle",
        "video_runners.backends",
        "controller",
        "lifecycle",
        "engines",
    },
    "video_runners.catalog": APPLICATION
    | {
        "video_runners.controller",
        "video_runners.lifecycle",
        "video_runners.backends",
        "controller",
        "lifecycle",
        "engines",
    },
    "video_runners.origins": APPLICATION
    | {
        "video_runners.controller",
        "video_runners.lifecycle",
        "video_runners.backends",
        "controller",
        "lifecycle",
        "engines",
    },
    "video_runners.backends": APPLICATION
    | {
        "video_runners.controller",
        "video_runners.lifecycle",
        "controller",
        "lifecycle",
        "engines",
    },
    "video_runners.lifecycle": APPLICATION
    | {"video_runners.controller", "controller", "lifecycle", "engines"},
    "video_runners.controller": APPLICATION | {"controller", "lifecycle", "engines"},
    "video_runners.runner": {"video_runners.controller", "controller"},
    "video_runners.stub_engine": APPLICATION
    | {"video_runners.controller", "controller"},
    "video_runners.tools.engine_entrypoint": APPLICATION
    | {"video_runners.controller", "controller"},
    "video_runners.tools.operator_io": APPLICATION
    | {"video_runners.controller", "video_runners.lifecycle", "video_runners.backends"},
    "video_runners.tools.sync_config": APPLICATION
    | {"video_runners.controller", "video_runners.lifecycle", "video_runners.backends"},
    "video_runners.tools.evidence": APPLICATION
    | {"video_runners.controller", "video_runners.lifecycle", "video_runners.backends"},
    "video_runners.diagnostics": APPLICATION
    | {"video_runners.controller", "video_runners.lifecycle", "video_runners.backends"},
}


def prose(text: str) -> str:
    """Exclude fenced examples from link and heading checks."""
    lines = []
    fence = ""
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
        elif not fence:
            lines.append(line)
    return "\n".join(lines)


def anchors(text: str) -> set[str]:
    counts: Counter[str] = Counter()
    result = set()
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose(text), re.MULTILINE):
        slug = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        count = counts[slug]
        result.add(f"{slug}-{count}" if count else slug)
        counts[slug] += 1
    return result


def check_docs(root: Path, files: list[Path]) -> list[str]:
    errors = []
    documents = {p.resolve(): prose(p.read_text()) for p in files if p.suffix == ".md"}
    graph: dict[Path, set[Path]] = {}
    for source, text in documents.items():
        links = re.findall(r"\]\((<[^>\n]+>|[^\s)]+)", text)
        links += re.findall(r"^\s*\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", text, re.MULTILINE)
        graph[source] = set()
        for link in links:
            parsed = urlsplit(link.strip("<>"))
            if parsed.scheme or parsed.netloc:
                continue
            target = (
                (source.parent / unquote(parsed.path)).resolve()
                if parsed.path
                else source
            )
            label = f"{source.relative_to(root)}: {link}"
            if not target.is_relative_to(root) or not target.exists():
                errors.append(
                    f"{label}: missing repository target; fix or remove the link"
                )
                continue
            graph[source].add(target)
            if parsed.fragment and target.suffix == ".md" and target.is_file():
                if unquote(parsed.fragment) not in anchors(target.read_text()):
                    errors.append(
                        f"{label}: missing heading anchor; link to an existing heading"
                    )
    pending = [(root / "docs/index.md").resolve()]
    reached: set[Path] = set()
    while pending:
        path = pending.pop()
        if path not in reached:
            reached.add(path)
            pending.extend(graph.get(path, set()) - reached)
    for path in sorted(documents):
        if path.is_relative_to(root / "docs") and path not in reached:
            errors.append(
                f"{path.relative_to(root)}: unindexed document; link it from docs/index.md or an indexed doc"
            )
    return errors


def check_imports(root: Path) -> list[str]:
    modules = {path.stem: path for path in root.glob("*.py")}
    for path in (root / "src").rglob("*.py"):
        parts = list(path.relative_to(root / "src").with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    graph = {}
    for module, path in modules.items():
        imports = set()
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                imports.update(name.name for name in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if node.level:
                    package = (
                        module
                        if path.name == "__init__.py"
                        else module.rpartition(".")[0]
                    )
                    target = resolve_name("." * node.level + target, package)
                imports.add(target)
                imports.update(
                    f"{target}.{name.name}"
                    for name in node.names
                    if f"{target}.{name.name}" in modules
                )
        # Importing a submodule also executes each package initializer.
        for target in list(imports):
            parts = target.split(".")
            imports.update(
                ".".join(parts[:i])
                for i in range(1, len(parts))
                if ".".join(parts[:i]) in modules
            )
        graph[module] = imports
    errors = []
    rules = dict(FORBIDDEN)
    for module in modules:
        for prefix, forbidden in PACKAGE_FORBIDDEN.items():
            if module == prefix or module.startswith(prefix + "."):
                rules[module] = forbidden
        if module.startswith("video_runners."):
            rules[module] = rules.get(module, set()) | {
                "runner",
                "controller",
                "engines",
                "lifecycle",
                "client",
                "stub_engine",
                "engine_entrypoint",
            }
    for source, forbidden in rules.items():
        pending = [(source,)]
        visited = set()
        while pending:
            chain = pending.pop()
            module = chain[-1]
            if module in visited:
                continue
            visited.add(module)
            if any(
                module == target or module.startswith(target + ".")
                for target in forbidden
            ):
                errors.append(
                    f"{' -> '.join(chain)}: prohibited dependency; keep Livepeer in runner/client and Docker implementation out of runner"
                )
            else:
                pending.extend(
                    chain + (name,) for name in sorted(graph.get(module, set()))
                )
    return errors


def main() -> None:
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        text=True,
    ).split("\0")
    files = [ROOT / name for name in names if name and (ROOT / name).is_file()]
    errors = [
        f"{name}: required repository entry point is missing"
        for name in REQUIRED
        if not (ROOT / name).is_file()
    ]
    errors += check_docs(ROOT, files)
    errors += check_imports(ROOT)
    if errors:
        raise SystemExit(
            "Repository checks failed:\n" + "\n".join(f"- {error}" for error in errors)
        )
    print(
        "Repository navigation, local links/anchors and static import boundaries passed"
    )


if __name__ == "__main__":
    main()
