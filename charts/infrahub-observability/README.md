# infrahub-observability

Observability stack (Alloy, Loki, Prometheus, Tempo, Grafana) for Infrahub on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

This chart deploys the same observability stack that Infrahub ships for local
Docker Compose development — Grafana Alloy (logs + metrics), Loki (logs),
Prometheus (metrics + remote-write receiver), Tempo (traces), Grafana
(visualization), and the Prefect prometheus exporter — onto Kubernetes. It is
designed to be installed alongside the [infrahub](../infrahub) or
[infrahub-enterprise](../infrahub-enterprise) chart in the same namespace.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.0+
- PV provisioner support in the underlying infrastructure (Loki, Prometheus,
  Tempo and Grafana enable persistence by default)
- The infrahub chart is installed in the same namespace, or its release
  name is supplied via `global.infrahubReleaseName`

## Installing the Chart

```sh
helm dependency update charts/infrahub-observability
helm install obs charts/infrahub-observability -n infrahub
```

## Wiring infrahub to send traces to Tempo

The infrahub chart exposes a `global.tracing` block that emits the
`INFRAHUB_TRACE_*` env vars on the server and task-worker deployments. Point
it at the Tempo service this chart creates:

```yaml
# infrahub values
global:
  tracing:
    enabled: true
    endpoint: "obs-tempo:4317"   # <obs-release-name>-tempo:4317 (host:port for grpc)
    protocol: grpc
    insecure: true
```

## Dashboards & datasources

