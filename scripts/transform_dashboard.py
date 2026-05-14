#!/usr/bin/env python3
"""Rewrite a vendored Grafana dashboard JSON from docker-compose form to K8s form.

The upstream `opsmill/infrahub` repository ships dashboards designed for its
docker-compose dev stack. Two patterns don't carry over to Kubernetes:

1. Container-resource panels filter on `container_label_com_docker_compose_*`
   labels, which only exist when cAdvisor scrapes Docker. In Kubernetes,
   cAdvisor (via kubelet) emits the same `container_*` metrics but labels
   them with K8s-native labels (`container`, `namespace`, `pod`, `node`).

2. The label *values* differ because Bitnami / community subcharts pick
   container names independent of the docker-compose service names. The
   Neo4j chart's container is called `neo4j`, not `database`; the redis
   chart's container is `redis`, not `cache`; and so on.

This script rewrites both the label names and the docker-compose-specific
filter values to their K8s equivalents. It runs on stdin → stdout (or in
place with --in-place) and is idempotent: re-running on an already
transformed file is a no-op because the new patterns no longer match the
old ones.

The transform is intentionally conservative — it only touches PromQL
`expr` fields and template-variable queries. Panel titles, descriptions,
and unrelated text are left alone.

Usage:
    python3 scripts/transform_dashboard.py < raw.json > k8s.json
    python3 scripts/transform_dashboard.py --in-place path/to/dashboard.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Label-name rewrites: tokens that appear bare in PromQL.
LABEL_REWRITES: list[tuple[str, str]] = [
    ("container_label_com_docker_compose_service", "container"),
    ("container_label_com_docker_compose_project", "namespace"),
]

# Filter-value rewrites: values that may appear inside a `container=~"..."`
# selector (or as exact-match equality). Docker-compose service name on the
# left, Kubernetes container name on the right.
#
# These are applied only AFTER label-name rewrites, and only inside string
# tokens that look like label-value selectors, so we don't accidentally
# rewrite panel titles or unrelated text.
VALUE_REWRITES: dict[str, str] = {
    "database": "neo4j",
    "cache": "redis",
    "message-queue": "rabbitmq",
    "task-manager-db": "postgresql",
    # infrahub-server / infrahub-task-worker / prefect-server are identical
    # in Docker and K8s, so they don't need an entry.
}

# The cAdvisor `id` label was used in docker-compose dashboards to filter
# out the cgroup root. In K8s cAdvisor, the equivalent guard is to require
# both `container` and `image` labels (which excludes pod-level and pause
# containers).
ID_FILTER_REWRITES: list[tuple[str, str]] = [
    ('id!=""', 'container!="", image!=""'),
    # Same pattern with single quotes (less common):
    ("id!=''", 'container!="", image!=""'),
]


def _rewrite_label_names(text: str) -> str:
    """Replace docker-compose label tokens with their K8s equivalents.

    Uses a word-boundary regex so partial matches in unrelated text are safe.
    """
    for src, dst in LABEL_REWRITES:
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return text


def _rewrite_id_filters(text: str) -> str:
    for src, dst in ID_FILTER_REWRITES:
        text = text.replace(src, dst)
    return text


# Matches a `container` (or post-rewrite equivalent) selector value, e.g.
#   container="database"
#   container=~"database|infrahub-server"
#   container!~"foo"
# Group 1: the value inside the quotes.
_SELECTOR_RE = re.compile(r'(?P<lhs>\bcontainer\s*[!=]~?\s*)"(?P<val>[^"]*)"')


def _rewrite_selector_values(text: str) -> str:
    """Apply VALUE_REWRITES inside container=...".." selectors.

    Only rewrites exact-match values and clean regex-alternation branches:

      container="database"                  → container="neo4j"
      container=~"database|infrahub-server" → container=~"neo4j|infrahub-server"

    Does NOT rewrite values nested inside larger regex patterns like
    `.*(database|cache|queue).*` — those are fuzzy matches whose K8s
    equivalents depend on which substrings each K8s container name
    contains, and a literal substitution would produce wrong results
    (e.g., `cache-master` would incorrectly get rewritten).

    Dashboards using such fuzzy patterns (currently only LogQL queries in
    infrahub_monitoring.json) will work only partially in K8s — the branches
    that happen to match a K8s container name as a substring keep working;
    the others don't. The static dashboard validator catches this as
    unknown-label-value warnings.
    """

    def replace(match: re.Match[str]) -> str:
        lhs = match.group("lhs")
        val = match.group("val")
        # Skip values that contain regex metacharacters beyond a simple
        # alternation — we can't reliably rewrite fuzzy patterns like
        # ".*(database|cache).*" because doing so would also touch
        # substrings that should remain (e.g., `cache-master`).
        if re.search(r"[.*?+\[\](){}^$\\]", val):
            return match.group(0)
        branches = val.split("|")
        rewritten = [VALUE_REWRITES.get(b, b) for b in branches]
        return f'{lhs}"{"|".join(rewritten)}"'

    return _SELECTOR_RE.sub(replace, text)


def transform_expr(expr: str) -> str:
    """Apply the full PromQL transform pipeline to a single expression."""
    expr = _rewrite_id_filters(expr)
    expr = _rewrite_label_names(expr)
    expr = _rewrite_selector_values(expr)
    return expr


def _is_promql_string(s: str) -> bool:
    """Heuristic: does this string look like a PromQL/LogQL expression?

    Avoids touching panel titles and prose. Triggers on any of:
    - presence of `{` (label selectors)
    - PromQL aggregation keywords (rate, sum, avg, count, by)
    - LogQL stream selectors (component=...)
    - References to known metric prefixes (container_, node_, infrahub_, etc.)
    """
    return bool(
        re.search(
            r"\{|"
            r"\b(rate|sum|avg|count|max|min|histogram_quantile|by|without)\s*\(|"
            r"\b(container|node|infrahub|loki|prefect|rabbitmq|prometheus)_",
            s,
        )
    )


def _walk(node: Any) -> Any:
    """Recursively transform expr fields and PromQL-shaped template queries.

    Also rewrites Grafana legend templates (`legendFormat`) which reference
    label names via `{{label_name}}` interpolation — when we rename the
    label in the query, we have to rename it in the legend too or the
    legend renders empty.
    """
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "expr" and isinstance(val, str):
                node[key] = transform_expr(val)
            elif key == "legendFormat" and isinstance(val, str):
                # Legend uses {{label}} syntax; reuse the label-name rewrite.
                node[key] = _rewrite_label_names(val)
            elif key == "query" and isinstance(val, str) and _is_promql_string(val):
                node[key] = transform_expr(val)
            elif key == "query" and isinstance(val, dict) and isinstance(
                val.get("query"), str
            ) and _is_promql_string(val["query"]):
                val["query"] = transform_expr(val["query"])
            else:
                _walk(val)
    elif isinstance(node, list):
        for item in node:
            _walk(item)
    return node


def transform_dashboard(raw: str) -> str:
    """Transform a dashboard JSON document. Idempotent.

    Returns the input unchanged (byte-for-byte) when the transform makes no
    structural changes. This is important because Grafana exports use a
    non-standard indentation (4 spaces at depth 1, +2 per level after) that
    no standard JSON serializer produces. Reformatting every dashboard on
    every sync would mask real changes in PR diffs with noise.
    """
    data = json.loads(raw)
    original = json.dumps(data, sort_keys=True)
    _walk(data)
    transformed = json.dumps(data, sort_keys=True)
    if original == transformed:
        return raw
    return json.dumps(data, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--in-place",
        metavar="FILE",
        type=Path,
        help="rewrite FILE in place; otherwise reads stdin and writes stdout",
    )
    args = parser.parse_args()

    if args.in_place:
        raw = args.in_place.read_text()
        transformed = transform_dashboard(raw)
        # Preserve the input's trailing-newline disposition. POSIX prefers
        # a trailing newline, but upstream is inconsistent across files
        # and matching the input keeps diffs minimal.
        if raw.endswith("\n") and not transformed.endswith("\n"):
            transformed += "\n"
        args.in_place.write_text(transformed)
        return 0

    raw = sys.stdin.read()
    sys.stdout.write(transform_dashboard(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
