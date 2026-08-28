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

Modules marked `manual` are never collected by CI (which selects chart markers)
and are run on demand by path:

```bash
uv run pytest -v -m manual tests/e2e/test_tracing_optout.py                  # tracing env opt-out
uv run pytest -v -m manual tests/e2e/test_infrahub_enterprise_openshift.py   # OpenShift overlay
uv run pytest -v -s -m manual tests/e2e/test_infrahub_upstream_playwright.py # upstream UI suite
```

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
