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
Enterprise release publishes the `infrahub-enterprise` chart from `stable`. Before an Infrahub
release, its release process sets `appVersion`, the chart `version`, the Prefect server image tag
(`prefectTag`) and the `infrahub` dependency of the `infrahub-enterprise` chart here on its own.

## Upgrading a dependency that Infrahub ships

An upgrade of Neo4j or Prefect in `opsmill/infrahub` also needs a pull request here. The
[Infrahub guide](https://github.com/opsmill/infrahub/blob/stable/dev/guides/backend/upgrading-infrastructure-dependencies.md)
covers the whole upgrade.

- Neo4j: change the `neo4j` dependency version in `charts/infrahub/Chart.yaml`. Compare the Neo4j
  settings with the release notes too: the `neo4j` section of `charts/infrahub/values.yaml` and of
  the size presets.
- Prefect: compare the Prefect settings with the release notes, and change the ones the new
  version affects:
  - The task worker environment and the `prefect-server` section of `charts/infrahub/values.yaml`.
  - Every values file of `charts/infrahub-enterprise/`. The size presets run the Prefect web
    server and the Prefect background services as separate deployments.
  - The `prefect-server` dependency version in `charts/infrahub/Chart.yaml`, if the new Prefect
    version needs a newer chart.

  When nothing has to change, say so in the Infrahub pull request instead of opening one here.
- Redis, RabbitMQ, PostgreSQL, NATS: not decided, ask a maintainer. The chart installs them from
  other Helm charts, and its Redis and RabbitMQ versions differ from the Docker Compose versions of
  Infrahub.

When a dependency version changes, update the dependency table in the `README.md` of the chart.
Add a changelog fragment in `charts/<name>/changelog/` for each chart that changes. Leave `version`
and `appVersion` to the release process, which changes them just before the merge.

Open the pull request as a draft and name in its description the Infrahub release it ships in.
Merge it while that release is cut, before the release is published, and only if the Infrahub
pull request is part of that release. Merged earlier, it ships with an Infrahub release that was
not tested with it. Merged later, the charts of that release do not contain it. If the Infrahub
pull request moves to a later release, change the release named in the description. The
`/cut-release` command of `opsmill/infrahub` has this step.

## Testing in the high-availability setup

The high-availability setup runs several replicas, a Neo4j cluster and the separate Prefect web
server and background services of the size presets. To test a change there:

- Install the local `infrahub-enterprise` chart with the size preset to test, for example
  `-f charts/infrahub-enterprise/values.small.yaml`. The published `-small`, `-medium` and `-large`
  charts are the base values merged with these files.
- Point the `infrahub` dependency of `infrahub-enterprise` at the local `charts/infrahub`, the way
  `tests/e2e/conftest.py` does. Otherwise the chart installs the published `infrahub` chart.
- For a Prefect upgrade, set `infrahubTag` and `prefectTag` to an Infrahub Enterprise image built
  from the upgrade branch. Otherwise every pod, the Prefect server included, runs the released
  Prefect version.
