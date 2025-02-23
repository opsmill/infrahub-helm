# infrahub

A Helm chart to deploy Infrahub on Kubernetes

## Infrahub Configuration

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
| https://helm.neo4j.com/neo4j/ | neo4j | 5.20.0 |
| https://nats-io.github.io/k8s/helm/charts/ | nats | 1.1.12 |
| https://prefecthq.github.io/prefect-helm | prefect-server | 2024.10.15184517 |
| oci://registry-1.docker.io/bitnamicharts | common | 2.23.0 |
| oci://registry-1.docker.io/bitnamicharts | rabbitmq | 14.4.1 |
| oci://registry-1.docker.io/bitnamicharts | redis | 19.5.2 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| global.commonAnnotations | object | `{}` | Annotations to use for all installed Kubernetes resources |
| global.commonLabels | object | `{}` | Labels to use for all installed Kubernetes resources |
| global.imagePullPolicy | string | `"IfNotPresent"` | Default image pull policy |
| global.infrahubRepository | string | `"opsmill/infrahub"` | Repository for Infrahub images |
| global.kubernetesClusterDomain | string | `"cluster.local"` | Kubernetes cluster domain |
| global.podLabels | object | `{}` | Labels to use for all configured pods |
| infrahubDemoData.backoffLimit | int | `4` | Backoff limit for the Kubernetes job that will load the data |
| infrahubDemoData.command | list | `["sh","-c","infrahubctl schema load models/base --wait 30 && infrahubctl run models/infrastructure_edge.py && infrahubctl menu load models/base_menu.yml && infrahubctl repository add demo-edge https://github.com/opsmill/infrahub-demo-edge --read-only"]` | Container entrypoint for the demo data loading job |
| infrahubDemoData.enabled | bool | `false` | Whether to enable loading of demo data |
| infrahubDemoData.env.INFRAHUB_API_TOKEN | string | `"06438eb2-8019-4776-878c-0941b1f1d1ec"` | Infrahub API token that will be used when loading the data |
| infrahubDemoData.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the Kubernetes job |
| infrahubServer.infrahubServer.args | list | `["gunicorn","--config","/source/backend/infrahub/serve/gunicorn_config.py","-w","2","--logger-class","infrahub.serve.log.GunicornLogger","infrahub.server:app"]` | Container arguments for the API server |
| infrahubServer.infrahubServer.env | object | `{"INFRAHUB_ALLOW_ANONYMOUS_ACCESS":"true","INFRAHUB_CACHE_PORT":6379,"INFRAHUB_DB_TYPE":"neo4j","INFRAHUB_GIT_REPOSITORIES_DIRECTORY":"/opt/infrahub/git","INFRAHUB_INITIAL_ADMIN_TOKEN":"06438eb2-8019-4776-878c-0941b1f1d1ec","INFRAHUB_LOG_LEVEL":"INFO","INFRAHUB_PRODUCTION":"false","INFRAHUB_SECURITY_SECRET_KEY":"327f747f-efac-42be-9e73-999f08f86b92","INFRAHUB_WORKFLOW_ADDRESS":"prefect-server","INFRAHUB_WORKFLOW_PORT":4200,"PREFECT_API_URL":"http://prefect-server:4200/api"}` | Container environment for the API server |
| infrahubServer.infrahubServer.imagePullPolicy | string | `"Always"` | Image pull policy for the API server |
| infrahubServer.infrahubServer.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the API server |
| infrahubServer.ingress.annotations | string | `nil` | Annotations to configure on the ingress |
| infrahubServer.ingress.enabled | bool | `true` | Whether to enable Ingress for the Infrahub API server |
| infrahubServer.ingress.hostname | string | `"infrahub-cluster.local"` | Hostname to configure for the ingress |
| infrahubServer.persistence.accessMode | string | `"ReadWriteOnce"` |  |
| infrahubServer.persistence.enabled | bool | `true` | Whether to enable data persistence for the Infrahub API server |
| infrahubServer.persistence.size | string | `"1Gi"` |  |
| infrahubServer.ports[0].name | string | `"interface"` |  |
| infrahubServer.ports[0].port | int | `8000` | Port on which to expose the API server service |
| infrahubServer.ports[0].targetPort | int | `8000` | Port on which Infrahub API server listens |
| infrahubServer.resources | object | `{}` | Resources request and limit to apply for the task worker |
| infrahubServer.type | string | `"ClusterIP"` | Service type for the Infrahub API server |
| infrahubTaskWorker.infrahubTaskWorker.args | list | `["prefect","worker","start","--type","infrahubasync","--pool","infrahub-worker","--with-healthcheck"]` | Container arguments for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.env | object | `{"INFRAHUB_API_TOKEN":"06438eb2-8019-4776-878c-0941b1f1d1ec","INFRAHUB_CACHE_PORT":6379,"INFRAHUB_DB_TYPE":"neo4j","INFRAHUB_GIT_REPOSITORIES_DIRECTORY":"/opt/infrahub/git","INFRAHUB_LOG_LEVEL":"DEBUG","INFRAHUB_PRODUCTION":"false","INFRAHUB_TIMEOUT":"60","INFRAHUB_WORKFLOW_ADDRESS":"prefect-server","INFRAHUB_WORKFLOW_PORT":4200,"PREFECT_AGENT_QUERY_INTERVAL":3,"PREFECT_API_URL":"http://prefect-server:4200/api","PREFECT_WORKER_QUERY_SECONDS":3}` | Container environment for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.imagePullPolicy | string | `"Always"` | Image pull policy for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the task worker |
| infrahubTaskWorker.replicas | int | `2` | Number of replicas of the Infrahub Task Worker |
| infrahubTaskWorker.resources | object | `{}` | Resources request and limit to apply for the task worker |
| nats.config.jetstream.enabled | bool | `true` |  |
| nats.enabled | bool | `false` |  |
| neo4j.config."dbms.security.auth_minimum_password_length" | string | `"4"` |  |
| neo4j.config."dbms.security.procedures.unrestricted" | string | `"apoc.*"` |  |
| neo4j.enabled | bool | `true` |  |
| neo4j.logInitialPassword | bool | `false` |  |
| neo4j.nameOverride | string | `"database"` |  |
| neo4j.neo4j.acceptLicenseAgreement | string | `"no"` |  |
| neo4j.neo4j.edition | string | `"community"` |  |
| neo4j.neo4j.minimumClusterSize | int | `1` |  |
| neo4j.neo4j.name | string | `"infrahub"` |  |
| neo4j.neo4j.password | string | `"admin"` |  |
| neo4j.neo4j.resources | object | `{}` |  |
| neo4j.services.admin.enabled | bool | `false` |  |
| neo4j.services.neo4j.enabled | bool | `false` |  |
| neo4j.services.neo4j.ports.bolt.enabled | bool | `true` |  |
| neo4j.services.neo4j.ports.bolt.port | int | `7687` |  |
| neo4j.services.neo4j.ports.bolt.targetPort | int | `7687` |  |
| neo4j.volumes.data.mode | string | `"volume"` |  |
| neo4j.volumes.data.volume.emptyDir | object | `{}` |  |
| prefect-server.enabled | bool | `true` |  |
| prefect-server.postgresql.enabled | bool | `true` |  |
| prefect-server.postgresql.image.tag | string | `"14.13.0"` |  |
| prefect-server.postgresql.primary.persistence.enabled | bool | `false` |  |
| prefect-server.server.env[0].name | string | `"PREFECT_UI_SERVE_BASE"` |  |
| prefect-server.server.env[0].value | string | `"/"` |  |
| prefect-server.server.image.prefectTag | string | `"3.0.11-python3.12-kubernetes"` |  |
| prefect-server.serviceAccount.create | bool | `false` |  |
| rabbitmq.auth.password | string | `"infrahub"` |  |
| rabbitmq.auth.username | string | `"infrahub"` |  |
| rabbitmq.enabled | bool | `true` |  |
| rabbitmq.metrics.enabled | bool | `true` |  |
| rabbitmq.nameOverride | string | `"message-queue"` |  |
| rabbitmq.persistence.enabled | bool | `false` |  |
| rabbitmq.startupProbe.enabled | bool | `true` |  |
| redis.architecture | string | `"standalone"` |  |
| redis.auth.enabled | bool | `false` |  |
| redis.enabled | bool | `true` |  |
| redis.master.persistence.enabled | bool | `false` |  |
| redis.master.service.ports.redis | int | `6379` |  |
| redis.nameOverride | string | `"cache"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.

