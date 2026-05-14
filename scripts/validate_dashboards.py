#!/usr/bin/env python3
"""Validate vendored Grafana dashboards against our chart's metric inventory.

Two checks, both run against every dashboard JSON under
charts/infrahub-observability/dashboards/:

1. HARD FAIL — denied tokens. Any occurrence of a token listed under
   `denied_tokens` in scripts/known-metrics.yaml inside a query expr means
   either the transform pipeline failed or upstream introduced a new
   docker-compose-specific pattern we don't yet handle. Exits non-zero.

2. SOFT WARN — unknown metrics. Every metric name referenced is matched
   against the `collected_prefixes` glob list. Names that match none of
   them are surfaced as warnings (informational; doesn't fail CI). These
   are usually one of: a typo, a metric we should consider scraping, or
   a third-party prefix we haven't added to the allowlist yet.

Designed to run fast (<1 s on the full dashboard set) without a cluster.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ImportError:
    print(
        "error: pyyaml is required. Install with `pip install pyyaml`.",
        file=sys.stderr,
    )
    sys.exit(2)


# Keywords that look like metric names in PromQL but aren't. Filtered out
# before checking against the allowlist so we don't have to list every
# function in the inventory.
PROMQL_KEYWORDS = frozenset(
    {
        "abs", "absent", "absent_over_time", "and", "atan", "atan2",
        "avg", "avg_over_time", "bool", "bottomk", "by", "ceil",
        "changes", "clamp", "clamp_max", "clamp_min", "cos", "cosh",
        "count", "count_over_time", "count_values", "day_of_month",
        "day_of_week", "day_of_year", "days_in_month", "delta", "deriv",
        "exp", "floor", "group", "group_left", "group_right",
        "histogram_avg", "histogram_count", "histogram_fraction",
        "histogram_quantile", "histogram_stddev", "histogram_stdvar",
        "histogram_sum", "holt_winters", "hour", "idelta", "if",
        "ignoring", "increase", "irate", "label_format", "label_join",
        "label_replace", "last_over_time", "ln", "log10", "log2", "max",
        "max_over_time", "min", "min_over_time", "minute", "month",
        "offset", "on", "or", "predict_linear", "present_over_time",
        "quantile", "quantile_over_time", "rate", "resets", "round",
        "scalar", "sgn", "sin", "sinh", "sort", "sort_desc", "sqrt",
        "stddev", "stddev_over_time", "stdvar", "stdvar_over_time",
        "sum", "sum_over_time", "tan", "tanh", "time", "timestamp",
        "topk", "unless", "vector", "without", "year",
        # LogQL specifics
        "line_format", "json", "logfmt", "regexp", "pattern", "unwrap",
        "rate_counter", "bytes_rate", "bytes_over_time", "first_over_time",
        "last_over_time", "label_format",
        # Grafana template-variable functions
        "label_values", "query_result",
        # Selector operator words that may slip through the regex
        "level", "instance", "job",
    }
)

# Identifier-like tokens that are PromQL/LogQL operators or punctuation
# residue, not metric names. The regex below is permissive so we filter
# manually here as well.
NON_METRIC_TOKENS = frozenset(
    {"i", "le", "id", "kube", "ingester", "deployment", "infrahub",
     "cache", "container", "component", "namespace", "pod", "image",
     "level", "method", "path", "branch", "env", "app_name",
     "flow_name", "kv_name", "lock", "is_schedule_active", "group_left",
     "ignoring"}
)


def _extract_metrics_and_labels(expr: str) -> tuple[set[str], set[str]]:
    """Return (metric_names, label_names) referenced in a PromQL/LogQL expr.

    Tight heuristic: a metric name appears immediately before `{` (selector),
    `[` (range), or as a bareword at expression top-level (`up`, `time()`).
    Labels appear as `<name>=` / `<name>!=` / `<name>=~` / `<name>!~` inside
    `{...}` selectors. This intentionally misses metrics inside complex
    nested PromQL like `histogram_quantile(0.95, foo_bucket{})` where the
    parser would need to look further than `foo_bucket{`, but in practice
    every metric name appears with `{` or `[` adjacent at least once in
    each dashboard, so we don't miss true positives at the dashboard level.
    """
    metrics: set[str] = set()
    labels: set[str] = set()

    # Metric names: identifier immediately followed by `{`, `[`, or end of
    # token in a metric-only context (we accept anything followed by `{`/`[`).
    for match in re.finditer(
        r"\b([a-zA-Z_][a-zA-Z0-9_:]*)\s*[{\[]", expr
    ):
        name = match.group(1)
        if name.startswith("__"):  # Prometheus internals like __name__
            continue
        if len(name) <= 1:  # single-char variable like LogQL's `t`
            continue
        if name in PROMQL_KEYWORDS or name in NON_METRIC_TOKENS:
            continue
        metrics.add(name)

    # Labels: identifier followed by =/!=/=~/!~ inside {...}.
    for sel_match in re.finditer(r"\{([^}]*)\}", expr):
        for label_match in re.finditer(
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*[!=]~?\s*\"", sel_match.group(1)
        ):
            labels.add(label_match.group(1))

    return metrics, labels


def _walk_exprs(node: object) -> Iterable[str]:
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "expr" and isinstance(val, str):
                yield val
            yield from _walk_exprs(val)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_exprs(item)


def _metric_is_collected(name: str, prefixes: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in prefixes)


def validate(
    dashboard_dir: Path, inventory_file: Path
) -> tuple[int, int]:
    """Validate every dashboard. Returns (hard_failures, soft_warnings)."""
    inventory = yaml.safe_load(inventory_file.read_text())
    collected_prefixes = list(inventory.get("collected_prefixes", []))
    denied_tokens = list(inventory.get("denied_tokens", []))

    dashboards = sorted(dashboard_dir.glob("*.json"))
    if not dashboards:
        print(f"error: no dashboards found in {dashboard_dir}", file=sys.stderr)
        return 1, 0

    hard = 0
    soft = 0

    for path in dashboards:
        data = json.loads(path.read_text())
        exprs = list(_walk_exprs(data))

        all_metrics: set[str] = set()
        all_labels: set[str] = set()
        for expr in exprs:
            # Hard-fail: denied tokens
            for tok in denied_tokens:
                if tok in expr:
                    hard += 1
                    print(
                        f"FAIL {path.name}: denied token `{tok}` "
                        f"found in expr: {expr[:120]}",
                        file=sys.stderr,
                    )
                    break
            m, l = _extract_metrics_and_labels(expr)
            all_metrics |= m
            all_labels |= l

        unknown = sorted(
            m
            for m in all_metrics
            if not _metric_is_collected(m, collected_prefixes)
        )
        if unknown:
            soft += len(unknown)
            print(
                f"WARN {path.name}: {len(unknown)} metric name(s) not "
                f"matched by any collected_prefix: {', '.join(unknown[:10])}"
                + (f" (+ {len(unknown) - 10} more)" if len(unknown) > 10 else "")
            )

        print(
            f"  {path.name}: {len(exprs)} exprs, "
            f"{len(all_metrics)} metrics, {len(all_labels)} labels"
        )

    print(
        f"\nSummary: {hard} hard failure(s), {soft} soft warning(s) "
        f"across {len(dashboards)} dashboard(s)"
    )
    return hard, soft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--dashboards",
        type=Path,
        default=Path("charts/infrahub-observability/dashboards"),
        help="dashboard directory (default: charts/infrahub-observability/dashboards)",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("scripts/known-metrics.yaml"),
        help="metric inventory YAML (default: scripts/known-metrics.yaml)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat soft warnings as failures too",
    )
    args = parser.parse_args()

    hard, soft = validate(args.dashboards, args.inventory)
    if hard > 0:
        return 1
    if args.strict and soft > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
