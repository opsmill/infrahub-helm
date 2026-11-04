# Chart e2e tests

End-to-end tests that deploy each chart in `charts/` into a throwaway
[vcluster](https://www.vcluster.com/) and exercise it with `pytest`.

Each chart has its own test module + marker, so CI can run only the job whose
chart changed (see `.github/workflows/ci.yml`):

| Chart                    | Marker          | What it checks |
|--------------------------|-----------------|----------------|
| `infrahub`               | `infrahub`      | Deploys the community chart; a `BuiltinTag` round-trips through the Infrahub SDK. |
| `infrahub-enterprise`    | `enterprise`    | Same SDK check against the enterprise chart. |
| `infrahub-backup`        | `backup`        | Seeds a tag, runs the backup Job to an S3 bucket served by Garage, deletes the tag, runs the restore Job, asserts the tag is back. The Jobs reach Garage over HTTPS with a certificate issued by a private CA that the test generates, and trust it through `extraEnv`, `extraVolumes` and `extraVolumeMounts`. A restore without these values must fail certificate verification. |
| `infrahub-observability` | `observability` | Deploys Infrahub + the stack together (tracing → Tempo, Alloy scraping Infrahub), drives API traffic, then asserts via Grafana that Infrahub metrics (Prometheus) and Infrahub traces (Tempo) are queryable. |
| `infrahub-mcp`           | `mcp`           | Deploys Infrahub with the MCP sub-chart behind a shared ingress and drives it over the streamable-HTTP transport. |

Charts are installed from the local `charts/` directory (cross-chart
dependencies are rewritten to local `file://` paths), so the tests reflect the
working tree rather than the published OCI charts.

## Requirements

- `vcluster`, `helm`, `kubectl`, Docker
- [`uv`](https://docs.astral.sh/uv/) (manages the Python environment)
- `yq` + `jq` (only for the observability test — it syncs Grafana provisioning
  from upstream via `scripts/sync-upstream.sh`)

All images and charts are pulled anonymously from `registry.opsmill.io`, so no
registry credentials are required.

## Running

```bash
uv run pytest -v -m infrahub        tests/e2e   # one chart
uv run pytest -v -m observability   tests/e2e
uv run pytest -v                    tests/e2e   # everything
```

Each run creates and tears down its own vcluster. On failure the suite dumps
pod status and recent container logs for every namespace it deployed into.

Modules marked `manual` are never collected by CI (which selects chart markers)
and are run on demand by path:

```bash
uv run pytest -v -m manual tests/e2e/test_tracing_optout.py                  # tracing env opt-out
uv run pytest -v -m manual tests/e2e/test_infrahub_enterprise_openshift.py   # OpenShift overlay
uv run pytest -v -s -m manual tests/e2e/test_infrahub_upstream_playwright.py # upstream UI suite
uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py                   # git behind a private CA
```

`test_tracing_optout.py` checks that enabling `infrahub-observability` for only
the Prefect exporter injects no `INFRAHUB_TRACE_*` env vars, while the
bundled-Tempo and external-collector paths still do. Only rendered objects are
inspected, so it needs no running pods.

`test_infrahub_upstream_playwright.py` runs [Infrahub's own pytest-playwright
suite](https://github.com/opsmill/infrahub/tree/stable/tests/e2e) against a
Helm-deployed Infrahub Enterprise instead of the testcontainers stack it boots
by default, on the OpenShift overlay's configuration. It clones the upstream
repository into `.cache/upstream-infrahub`, installs its environment and a
Chromium build, and points it at the deployment with `INFRAHUB_ADDRESS`; the
chart's demo-data Job supplies the dataset the suite's own fixtures would
otherwise load. `INFRAHUB_E2E_REF` picks the upstream ref — it defaults to
`infrahub-v<appVersion>`, the release the chart deploys, since the suite tracks
the UI and `stable` runs ahead of the released image between releases.
`INFRAHUB_E2E_SRC` reuses an existing prepared checkout and `INFRAHUB_E2E_TESTS`
narrows the run to a subset. It needs `uv` and enough disk for the checkout and
browser.

`test_git_custom_ca.py` checks that Infrahub imports a git repository served
over HTTPS by a private CA, using the Helm form of the
[Trust a private CA](https://docs.infrahub.app/deploy-manage/install-configure/production-deployment/private-ca)
guide: the bundle mounted through `extraVolumes`/`extraVolumeMounts` and
`INFRAHUB_TLS_CA_BUNDLE`. A second repository behind a CA that is *not* in the
bundle must be rejected. Last, it runs a `helm upgrade` with `upgrade.enabled`,
which only passes when the upgrade job gets the server's `extraVolumes` too
([#97](https://github.com/opsmill/infrahub-helm/pull/97)).

`test_git_custom_ca.py` needs an Infrahub image carrying
[opsmill/infrahub#10487](https://github.com/opsmill/infrahub/pull/10487), which
no released `appVersion` points at. The fixture builds one with
`scripts/build-infrahub-image.sh` and imports it into the vcluster:

```bash
# clones opsmill/infrahub itself
uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py

# reuse a local checkout instead of cloning (the ref only has to be fetched)
INFRAHUB_SOURCE_DIR=~/code/infrahub uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py

# skip the build and use an image that already exists locally
INFRAHUB_CUSTOM_IMAGE=registry.opsmill.io/opsmill/infrahub:pr-10487 \
  uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py
```

The script overlays the ref's `backend/` on a released image rather than
rebuilding from `development/Dockerfile`, so it takes seconds; it refuses to
build when the ref's `uv.lock` differs from the base image's. Run it directly to
build an image for another ref:

```bash
./scripts/build-infrahub-image.sh --help
./scripts/build-infrahub-image.sh --ref my-branch --tag my-tag
```

## Neo4j HA increment

```bash
uv run pytest -v -s -m ha tests/e2e
NEO4J_DOCKER_IMAGE=neo4j:2026.10.1-enterprise uv run pytest -v -s -m ha tests/e2e
```

The `ha` marker creates three Kubernetes nodes (one control plane, two workers)
with vcluster's Docker driver. It installs the local Enterprise chart with two
API servers, two task workers, two Prefect servers, and three separate Neo4j
Enterprise releases spread across distinct nodes. Each database member uses a
2 GiB persistent volume and requests 500m CPU / 2 GiB RAM. Allow additional
capacity for Kubernetes, Infrahub, Prefect and the supporting services; the CI
job uses `huge-runners` and has a 60-minute ceiling. This is a functional smoke
topology with small memory settings, not a performance baseline.

The test checks Neo4j's reported database topology (three online primaries and
one writer), creates a branch through Prefect, and round-trips a tag. It scales
the selected writer to zero, waits for its pod to disappear and for the two
surviving primaries to report a replacement writer, then creates another branch
and writes/reads data while that member remains absent. Three primaries require
a majority of two; the chart setting of three is the initial formation minimum.
After restoring the member it checks cluster recovery and both tags, verifies
that the new pod uses the same PVC UID, and directly reads pre-failure and
outage database markers from that member over Bolt to verify catch-up. This tests member loss and
recovery; it does not simulate an abrupt node crash or a network partition.

The database chart version comes from the staged local `infrahub` dependency,
so a chart upgrade PR tests its own pin. `NEO4J_DOCKER_IMAGE` overrides all three
members through `image.customImage`. `PREFECT_DOCKER_IMAGE` overrides the task
manager's image repository and tag. **It must contain Infrahub's custom Prefect
entrypoint** (for example, an Infrahub Enterprise build with the candidate
Prefect dependency); a stock `prefecthq/prefect` image is not compatible with
this chart. `INFRAHUB_DOCKER_IMAGE` overrides the image of the API servers and
task workers. It must start with the registry host, for example
`registry.opsmill.io/opsmill/infrahub-enterprise:dev-1234567`, because the chart
sets the registry, the repository and the tag apart. To test an Infrahub build,
set `INFRAHUB_DOCKER_IMAGE` and `PREFECT_DOCKER_IMAGE` to the same image. Omit a
variable to test the chart's default. The test logs actual pod images and node
placement.

`.github/workflows/ha-e2e.yml` runs on relevant pull requests and exposes
`neo4j_image`, `prefect_image`, `infrahub_image` and `neo4j_upgrade_from_chart`
for manual or reusable workflow invocation.
An empty input uses chart defaults. For candidate comparisons run the same
chart commit once with defaults and once with the candidate image, keeping
Prefect unchanged. Both runs use fresh stores: they do not validate an upgrade
of a persisted store from 2026.05 (the rolling upgrade mode below does). A
candidate image override does not itself validate a different Neo4j chart
version.

This increment leaves Redis, PostgreSQL and RabbitMQ at the existing smoke-test
settings: it is **Neo4j HA coverage, not full-stack HA validation**. Schema
changes, proposed-change review/merge, generators, backup/restore, rolling
upgrades other than the Neo4j one below and performance regression remain
separate increments for INBOX-407. It must not be used alone to enable automatic
dependency upgrades.

### Rolling Neo4j upgrade

```bash
NEO4J_UPGRADE_FROM_CHART=2026.5.0 uv run pytest -v -s -m ha tests/e2e
```

`test_neo4j_rolling_upgrade` runs only when `NEO4J_UPGRADE_FROM_CHART` is set,
and the workflow input `neo4j_upgrade_from_chart` sets it. The three members are
then installed from that version of the Neo4j chart, pulled from the repository
that `charts/infrahub/Chart.yaml` names, and Infrahub is installed as usual. The
test writes a tag through Infrahub and a marker node over Bolt, then runs
`helm upgrade` of one member release at a time to the pinned chart, with the
same values. Before each step it picks a member that does not host the writer
of the `neo4j` database, so the writer is upgraded last; it picks again before
every step because the writer can move when a member restarts. After each step
it waits until the member's pod is replaced and ready, then checks three online
primaries and one writer, the member's Neo4j version (`dbms.components()` over a
direct Bolt connection), the markers written so far on that member, and that
Infrahub can still create a branch and write and read a tag. At the end every
member must report the new version, serve every marker and keep the PVC (same
UID) it had before the upgrade, and every tag must still be readable. The log
shows both versions, the upgrade order with the writer at each step, and the
images and restart counts of all pods. The test never restarts the Infrahub
pods; the restart counts show whether they restarted on their own.

The test is skipped when both charts run the same Neo4j version. Setup fails when
the pinned chart runs an older Neo4j than the chart named, or when
`NEO4J_DOCKER_IMAGE` is also set, since that image would run before and after the
upgrade. In this mode `test_neo4j_writer_loss_and_recovery` runs after the
upgrade, on the upgraded cluster.

The upgrade runs on a small store, with checks between the steps rather than
traffic during each restart. It does not test a rollback, a Neo4j image that the
chart does not pin, or an upgrade of Infrahub, Prefect or the other services.