The Grafana provisioning bundled into this chart — seven dashboards and the
datasource definitions — is sourced from the [opsmill/infrahub
repository](https://github.com/opsmill/infrahub) at the version recorded in
`.upstream-source` and adapted for Kubernetes by `scripts/sync-upstream.sh`
(docker-compose labels/hostnames rewritten to their Kubernetes equivalents).
The chart's `appVersion` tracks this version.

These files are **not** committed to this repository — they are fetched and
bundled into the chart only when it is packaged for release. To populate them
locally (for `helm template`/`helm lint` or a local install):

```sh
make sync-upstream REF=v1.9.3
```

## Grafana MCP server

The chart can install the [Grafana MCP server](https://github.com/grafana/mcp-grafana), so that an AI
assistant such as Claude Code reads the metrics, logs and traces of the stack through Grafana. The
server is off by default. When it is on, it only reads: it has no tool that changes Grafana, it does
not send usage statistics, and its Grafana service account has the Viewer role.

Set a token that the AI assistant sends, and turn the server on:

```sh
helm upgrade --install obs charts/infrahub-observability -n infrahub \
  --set grafanaMcp.enabled=true \
  --set grafanaMcp.serverToken.existingSecret=my-grafana-mcp-token
```

Use `grafanaMcp.serverToken.value` instead to let the chart create that Secret. There is no default
token: the install fails when neither value is set.

What the chart creates:

- A Deployment and a Service (`ClusterIP`) named `<fullname>-grafana-mcp`.
- A hook Job, after each install and upgrade, that creates the Grafana service account
  `infrahub-grafana-mcp` and stores its token in the Secret `<fullname>-grafana-mcp-grafana-token`.
  The Job logs in to Grafana as the admin user, with the admin Secret of the Grafana sub-chart or
  `grafanaMcp.grafana.adminSecret`. It keeps a stored token that Grafana still accepts and replaces
  one that Grafana refuses. The Job and the server never print a token.

After an install, the pod gets the token file about one to two minutes after the Job writes the
Secret, because the kubelet refreshes mounted Secrets on a timer. Until then, calls to Grafana
through the server fail with HTTP 401. The server reads the file on every call, so it needs no restart.
`helm uninstall` does not remove the token Secret, because the Job created it: delete it by hand.

To connect from your computer, forward the port. The default `grafanaMcp.allowedHosts` accepts
`localhost:8100`:

```sh
kubectl port-forward -n infrahub svc/<fullname>-grafana-mcp 8100:8000
```

The server is then at `http://localhost:8100/mcp`, and the assistant sends the token as
`Authorization: Bearer <token>`. For another host name or port, for example an Ingress, add it to
`grafanaMcp.allowedHosts`.

Without `grafanaMcp.tls.existingSecret`, the server serves plain HTTP, so the token travels
unencrypted. An Ingress in front of it must use TLS. A `LoadBalancer` or `NodePort` Service needs
`grafanaMcp.tls.existingSecret`, a `kubernetes.io/tls` Secret (for example from cert-manager): the
chart refuses to render without it. With the Secret, the server serves HTTPS. Restart the pod after
a certificate renewal, so that the server reads the new files.

## Uninstalling the Chart

```sh
helm delete obs -n infrahub
```

Persistent volumes for Loki, Prometheus, Tempo and Grafana are retained by
default. Delete the PVCs explicitly if you want a clean slate.

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| OpsMill |  | <https://github.com/opsmill> |

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://grafana.github.io/helm-charts | alloy | 1.0.3 |
| https://grafana.github.io/helm-charts | grafana | 8.5.0 |
| https://grafana.github.io/helm-charts | loki | 6.16.0 |
| https://grafana.github.io/helm-charts | tempo | 1.10.0 |
| https://prometheus-community.github.io/helm-charts | prometheus | 25.27.0 |
| https://prometheus-community.github.io/helm-charts | prometheus-node-exporter | 4.36.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| alloy | object | `{"alloy":{"clustering":{"enabled":false},"configMap":{"create":false,"key":"config.alloy","name":""},"mounts":{"dockercontainers":false,"varlog":true}},"cadvisor":{"enabled":true},"controller":{"type":"daemonset"},"enabled":true}` | -------------------------------------------------------------------------- |
| alloy.alloy.configMap.name | string | `""` | Name of the ConfigMap that holds Alloy's config.alloy file. Resolved at render time via the helper. |
| alloy.cadvisor | object | `{"enabled":true}` | Scrape kubelet cAdvisor for per-container CPU/memory/network/fs metrics. Requires the Alloy ServiceAccount to have `get nodes/proxy`, which the subchart's default RBAC already grants. Disable if your cluster's policy forbids that permission; the Container Resources and Neo4j Monitoring dashboards will then show no data. |
| global | object | `{"commonAnnotations":{},"commonLabels":{},"imagePullPolicy":"IfNotPresent","imagePullSecrets":[],"infrahubNamespace":"","infrahubReleaseName":"infrahub","kubernetesClusterDomain":"cluster.local","podLabels":{}}` | Global values shared across all sub-charts and templates in this chart. |
| global.commonAnnotations | object | `{}` | Annotations added to every resource managed by this chart. |
| global.commonLabels | object | `{}` | Labels added to every resource managed by this chart. |
| global.imagePullPolicy | string | `"IfNotPresent"` | Default imagePullPolicy for in-chart workloads (currently only the Prefect exporter). |
| global.imagePullSecrets | list | `[]` | Image pull secrets propagated to in-chart workloads. |
| global.infrahubNamespace | string | `""` | Namespace where the sibling infrahub release lives. Empty string means the same namespace as this release. |
| global.infrahubReleaseName | string | `"infrahub"` | Release name of the sibling infrahub chart. Used by the Prefect exporter to derive the default PREFECT_API_URL and by Alloy when scoping discovery. |
| global.kubernetesClusterDomain | string | `"cluster.local"` | Cluster DNS domain. Used for fully-qualified service names if needed. |
| global.podLabels | object | `{}` | Pod-level labels merged into the standard selector labels. |
| grafana | object | `{"adminPassword":"admin","adminUser":"admin","enabled":true,"env":{"GF_LOG_LEVEL":"warn","GF_USERS_ALLOW_SIGN_UP":"false"},"ingress":{"enabled":false},"persistence":{"enabled":true,"size":"5Gi"},"service":{"type":"ClusterIP"},"sidecar":{"dashboards":{"enabled":true,"label":"grafana_dashboard","labelValue":"1","searchNamespace":"ALL"},"datasources":{"enabled":true,"label":"grafana_datasource","labelValue":"1","searchNamespace":"ALL"}}}` | -------------------------------------------------------------------------- |
| grafana.adminPassword | string | `"admin"` | Default password matches docker-compose dev parity. Override via `grafana.admin.existingSecret` in production. |
| grafanaMcp | object | `{"affinity":{},"allowedHosts":"localhost:8100,127.0.0.1:8100","containerSecurityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true},"enabled":false,"grafana":{"adminSecret":"","url":""},"image":{"digest":"sha256:78d208116ec52b09b44f0eca66892073b39aefcb64483c54d43255c8eab7e97a","pullPolicy":"","repository":"grafana/mcp-grafana","tag":"2.0.2"},"nodeSelector":{},"podAnnotations":{},"replicas":1,"resources":{},"securityContext":{"fsGroup":999,"runAsGroup":999,"runAsNonRoot":true,"runAsUser":1000},"serverToken":{"existingSecret":"","existingSecretKey":"token","value":""},"service":{"port":8000,"type":"ClusterIP"},"serviceAccountJob":{"containerSecurityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true},"image":{"pullPolicy":"","repository":"grafana/grafana","tag":"11.1.5"},"resources":{},"securityContext":{"fsGroup":472,"runAsGroup":472,"runAsNonRoot":true,"runAsUser":472}},"tls":{"existingSecret":""},"tolerations":[]}` | -------------------------------------------------------------------------- |
| grafanaMcp.allowedHosts | string | `"localhost:8100,127.0.0.1:8100"` | Host header values that the server accepts, separated by commas. Add the host and port of any URL other than a `kubectl port-forward svc/<name> 8100:8000`. |
| grafanaMcp.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | Container-level security context of the server. |
| grafanaMcp.enabled | bool | `false` | Install the Grafana MCP server. When false, the chart creates no object for it. |
| grafanaMcp.grafana.adminSecret | string | `""` | Name of the Secret with the Grafana admin user and password, which the hook Job uses to create the service account. Empty: the admin Secret of the grafana sub-chart (or `grafana.admin.existingSecret` when that is set). |
| grafanaMcp.grafana.url | string | `""` | Address of Grafana. Empty: the Grafana Service of this release. |
| grafanaMcp.image.digest | string | `"sha256:78d208116ec52b09b44f0eca66892073b39aefcb64483c54d43255c8eab7e97a"` | Digest of the image. The chart pulls repository:tag@digest. Empty: pull by tag only. |
| grafanaMcp.image.pullPolicy | string | `""` | Image pull policy. Empty: global.imagePullPolicy. |
| grafanaMcp.image.repository | string | `"grafana/mcp-grafana"` | Image of the Grafana MCP server. |
| grafanaMcp.image.tag | string | `"2.0.2"` | Tag of the image. |
| grafanaMcp.securityContext | object | `{"fsGroup":999,"runAsGroup":999,"runAsNonRoot":true,"runAsUser":1000}` | Pod-level security context of the server pod. The image runs as user 1000, group 999. fsGroup lets that group read the mounted TLS key. |
| grafanaMcp.serverToken | object | `{"existingSecret":"","existingSecretKey":"token","value":""}` | Token that AI assistants send to the server (as a bearer token). It has no default: set `value` or `existingSecret`, or the install fails. |
| grafanaMcp.serverToken.existingSecret | string | `""` | Name of an existing Secret that holds the token. Takes the place of `value`. |
| grafanaMcp.serverToken.existingSecretKey | string | `"token"` | Key of the token in the existing Secret. |
| grafanaMcp.serverToken.value | string | `""` | The token as a plain value. The chart stores it in a Secret. Prefer `existingSecret`. |
| grafanaMcp.service.port | int | `8000` | Service port. |
| grafanaMcp.service.type | string | `"ClusterIP"` | Service type. LoadBalancer and NodePort open the server to a network, so they need `tls.existingSecret`. |
| grafanaMcp.serviceAccountJob.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | Container-level security context of the Job. |
| grafanaMcp.serviceAccountJob.image | object | `{"pullPolicy":"","repository":"grafana/grafana","tag":"11.1.5"}` | Image of the hook Job. It needs curl, sed, grep and base64: the Grafana image has them. |
| grafanaMcp.serviceAccountJob.securityContext | object | `{"fsGroup":472,"runAsGroup":472,"runAsNonRoot":true,"runAsUser":472}` | Pod-level security context of the Job pod. |
| grafanaMcp.tls.existingSecret | string | `""` | Name of a kubernetes.io/tls Secret (keys tls.crt and tls.key), for example from cert-manager. The server then serves HTTPS. Empty: the server serves plain HTTP. |
| loki | object | `{"backend":{"replicas":0},"chunksCache":{"enabled":false},"deploymentMode":"SingleBinary","enabled":true,"gateway":{"enabled":false},"loki":{"auth_enabled":false,"commonConfig":{"replication_factor":1},"compactor":{"compaction_interval":"10m","delete_request_store":"filesystem","retention_delete_delay":"2h","retention_delete_worker_count":100,"retention_enabled":true,"working_directory":"/var/loki/compactor"},"limits_config":{"allow_structured_metadata":true,"cardinality_limit":100000,"ingestion_burst_size_mb":64,"ingestion_rate_mb":32,"max_entries_limit_per_query":10000,"max_global_streams_per_user":15000,"max_query_lookback":"24h","max_streams_per_user":20000,"per_stream_rate_limit":"3MB","per_stream_rate_limit_burst":"5MB","reject_old_samples":true,"reject_old_samples_max_age":"168h","retention_period":"24h"},"schemaConfig":{"configs":[{"from":"2024-04-01","index":{"period":"24h","prefix":"loki_index_"},"object_store":"filesystem","schema":"v13","store":"tsdb"}]},"server":{"log_level":"warn"},"storage":{"type":"filesystem"}},"lokiCanary":{"enabled":false},"read":{"replicas":0},"resultsCache":{"enabled":false},"singleBinary":{"persistence":{"enabled":true,"size":"10Gi"},"replicas":1},"test":{"enabled":false},"write":{"replicas":0}}` | -------------------------------------------------------------------------- |
| prefectExporter | object | `{"affinity":{},"containerSecurityContext":{},"enabled":true,"extraEnv":[],"image":{"pullPolicy":"","repository":"prefecthq/prometheus-prefect-exporter","tag":"3.3.0"},"logLevel":"WARNING","nodeSelector":{},"podAnnotations":{},"prefectApiUrl":"","readinessProbe":{"failureThreshold":3,"httpGet":{"path":"/metrics","port":"metrics"},"initialDelaySeconds":10,"periodSeconds":30,"timeoutSeconds":10},"replicas":1,"resources":{},"securityContext":{"runAsNonRoot":true,"runAsUser":1000},"service":{"port":8000,"type":"ClusterIP"},"tolerations":[]}` | -------------------------------------------------------------------------- |
| prefectExporter.containerSecurityContext | object | `{}` | Container-level security context for the prefect-exporter container. Empty by default so it stays optional; set this to satisfy cluster policies that require a container-level securityContext (e.g. allowPrivilegeEscalation, readOnlyRootFilesystem, capabilities). |
| prefectExporter.enabled | bool | `true` | Enable the Prefect prometheus exporter sidecar Deployment. |
| prefectExporter.extraEnv | list | `[]` | Extra environment variables for the prefect-exporter container, for example the exporter's OFFSET_MINUTES or FAILED_RUNS_OFFSET_MINUTES. |
| prefectExporter.logLevel | string | `"WARNING"` | Log level passed to the exporter. |
| prefectExporter.prefectApiUrl | string | `""` | PREFECT_API_URL. Empty string defaults to the task-manager service of the sibling infrahub release (see _helpers.tpl). |
| prefectExporter.readinessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/metrics","port":"metrics"},"initialDelaySeconds":10,"periodSeconds":30,"timeoutSeconds":10}` | Readiness probe for the prefect-exporter container. The exporter builds /metrics by querying the Prefect API on every request, so the response time grows with the number of flows and deployments. timeoutSeconds is set well above the Kubernetes default of 1s so the pod becomes Ready on larger instances. Set to {} to remove the probe. |
| prefectExporter.securityContext | object | `{"runAsNonRoot":true,"runAsUser":1000}` | Pod-level security context for the Prefect exporter pod. |
| prometheus | object | `{"alertmanager":{"enabled":false},"enabled":true,"kube-state-metrics":{"enabled":false},"prometheus-node-exporter":{"enabled":false},"prometheus-pushgateway":{"enabled":false},"server":{"extraArgs":{"log.level":"warn","web.enable-remote-write-receiver":""},"persistentVolume":{"enabled":true,"size":"20Gi"},"retention":"96h"},"serverFiles":{"prometheus.yml":{"scrape_configs":[]}}}` | -------------------------------------------------------------------------- |
| prometheus-node-exporter | object | `{"enabled":true}` | -------------------------------------------------------------------------- |
| tempo | object | `{"enabled":true,"persistence":{"enabled":true,"size":"10Gi"},"tempo":{"metricsGenerator":{"enabled":false},"receivers":{"otlp":{"protocols":{"grpc":{"endpoint":"0.0.0.0:4317"},"http":{}}}},"retention":"96h"}}` | -------------------------------------------------------------------------- |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
