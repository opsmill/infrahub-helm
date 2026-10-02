# Chart e2e tests

End-to-end tests that deploy each chart in `charts/` into a throwaway
[vcluster](https://www.vcluster.com/) and exercise it with `pytest`.

Each chart has its own test module + marker, so CI can run only the job whose
chart changed (see `.github/workflows/ci.yml`):

| Chart                    | Marker          | What it checks |
|--------------------------|-----------------|----------------|
| `infrahub`               | `infrahub`      | Deploys the community chart; a `BuiltinTag` round-trips through the Infrahub SDK. |
| `infrahub-enterprise`    | `enterprise`    | Same SDK check against the enterprise chart. |
| `infrahub-backup`        | `backup`        | Seeds a tag, runs the backup Job to MinIO, deletes the tag, runs the restore Job, asserts the tag is back. |
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
