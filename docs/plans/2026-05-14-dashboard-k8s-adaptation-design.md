# Dashboard Kubernetes adaptation — design

**Status:** Approved, ready for implementation
**Date:** 2026-05-14
**Branch:** `feat/infrahub-observability-chart`

## Problem

`infrahub-observability` ships seven Grafana dashboards vendored from
`opsmill/infrahub` (a docker-compose dev stack). Two of them —
`container_resources` and `neo4j_monitoring` — have panels that show no data
in Kubernetes because:

1. **No `container_*` metrics are collected.** Upstream runs a standalone
   cAdvisor container; our chart's Alloy config doesn't scrape the K8s
   equivalent (kubelet `/metrics/cadvisor`). Prometheus has zero
   `container_*` series.
2. **The dashboards filter by Docker-only labels.** Queries use
   `container_label_com_docker_compose_service` and
   `container_label_com_docker_compose_project`, which only exist when
   cAdvisor scrapes a Docker daemon. Even if we collected the metrics, the
   filters would never match.

Both issues need fixing, and the fix must survive future upstream syncs —
the dashboards are re-pulled by `scripts/sync-dashboards.sh` whenever
upstream cuts a new infrahub release.

## Goals

- `container_*` metrics flow into Prometheus.
- Container Resources and Neo4j Monitoring dashboards render real data.
- The fix survives `make sync-dashboards REF=…`.
- CI catches regressions when upstream or our chart drifts.

## Non-goals

- Replacing the upstream dashboards with a different design.
- Wholesale switch to kube-prometheus-stack.
- Per-cluster customisation of the dashboards beyond what upstream allows.

## Design

### 1. Collection: scrape kubelet cAdvisor

Add a `prometheus.scrape "cadvisor"` block to
`charts/infrahub-observability/templates/alloy-config.yaml`. The scrape
target is the API server's node-proxy endpoint
(`/api/v1/nodes/<name>/proxy/metrics/cadvisor`), one per node, discovered
via `discovery.kubernetes` with `role = "node"`. TLS uses the in-cluster
CA; auth uses the Alloy ServiceAccount bearer token.

A new template `templates/alloy-cadvisor-rbac.yaml` provisions a
ClusterRole granting `get` on `nodes/proxy` and a ClusterRoleBinding to
the Alloy SA created by the subchart. The block is gated by a new value
`alloy.cadvisor.enabled` (default `true`) so users without the RBAC
appetite can disable it.

### 2. Adaptation: post-sync transform script

`scripts/transform_dashboard.py` rewrites the dashboards from raw upstream
form to K8s-adapted form. Rules:

```python
REPLACEMENTS = [
    ("container_label_com_docker_compose_service", "container"),
    ("container_label_com_docker_compose_project", "namespace"),
    ('id!=""', 'container!="", image!=""'),
]
```

Dashboard template-variable queries that key off Docker compose are
rewritten to use K8s labels (`namespace`, `container`).

`scripts/sync-dashboards.sh` is extended to call the transform on every
fetched JSON before writing it to
`charts/infrahub-observability/dashboards/`. Upstream is the only source
of truth; we never edit the vendored JSONs by hand. The transform is
idempotent — re-running on already-transformed JSON is a no-op.

### 3. Validation: static query allowlist

`scripts/validate_dashboards.py` parses every dashboard JSON, extracts all
`expr` fields, and verifies:

- Every metric name appears in `scripts/known-metrics.yaml` (curated by
  source: infrahub_app, cadvisor, node_exporter, prometheus_internal,
  loki).
- Every label name in a selector appears in `scripts/known-labels.yaml`
  (either metric-native or relabeled onto the series by Alloy).

Exit non-zero on any violation. Runs in CI right after `helm lint`.
Forces an explicit acknowledgement (allowlist edit) when collection
changes.

Trade-offs accepted:
- Doesn't verify query *semantics* (right grouping, right rate window).
- Allowlist must be kept in sync with the Alloy scrape config — but this
  is the point: a missed metric in the allowlist is a missing scrape.

### 4. Wiring

```
charts/infrahub-observability/templates/
  alloy-config.yaml                 MODIFY  cadvisor scrape + node discovery
  alloy-cadvisor-rbac.yaml          NEW     ClusterRole/Binding for Alloy SA

scripts/
  sync-dashboards.sh                MODIFY  post-fetch transform step
  transform_dashboard.py            NEW     k8s adaptation
  validate_dashboards.py            NEW     static query validation
  known-metrics.yaml                NEW     allowlist by source
  known-labels.yaml                 NEW     allowlist

charts/infrahub-observability/dashboards/
  container_resources.json          REGEN   re-run sync to produce k8s form
  neo4j_monitoring.json             REGEN   same

.github/workflows/ci.yml            MODIFY  add validate_dashboards.py step
docs/local-testing-observability.md MODIFY  note container_* present, mention toggle
```

## Commit sequence

1. `feat(observability): scrape kubelet cAdvisor for container metrics`
   — alloy-config + RBAC. Metrics start flowing; dashboards still
   filter-broken.
2. `feat(observability): add dashboard transform pipeline for k8s
   label adaptation` — transform script + sync integration. No JSON
   regen yet; just the tooling.
3. `chore(observability): re-sync dashboards through k8s transform` —
   regenerates the two affected dashboards. This is where the UI
   becomes correct.
4. `ci: static-validate dashboard queries against known-metrics
   allowlist` — validator + CI step. Allowlist files are committed
   last so they reflect the final state.

Each step independently passes `helm lint`, so bisecting works.

## Risks

- **RBAC expansion.** `nodes/proxy` is cluster-scope `get`. Standard
  monitoring permission (kube-prometheus-stack et al. request the same)
  but worth flagging in the chart's `Service discovery and toggles`
  section.
- **Transform regex fragility.** If upstream switches phrasing
  (`container_label_com_docker_compose_service!=""` →
  `container_label_com_docker_compose_service=~".+"`), the rewrite may
  miss. The validator catches the residual unknown-label in CI rather
  than silently shipping broken dashboards.
- **Allowlist drift.** Adding a new metric source (e.g., kube-state-
  metrics later) requires updating `known-metrics.yaml`. This is
  intentional friction.

## Out-of-scope follow-ups

- kube-state-metrics integration (pod/replicaset metadata).
- Live-cluster integration test in CI (deferred; static validation
  catches the immediate concern).
- Custom dashboards for the chart's own components beyond what upstream
  ships.
