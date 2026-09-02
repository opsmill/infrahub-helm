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

## Manual tests

Modules marked `manual` are never collected by CI, which only ever selects the
per-chart markers. Run them on demand:

```bash
uv run pytest -v -m manual tests/e2e/test_tracing_optout.py
uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py
```

| Module | What it checks |
|--------|----------------|
| `test_tracing_optout.py` | Enabling `infrahub-observability` for only the Prefect exporter injects no `INFRAHUB_TRACE_*` env vars, while the bundled-Tempo and external-collector paths still do. Only rendered objects are inspected, so it needs no running pods. |
| `test_git_custom_ca.py` | Infrahub imports a git repository served over HTTPS by a private CA, using the Helm form of the [Trust a private CA](https://docs.infrahub.app/deploy-manage/install-configure/production-deployment/private-ca) guide: the bundle mounted through `extraVolumes`/`extraVolumeMounts` and `INFRAHUB_TLS_CA_BUNDLE`. A second repository behind a CA that is *not* in the bundle must be rejected. |

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
