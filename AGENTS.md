# Infrahub Helm charts

Helm charts that deploy Infrahub on Kubernetes. Each chart lives in `charts/<name>/`:

- `infrahub`: the community chart. It installs Neo4j, Redis, RabbitMQ, NATS and the Prefect server
  from dependency charts listed in `charts/infrahub/Chart.yaml`.
- `infrahub-enterprise`: wraps the `infrahub` chart and adds the size presets
  (`values.small.yaml`, `values.medium*.yaml`, `values.large*.yaml`) and the OpenShift values.
- `infrahub-backup`, `infrahub-observability`, `infrahub-mcp`: optional charts that the `infrahub`
  chart can include.

`stable` is the only main branch: open every pull request against it.

## Tests

CI runs `helm lint` and the end-to-end tests in `tests/e2e/` for each chart that a pull request
changes. The end-to-end tests install the charts from `charts/` into a throwaway vcluster; see
`tests/README.md` to run them locally. No CI job deploys the high-availability setup, see
[Testing in the high-availability setup](#testing-in-the-high-availability-setup).

## Infrahub releases publish these charts

Every final Infrahub release publishes the `infrahub` chart from `stable`, and every final Infrahub
Enterprise release publishes the `infrahub-enterprise` chart from `stable`, so a change merged here
ships with the next of these releases. Before an Infrahub release, its release process sets
`appVersion`, the chart `version`, the Prefect server image tag (`prefectTag`) and the `infrahub`
dependency of the `infrahub-enterprise` chart here on its own.

## Changing a dependency chart

When the version of a dependency chart changes, update the dependency table in the `README.md` of
the chart, and add a changelog fragment in `charts/<name>/changelog/` for each chart that changes.

## Testing in the high-availability setup

The high-availability setup runs several replicas, a Neo4j cluster and the separate Prefect web
server and background services of the size presets. To test a change there:

- Install the local `infrahub-enterprise` chart with the size preset to test, for example
  `-f charts/infrahub-enterprise/values.small.yaml`. The published `-small`, `-medium` and `-large`
  charts are the base values merged with these files.
- Point the `infrahub` dependency of `infrahub-enterprise` at the local `charts/infrahub`, the way
  `tests/e2e/conftest.py` does. Otherwise the chart installs the published `infrahub` chart.
- To test an Infrahub version that is not released, set `infrahubTag` and `prefectTag` to an
  Infrahub Enterprise image built from its branch. Otherwise every pod, the Prefect server
  included, runs the released version.
