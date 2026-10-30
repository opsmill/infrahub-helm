#!/usr/bin/env python3
"""Compare the settings an infrahub-mcp release reads with the ones the chart sets.

The infrahub-mcp server is configured only through environment variables. This
script collects the variables that a checkout of the opsmill/infrahub-mcp
repository reads, and the variables that charts/infrahub-mcp/templates/deployment.yaml
sets, and reports the difference:

- "missing": the server reads the variable, the chart does not set it. The script
  exits with 1 when any variable is missing.
- "unused": the chart sets the variable, the server no longer reads it. Reported
  only; a value is removed from the chart by a person, not by this check.

The server reads its variables from three places:

- the fields of the ``ServerConfig`` pydantic-settings class, prefixed with its
  ``env_prefix`` (``INFRAHUB_MCP_``),
- ``env_get("...")``, ``os.environ.get("...")`` and ``os.getenv("...")`` calls,
- ``ENV`` lines of the container image Dockerfile (``MCP_HOST``, ``MCP_PORT``).

Usage:
    scripts/check_mcp_settings.py --source <infrahub-mcp checkout> [--markdown]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENT = REPO_ROOT / "charts" / "infrahub-mcp" / "templates" / "deployment.yaml"

# Only variables with these prefixes are server settings. The source also reads
# other names (for example PYTHONUNBUFFERED in the Dockerfile).
PREFIXES = ("INFRAHUB_", "MCP_")

# Variables the chart leaves to `extraEnv` on purpose, with the reason.
IGNORED = {
    "INFRAHUB_MCP_ENV_FILE": "path of a .env file; the pod has no .env file",
}

ENV_READERS = {"env_get", "getenv", "get"}
ENV_LINE = re.compile(r"^\s*ENV\s+([A-Za-z_][A-Za-z0-9_]*)=", re.MULTILINE)
CHART_ENV = re.compile(r"^\s*- name: ([A-Z][A-Z0-9_]*)\s*$", re.MULTILINE)


def _settings_fields(tree: ast.Module) -> set[str]:
    """Return the env var names of the fields of every pydantic-settings class with an env_prefix."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        prefix = None
        fields = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "model_config" for t in stmt.targets
            ):
                if isinstance(stmt.value, ast.Call):
                    for kw in stmt.value.keywords:
                        if kw.arg == "env_prefix" and isinstance(kw.value, ast.Constant):
                            prefix = kw.value.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if stmt.target.id != "model_config":
                    fields.append(stmt.target.id)
        if prefix:
            names.update(f"{prefix}{field}".upper() for field in fields)
    return names


def _env_reads(tree: ast.Module) -> set[str]:
    """Return the names passed as a string literal to env_get(), os.getenv() or os.environ.get()."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in ENV_READERS or not isinstance(node.args[0].value, str):
            continue
        # `.get` counts only on os.environ, not on any dict.
        if name == "get" and not (isinstance(func.value, ast.Attribute) and func.value.attr == "environ"):
            continue
        names.add(node.args[0].value)
    return names


def server_settings(source: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted((source / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        names |= _settings_fields(tree)
        names |= _env_reads(tree)
    for path in sorted(source.rglob("Dockerfile")):
        names.update(ENV_LINE.findall(path.read_text()))
    return {name for name in names if name.startswith(PREFIXES)}


def chart_settings() -> set[str]:
    return set(CHART_ENV.findall(DEPLOYMENT.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="checkout of opsmill/infrahub-mcp")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown report")
    args = parser.parse_args()

    server = server_settings(args.source)
    if not server:
        print(f"No settings found under {args.source}; is it an infrahub-mcp checkout?", file=sys.stderr)
        return 2
    chart = chart_settings()
    missing = sorted(server - chart - IGNORED.keys())
    unused = sorted(chart - server)

    if args.markdown:
        if missing:
            print("The MCP server reads these variables, and `charts/infrahub-mcp` does not set them:\n")
            print("\n".join(f"- `{name}`" for name in missing))
            print(
                "\nAdd a value for each one to `values.yaml` (with a `# --` comment) and to"
                " `templates/deployment.yaml`, or add it to `IGNORED` in"
                " `scripts/check_mcp_settings.py` with the reason."
            )
        else:
            print("`charts/infrahub-mcp` sets every variable that the MCP server reads.")
        if unused:
            print("\nThe chart sets these variables, and the MCP server no longer reads them:\n")
            print("\n".join(f"- `{name}`" for name in unused))
    else:
        for name in missing:
            print(f"missing: {name}")
        for name in unused:
            print(f"unused: {name}")
        if not missing and not unused:
            print("The chart sets every variable that the MCP server reads.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
