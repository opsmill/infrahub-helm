# infrahub-enterprise

A Helm chart to deploy Infrahub Enterprise on Kubernetes

## Infrahub Configuration

This chart is based off the community Infrahub chart which is used as a dependency.
All chart configuration from the Infrahub chart is available through the `infrahub` top-level key.

The Infrahub configuration is structured as follows:

- The `internal_address` is dynamically set based on the release name, namespace, and cluster domain.
- Database, broker, cache, and other service addresses are set dynamically, referring to the relevant services within the Kubernetes cluster.
- Ports for services like the database and cache are pulled from the `values.yaml` file, ensuring flexibility and ease of configuration changes.

Using environment variables is also possible and recommended to set or override existing configuration values.

It is possible to use Kubernetes secrets to configure credentials required by Infrahub such as the database credentials.
The `envFromExistingSecret` parameter is available to pass environment variables from Kubernetes secrets.

## Prerequisites

- Kubernetes 1.12+
- Helm 3.0+
- PV provisioner support in the underlying infrastructure (if persistence is required)

## Installing the Chart

To install the chart with the release name `infrahub`:

```sh
helm install infrahub path/to/infrahub/chart
```

## Upgrading the Chart

To upgrade the chart to a new version:

```sh
helm upgrade infrahub path/to/infrahub/chart
```

## Uninstalling the Chart

To uninstall/delete the `infrahub` deployment:

```sh
helm delete infrahub
```

## Persistence

The chart offers the ability to configure persistence for the database and other components. Check the `persistence` section of each component in `values.yaml` for more details.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://registry.opsmill.io/opsmill/chart | infrahub | 4.1.7 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| infrahub.global.imagePullPolicy | string | `"IfNotPresent"` |  |
| infrahub.global.infrahubRepository | string | `"opsmill/infrahub-enterprise"` |  |
| infrahub.global.kubernetesClusterDomain | string | `"cluster.local"` |  |
| infrahub.infrahubDemoData.command[0] | string | `"sh"` |  |
| infrahub.infrahubDemoData.command[1] | string | `"-c"` |  |
| infrahub.infrahubDemoData.command[2] | string | `"infrahubctl schema load community/models/base --wait 30 && infrahubctl run community/models/infrastructure_edge.py && infrahubctl menu load community/models/base_menu.yml && infrahubctl repository add demo-edge https://github.com/opsmill/infrahub-demo-edge --read-only"` |  |
| infrahub.infrahubServer.infrahubServer.args[0] | string | `"gunicorn"` |  |
| infrahub.infrahubServer.infrahubServer.args[1] | string | `"--config"` |  |
| infrahub.infrahubServer.infrahubServer.args[2] | string | `"/source/community/backend/infrahub/serve/gunicorn_config.py"` |  |
| infrahub.infrahubServer.infrahubServer.args[3] | string | `"-w"` |  |
| infrahub.infrahubServer.infrahubServer.args[4] | string | `"2"` |  |
| infrahub.infrahubServer.infrahubServer.args[5] | string | `"--logger-class"` |  |
| infrahub.infrahubServer.infrahubServer.args[6] | string | `"infrahub.serve.log.GunicornLogger"` |  |
| infrahub.infrahubServer.infrahubServer.args[7] | string | `"infrahub_enterprise.server:app"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_ALLOW_ANONYMOUS_ACCESS | string | `"true"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_CACHE_PORT | int | `6379` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_DB_TYPE | string | `"neo4j"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_GIT_REPOSITORIES_DIRECTORY | string | `"/opt/infrahub/git"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_INITIAL_ADMIN_TOKEN | string | `"06438eb2-8019-4776-878c-0941b1f1d1ec"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_LOG_LEVEL | string | `"INFO"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_PRODUCTION | string | `"false"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_SECURITY_SECRET_KEY | string | `"327f747f-efac-42be-9e73-999f08f86b92"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_WORKFLOW_ADDRESS | string | `"prefect-server"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_WORKFLOW_DEFAULT_WORKER_TYPE | string | `"infrahubentasync"` |  |
| infrahub.infrahubServer.infrahubServer.env.INFRAHUB_WORKFLOW_PORT | int | `4200` |  |
| infrahub.infrahubServer.infrahubServer.env.PREFECT_API_URL | string | `"http://prefect-server:4200/api"` |  |
| infrahub.infrahubServer.infrahubServer.securityContext.allowPrivilegeEscalation | bool | `false` |  |
| infrahub.infrahubServer.podSecurityContext.fsGroup | int | `1000` |  |
| infrahub.infrahubServer.podSecurityContext.runAsGroup | int | `1000` |  |
| infrahub.infrahubServer.podSecurityContext.runAsNonRoot | bool | `true` |  |
| infrahub.infrahubServer.podSecurityContext.runAsUser | int | `1000` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[0] | string | `"prefect"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[1] | string | `"worker"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[2] | string | `"start"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[3] | string | `"--type"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[4] | string | `"infrahubentasync"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[5] | string | `"--pool"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[6] | string | `"infrahub-worker"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.args[7] | string | `"--with-healthcheck"` |  |
| infrahub.infrahubTaskWorker.infrahubTaskWorker.securityContext.allowPrivilegeEscalation | bool | `false` |  |
| infrahub.infrahubTaskWorker.podSecurityContext.fsGroup | int | `1000` |  |
| infrahub.infrahubTaskWorker.podSecurityContext.runAsGroup | int | `1000` |  |
| infrahub.infrahubTaskWorker.podSecurityContext.runAsNonRoot | bool | `true` |  |
| infrahub.infrahubTaskWorker.podSecurityContext.runAsUser | int | `1000` |  |
| infrahub.neo4j.neo4j.acceptLicenseAgreement | string | `"yes"` |  |
| infrahub.neo4j.neo4j.edition | string | `"enterprise"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.

