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

## Dashboards

Seven Grafana dashboards are sourced from the [opsmill/infrahub
repository](https://github.com/opsmill/infrahub) at the version recorded in
`.dashboards-source` and adapted for Kubernetes by
`scripts/sync-dashboards.sh`. The chart's `appVersion` tracks this version.

The dashboards are **not** committed to this repository — they are fetched and
bundled into the chart only when it is packaged for release. To populate them
locally (for `helm template`/`helm lint` or a local install):

```sh
make sync-dashboards REF=v1.9.3
```

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
| loki | object | `{"backend":{"replicas":0},"chunksCache":{"enabled":false},"deploymentMode":"SingleBinary","enabled":true,"gateway":{"enabled":false},"loki":{"auth_enabled":false,"commonConfig":{"replication_factor":1},"compactor":{"compaction_interval":"10m","delete_request_store":"filesystem","retention_delete_delay":"2h","retention_delete_worker_count":100,"retention_enabled":true,"working_directory":"/var/loki/compactor"},"limits_config":{"allow_structured_metadata":true,"cardinality_limit":100000,"ingestion_burst_size_mb":64,"ingestion_rate_mb":32,"max_entries_limit_per_query":10000,"max_global_streams_per_user":15000,"max_query_lookback":"24h","max_streams_per_user":20000,"per_stream_rate_limit":"3MB","per_stream_rate_limit_burst":"5MB","reject_old_samples":true,"reject_old_samples_max_age":"168h","retention_period":"24h"},"schemaConfig":{"configs":[{"from":"2024-04-01","index":{"period":"24h","prefix":"loki_index_"},"object_store":"filesystem","schema":"v13","store":"tsdb"}]},"server":{"log_level":"warn"},"storage":{"type":"filesystem"}},"lokiCanary":{"enabled":false},"read":{"replicas":0},"resultsCache":{"enabled":false},"singleBinary":{"persistence":{"enabled":true,"size":"10Gi"},"replicas":1},"test":{"enabled":false},"write":{"replicas":0}}` | -------------------------------------------------------------------------- |
| prefectExporter | object | `{"affinity":{},"enabled":true,"image":{"pullPolicy":"","repository":"prefecthq/prometheus-prefect-exporter","tag":"3.3.0"},"logLevel":"WARNING","nodeSelector":{},"podAnnotations":{},"prefectApiUrl":"","replicas":1,"resources":{},"securityContext":{"runAsNonRoot":true,"runAsUser":1000},"service":{"port":8000,"type":"ClusterIP"},"tolerations":[]}` | -------------------------------------------------------------------------- |
| prefectExporter.enabled | bool | `true` | Enable the Prefect prometheus exporter sidecar Deployment. |
| prefectExporter.logLevel | string | `"WARNING"` | Log level passed to the exporter. |
| prefectExporter.prefectApiUrl | string | `""` | PREFECT_API_URL. Empty string defaults to the task-manager service of the sibling infrahub release (see _helpers.tpl). |
| prometheus | object | `{"alertmanager":{"enabled":false},"enabled":true,"kube-state-metrics":{"enabled":false},"prometheus-node-exporter":{"enabled":false},"prometheus-pushgateway":{"enabled":false},"server":{"extraArgs":{"log.level":"warn","web.enable-remote-write-receiver":""},"persistentVolume":{"enabled":true,"size":"20Gi"},"retention":"96h"},"serverFiles":{"prometheus.yml":{"scrape_configs":[]}}}` | -------------------------------------------------------------------------- |
| prometheus-node-exporter | object | `{"enabled":true}` | -------------------------------------------------------------------------- |
| tempo | object | `{"enabled":true,"persistence":{"enabled":true,"size":"10Gi"},"tempo":{"metricsGenerator":{"enabled":false},"receivers":{"otlp":{"protocols":{"grpc":{"endpoint":"0.0.0.0:4317"},"http":{}}}},"retention":"96h"}}` | -------------------------------------------------------------------------- |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
