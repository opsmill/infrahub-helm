# infrahub

A Helm chart to deploy Infrahub on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

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
| https://helm.neo4j.com/neo4j/ | neo4j | 2025.10.1-4 |
| https://nats-io.github.io/k8s/helm/charts/ | nats | 1.1.12 |
| https://prefecthq.github.io/prefect-helm | prefect-server | 2025.12.24192415 |
| oci://registry-1.docker.io/bitnamicharts | common | 2.23.0 |
| oci://registry-1.docker.io/bitnamicharts | rabbitmq | 14.4.1 |
| oci://registry-1.docker.io/bitnamicharts | redis | 19.5.2 |
| oci://registry.opsmill.io/opsmill/chart | infrahub-backup | 1.2.0 |
| oci://registry.opsmill.io/opsmill/chart | infrahub-mcp | 0.1.0 |
| oci://registry.opsmill.io/opsmill/chart | infrahub-observability | 0.1.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| emma.affinity | object | `{}` | Affinity for the emma pods |
| emma.enabled | bool | `false` | Whether to enable Emma |
| emma.env.STREAMLIT_SERVER_BASE_URL_PATH | string | `"/emma"` |  |
| emma.imageName | string | `"opsmill/emma"` |  |
| emma.imageRegistry | string | `"registry.opsmill.io"` |  |
| emma.nodeSelector | object | `{}` | Node selector for the emma pods |
| emma.podSecurityContext | object | `{}` | Pod security context for the emma pods |
| emma.ports[0].name | string | `"interface"` |  |
| emma.ports[0].port | int | `8501` |  |
| emma.ports[0].targetPort | int | `8501` |  |
| emma.priorityClassName | string | `""` | Priority class name for the emma pods |
| emma.resources | object | `{}` | Resources request and limit to apply for emma |
| emma.revisionHistoryLimit | int | `10` | Revision history limit for the emma Deployment |
| emma.securityContext | object | `{}` | Container security context for the emma container |
| emma.tolerations | list | `[]` | Tolerations for the emma pods |
| emma.topologySpreadConstraints | list | `[]` | Topology spread constraints for the emma pods |
| emma.type | string | `"ClusterIP"` |  |
| emma.version | string | `"latest"` |  |
| global.commonAnnotations | object | `{}` | Annotations to use for all installed Kubernetes resources |
| global.commonLabels | object | `{}` | Labels to use for all installed Kubernetes resources |
| global.imagePullPolicy | string | `"IfNotPresent"` | Default image pull policy |
| global.imagePullSecrets | list | `[]` | Image pull secrets |
| global.infrahubRepository | string | `"opsmill/infrahub"` | Repository for Infrahub images |
| global.kubernetesClusterDomain | string | `"cluster.local"` | Kubernetes cluster domain |
| global.podLabels | object | `{}` | Labels to use for all configured pods |
| global.tracing | object | `{"enabled":false,"endpoint":"","insecure":true,"protocol":"grpc"}` | Send traces to an OTLP collector. When enabled, INFRAHUB_TRACE_* env vars are injected into the server and task-worker Deployments. Implied true when `infrahub-observability.enabled` is true. Pair with the infrahub-observability chart (Tempo endpoint: <release>-tempo:4317) or any other OTLP-compatible collector. |
| global.tracing.enabled | bool | `false` | Enable tracing instrumentation on server and task-worker pods. Implied true when `infrahub-observability.enabled` is true. |
| global.tracing.endpoint | string | `""` | OTLP endpoint. For grpc protocol, use host:port (no scheme). For http/protobuf, use a full URL. Example: "obs-tempo:4317". When empty and `infrahub-observability.enabled` is true, defaults to "<release>-tempo:4317". |
| global.tracing.insecure | bool | `true` | Skip TLS verification when talking to the collector. |
| global.tracing.protocol | string | `"grpc"` | OTLP protocol. One of: grpc, http/protobuf. |
| infrahub-backup.backup | object | `{"enabled":false,"mode":"cronjob","schedule":"0 2 * * *","storage":{"s3":{"bucket":"","endpoint":"","prefix":"","region":"us-east-1","secretName":""},"type":"s3"}}` | Backup configuration |
| infrahub-backup.enabled | bool | `false` | Whether to enable Infrahub Backup |
| infrahub-backup.restore | object | `{"enabled":false,"s3":{"bucket":"","endpoint":"","key":"","region":"us-east-1","secretName":""}}` | Restore configuration |
| infrahub-mcp.enabled | bool | `false` | Whether to enable Infrahub MCP Server |
| infrahub-mcp.infrahub | object | `{"address":"","apiToken":{"value":""}}` | Infrahub connection for the MCP server. Set `address` to the in-cluster Infrahub URL (e.g. "http://<release>-infrahub-server:8000") and provide an API token via `apiToken.value` or `apiToken.existingSecret`. |
| infrahub-mcp.mcp | object | `{"authMode":"none","logLevel":"info","readOnly":false}` | MCP server settings |
| infrahub-observability.enabled | bool | `false` | Deploy the infrahub-observability subchart and force tracing on. |
| infrahubDemoData.affinity | object | `{}` | Affinity for the demo data job pod |
| infrahubDemoData.backoffLimit | int | `4` | Backoff limit for the Kubernetes job that will load the data |
| infrahubDemoData.command | list | `["sh","-c","infrahubctl schema load models/base --wait 30 && infrahubctl run models/infrastructure_edge.py && infrahubctl menu load models/base_menu.yml && infrahubctl repository add demo-edge https://github.com/opsmill/infrahub-demo-edge --read-only"]` | Container entrypoint for the demo data loading job |
| infrahubDemoData.enabled | bool | `false` | Whether to enable loading of demo data |
| infrahubDemoData.env.INFRAHUB_API_TOKEN | string | `"06438eb2-8019-4776-878c-0941b1f1d1ec"` | Infrahub API token that will be used when loading the data |
| infrahubDemoData.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the Kubernetes job |
| infrahubDemoData.nodeSelector | object | `{}` | Node selector for the demo data job pod |
| infrahubDemoData.podSecurityContext | object | `{}` | Pod security context for the demo data job pod |
| infrahubDemoData.priorityClassName | string | `""` | Priority class name for the demo data job pod |
| infrahubDemoData.resources | object | `{}` | Resources request and limit to apply for the demo data job |
| infrahubDemoData.securityContext | object | `{}` | Container security context for the demo data job container |
| infrahubDemoData.tolerations | list | `[]` | Tolerations for the demo data job pod |
| infrahubServer.affinity | object | `{}` | Affinity for the server pods |
| infrahubServer.gatewayApi | object | `{"enabled":false,"gateway":{"annotations":{},"className":"","enabled":false,"labels":{},"listeners":[],"name":""},"httpRoute":{"annotations":{},"extraRules":[],"hostnames":[],"labels":{},"name":"","parentRefs":[],"path":"/"}}` | Gateway API configuration for the Infrahub API server ref: https://gateway-api.sigs.k8s.io/ Mutually exclusive with infrahubServer.ingress |
| infrahubServer.gatewayApi.enabled | bool | `false` | Whether to enable Gateway API HTTPRoute for the Infrahub API server |
| infrahubServer.gatewayApi.gateway.annotations | object | `{}` | Additional annotations for the Gateway resource |
| infrahubServer.gatewayApi.gateway.className | string | `""` | GatewayClass name (required when gateway.enabled is true) |
| infrahubServer.gatewayApi.gateway.enabled | bool | `false` | Whether to create a Gateway resource (most users will reference an existing Gateway via httpRoute.parentRefs) |
| infrahubServer.gatewayApi.gateway.labels | object | `{}` | Additional labels for the Gateway resource |
| infrahubServer.gatewayApi.gateway.listeners | list | `[]` | Gateway listeners configuration |
| infrahubServer.gatewayApi.gateway.name | string | `""` | Gateway resource name (defaults to "<fullname>-gateway") |
| infrahubServer.gatewayApi.httpRoute.annotations | object | `{}` | Additional annotations for the HTTPRoute resource |
| infrahubServer.gatewayApi.httpRoute.extraRules | list | `[]` | Additional HTTPRoute rules beyond the auto-generated ones |
| infrahubServer.gatewayApi.httpRoute.hostnames | list | `[]` | Hostnames that this HTTPRoute should match |
| infrahubServer.gatewayApi.httpRoute.labels | object | `{}` | Additional labels for the HTTPRoute resource |
| infrahubServer.gatewayApi.httpRoute.name | string | `""` | HTTPRoute resource name (defaults to "<fullname>-httproute") |
| infrahubServer.gatewayApi.httpRoute.parentRefs | list | `[]` | Parent Gateway references |
| infrahubServer.gatewayApi.httpRoute.path | string | `"/"` | Path prefix for the default matching rule |
| infrahubServer.infrahubServer.args | list | `["gunicorn","--config","/source/backend/infrahub/serve/gunicorn_config.py","-w","2","--logger-class","infrahub.serve.log.GunicornLogger","infrahub.server:app"]` | Container arguments for the API server |
| infrahubServer.infrahubServer.env | object | `{"INFRAHUB_ALLOW_ANONYMOUS_ACCESS":"true","INFRAHUB_CACHE_PORT":6379,"INFRAHUB_DB_TYPE":"neo4j","INFRAHUB_GIT_REPOSITORIES_DIRECTORY":"/opt/infrahub/git","INFRAHUB_INITIAL_ADMIN_TOKEN":"06438eb2-8019-4776-878c-0941b1f1d1ec","INFRAHUB_INITIAL_AGENT_TOKEN":"44af444d-3b26-410d-9546-b758657e026c","INFRAHUB_LOG_LEVEL":"INFO","INFRAHUB_PRODUCTION":"false","INFRAHUB_SECURITY_SECRET_KEY":"327f747f-efac-42be-9e73-999f08f86b92","INFRAHUB_WORKFLOW_ADDRESS":"prefect-server","INFRAHUB_WORKFLOW_PORT":4200,"PREFECT_API_URL":"http://prefect-server:4200/api"}` | Container environment for the API server |
| infrahubServer.infrahubServer.envFromExistingSecret | DEPRECATED | `""` | Name of an existing secret to use for environment variables. Use envFromExistingSecrets instead. @deprecated Use envFromExistingSecrets instead |
| infrahubServer.infrahubServer.envFromExistingSecrets | list | `[]` | List of existing secrets to use for environment variables |
| infrahubServer.infrahubServer.extraVolumeMounts | list | `[]` | Extra volumeMounts for the server pod |
| infrahubServer.infrahubServer.extraVolumes | list | `[]` | Extra volumes for the server pod |
| infrahubServer.infrahubServer.imagePullPolicy | string | `"Always"` | Image pull policy for the API server |
| infrahubServer.infrahubServer.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the API server |
| infrahubServer.infrahubServer.livenessProbe | object | `{"failureThreshold":20,"httpGet":{"path":"/api/config","port":8000,"scheme":"HTTP"},"initialDelaySeconds":10,"periodSeconds":5,"timeoutSeconds":5}` | Liveness probe to use for the API server |
| infrahubServer.infrahubServer.readinessProbe | object | `{"failureThreshold":20,"httpGet":{"path":"/api/config","port":8000,"scheme":"HTTP"},"initialDelaySeconds":10,"periodSeconds":5,"timeoutSeconds":5}` | Readiness probe to use for the API server |
| infrahubServer.ingress.annotations | string | `nil` | Annotations to configure on the ingress |
| infrahubServer.ingress.enabled | bool | `true` | Whether to enable Ingress for the Infrahub API server |
| infrahubServer.ingress.hostname | string | `"infrahub-cluster.local"` | Hostname to configure for the ingress |
| infrahubServer.nodeSelector | object | `{}` | Node selector for the server pods |
| infrahubServer.persistence.accessMode | string | `"ReadWriteOnce"` |  |
| infrahubServer.persistence.enabled | bool | `true` | Whether to enable data persistence for the Infrahub API server |
| infrahubServer.persistence.size | string | `"1Gi"` |  |
| infrahubServer.podLabels | object | `{"infrahub/service":"server"}` | Pod labels for the server pods |
| infrahubServer.podSecurityContext | object | `{}` | Pod security context for the server pods |
| infrahubServer.ports | list | `[]` | @deprecated Use `infrahubServer.service.ports` instead. This field will be removed in a future release. |
| infrahubServer.priorityClassName | string | `""` | Priority class name for the server pods |
| infrahubServer.replicas | int | `1` | Number of replicas of the Infrahub API server |
| infrahubServer.resources | object | `{}` | Resources request and limit to apply for the Infrahub API server |
| infrahubServer.revisionHistoryLimit | int | `10` | Revision history limit for the server Deployment |
| infrahubServer.service.ports[0].name | string | `"interface"` |  |
| infrahubServer.service.ports[0].port | int | `8000` | Port on which to expose the API server service |
| infrahubServer.service.ports[0].targetPort | int | `8000` | Port on which Infrahub API server listens |
| infrahubServer.service.type | string | `"ClusterIP"` | Service type for the Infrahub API server |
| infrahubServer.tolerations | list | `[]` | Tolerations for the server pods |
| infrahubServer.topologySpreadConstraints | list | `[]` | Topology spread constraints for the server pods |
| infrahubServer.type | string | `""` | @deprecated Use `infrahubServer.service.type` instead. This field will be removed in a future release. |
| infrahubTaskWorker.affinity | object | `{}` | Affinity for the task worker pods |
| infrahubTaskWorker.infrahubTaskWorker.args | list | `["prefect","worker","start","--type","infrahubasync","--pool","infrahub-worker","--with-healthcheck"]` | Container arguments for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.env | object | `{"INFRAHUB_API_TOKEN":"06438eb2-8019-4776-878c-0941b1f1d1ec","INFRAHUB_CACHE_PORT":6379,"INFRAHUB_DB_TYPE":"neo4j","INFRAHUB_GIT_REPOSITORIES_DIRECTORY":"/opt/infrahub/git","INFRAHUB_INITIAL_AGENT_TOKEN":"44af444d-3b26-410d-9546-b758657e026c","INFRAHUB_LOG_LEVEL":"DEBUG","INFRAHUB_PRODUCTION":"false","INFRAHUB_TIMEOUT":"60","INFRAHUB_WORKFLOW_ADDRESS":"prefect-server","INFRAHUB_WORKFLOW_PORT":4200,"PREFECT_AGENT_QUERY_INTERVAL":3,"PREFECT_API_URL":"http://prefect-server:4200/api","PREFECT_WORKER_QUERY_SECONDS":3}` | Container environment for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.envFromExistingSecret | DEPRECATED | `""` | Name of an existing secret to use for environment variables. Use envFromExistingSecrets instead. @deprecated Use envFromExistingSecrets instead |
| infrahubTaskWorker.infrahubTaskWorker.envFromExistingSecrets | list | `[]` | List of existing secrets to use for environment variables |
| infrahubTaskWorker.infrahubTaskWorker.extraVolumeMounts | list | `[]` | Extra volumeMounts for the task worker pod |
| infrahubTaskWorker.infrahubTaskWorker.extraVolumes | list | `[]` | Extra volumes for the task worker pod |
| infrahubTaskWorker.infrahubTaskWorker.imagePullPolicy | string | `"Always"` | Image pull policy for the task worker |
| infrahubTaskWorker.infrahubTaskWorker.imageRegistry | string | `"registry.opsmill.io"` | Image registry to use for the task worker |
| infrahubTaskWorker.nodeSelector | object | `{}` | Node selector for the task worker pods |
| infrahubTaskWorker.podLabels | object | `{"infrahub/service":"task-worker"}` | Pod labels for the task worker pods |
| infrahubTaskWorker.podSecurityContext | object | `{}` | Pod security context for the task worker pods |
| infrahubTaskWorker.priorityClassName | string | `""` | Priority class name for the task worker pods |
| infrahubTaskWorker.replicas | int | `2` | Number of replicas of the Infrahub Task Worker |
| infrahubTaskWorker.resources | object | `{}` | Resources request and limit to apply for the task worker |
| infrahubTaskWorker.revisionHistoryLimit | int | `10` | Revision history limit for the task worker Deployment |
| infrahubTaskWorker.tolerations | list | `[]` | Tolerations for the task worker pods |
| infrahubTaskWorker.topologySpreadConstraints | list | `[]` | Topology spread constraints for the task worker pods |
| nats.config.jetstream.enabled | bool | `true` |  |
| nats.enabled | bool | `false` |  |
| neo4j.config."dbms.security.auth_minimum_password_length" | string | `"4"` |  |
| neo4j.config."dbms.security.procedures.unrestricted" | string | `"apoc.*"` |  |
| neo4j.enabled | bool | `true` |  |
| neo4j.logInitialPassword | bool | `false` |  |
| neo4j.nameOverride | string | `"database"` |  |
| neo4j.neo4j.acceptLicenseAgreement | string | `"no"` |  |
| neo4j.neo4j.edition | string | `"community"` |  |
| neo4j.neo4j.labels.infrahub/service | string | `"database"` |  |
| neo4j.neo4j.minimumClusterSize | int | `1` |  |
| neo4j.neo4j.name | string | `"infrahub"` |  |
| neo4j.neo4j.password | string | `"admin"` |  |
| neo4j.neo4j.resources.limits.cpu | string | `"4"` |  |
| neo4j.neo4j.resources.limits.memory | string | `"8Gi"` |  |
| neo4j.neo4j.resources.requests.cpu | string | `"2"` |  |
| neo4j.neo4j.resources.requests.memory | string | `"4Gi"` |  |
| neo4j.services.admin.enabled | bool | `false` |  |
| neo4j.services.neo4j.enabled | bool | `false` |  |
| neo4j.services.neo4j.ports.bolt.enabled | bool | `true` |  |
| neo4j.services.neo4j.ports.bolt.port | int | `7687` |  |
| neo4j.services.neo4j.ports.bolt.targetPort | int | `7687` |  |
| neo4j.volumes.data.mode | string | `"volume"` |  |
| neo4j.volumes.data.volume.emptyDir | object | `{}` |  |
| prefect-server.enabled | bool | `true` |  |
| prefect-server.global.prefect.image.prefectTag | string | `"1.9.7"` |  |
| prefect-server.global.prefect.image.repository | string | `"registry.opsmill.io/opsmill/infrahub"` |  |
| prefect-server.postgresql.enabled | bool | `true` |  |
| prefect-server.postgresql.image.repository | string | `"bitnamilegacy/postgresql"` |  |
| prefect-server.postgresql.primary.persistence.enabled | bool | `false` |  |
| prefect-server.postgresql.primary.podLabels.infrahub/service | string | `"task-manager-db"` |  |
| prefect-server.server.args[0] | string | `"uvicorn"` |  |
| prefect-server.server.args[1] | string | `"--host"` |  |
| prefect-server.server.args[2] | string | `"0.0.0.0"` |  |
| prefect-server.server.args[3] | string | `"--port"` |  |
| prefect-server.server.args[4] | string | `"4200"` |  |
| prefect-server.server.args[5] | string | `"--factory"` |  |
| prefect-server.server.args[6] | string | `"infrahub.prefect_server.app:create_infrahub_prefect"` |  |
| prefect-server.server.command[0] | string | `"/usr/bin/tini"` |  |
| prefect-server.server.command[1] | string | `"-g"` |  |
| prefect-server.server.command[2] | string | `"--"` |  |
| prefect-server.server.env[0].name | string | `"PREFECT_UI_SERVE_BASE"` |  |
| prefect-server.server.env[0].value | string | `"/"` |  |
| prefect-server.server.podLabels.infrahub/service | string | `"task-manager"` |  |
| prefect-server.serviceAccount.create | bool | `false` |  |
| rabbitmq.auth.password | string | `"infrahub"` |  |
| rabbitmq.auth.username | string | `"infrahub"` |  |
| rabbitmq.enabled | bool | `true` |  |
| rabbitmq.image.repository | string | `"bitnamilegacy/rabbitmq"` |  |
| rabbitmq.image.tag | string | `"4.1.3-debian-12-r1"` |  |
| rabbitmq.metrics.enabled | bool | `true` |  |
| rabbitmq.nameOverride | string | `"message-queue"` |  |
| rabbitmq.persistence.enabled | bool | `false` |  |
| rabbitmq.podLabels.infrahub/service | string | `"message-queue"` |  |
| rabbitmq.startupProbe.enabled | bool | `true` |  |
| redis.architecture | string | `"standalone"` |  |
| redis.auth.enabled | bool | `false` |  |
| redis.enabled | bool | `true` |  |
| redis.image.repository | string | `"bitnamilegacy/redis"` |  |
| redis.image.tag | string | `"8.2.1-debian-12-r0"` |  |
| redis.master.persistence.enabled | bool | `false` |  |
| redis.master.podLabels.infrahub/service | string | `"cache"` |  |
| redis.master.resourcesPreset | string | `"medium"` |  |
| redis.master.service.ports.redis | int | `6379` |  |
| redis.nameOverride | string | `"cache"` |  |
| serviceAccount | object | `{"annotations":{},"create":false,"name":""}` | ServiceAccount configuration for the Infrahub pods |
| serviceAccount.annotations | object | `{}` | Annotations to add to the ServiceAccount |
| serviceAccount.create | bool | `false` | Create a ServiceAccount for the Infrahub pods |
| serviceAccount.name | string | `""` | Name of the ServiceAccount to use (auto-generated if empty and create is true; if empty and create is false, the field is omitted from pod specs) |
| upgrade.enabled | bool | `false` | Whether to run infrahub upgrade as a post-install/pre-upgrade hook job |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.

