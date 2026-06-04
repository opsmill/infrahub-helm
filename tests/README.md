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
