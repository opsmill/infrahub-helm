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

The server is the [`grafana-mcp` chart](https://github.com/grafana-community/helm-charts/tree/main/charts/grafana-mcp)
of the Grafana community, version 0.37.0, installed as a dependency. (The `grafana-mcp` chart in
`grafana.github.io/helm-charts` is deprecated and cannot set a token for callers.) This chart adds a
hook Job. Settings are under two keys, because the values schema of the dependency rejects a key that
it does not know:

- `grafana-mcp-setup`: the flag `enabled` and the settings of the hook Job. `grafana-mcp-setup.enabled`
  is the only flag: it turns on the dependency and the Job together.
- `grafana-mcp`: the settings of the server, as the dependency defines them (Ingress, HTTPRoute,
  autoscaling, ServiceMonitor and others). This chart sets the options that make the server read-only.

In short: `grafana-mcp` holds the settings of the upstream chart, and `grafana-mcp-setup` holds the flag
and the token Job.

Set a token that the AI assistant sends, and turn the server on:

```sh
helm upgrade --install obs charts/infrahub-observability -n infrahub \
  --set grafana-mcp-setup.enabled=true \
  --set grafana-mcp.serverAuth.tokenSecret.name=my-grafana-mcp-token
```

The Secret `my-grafana-mcp-token` must have the key `token` (set `grafana-mcp.serverAuth.tokenSecret.key`
for another key). Use `grafana-mcp.serverAuth.token` instead to let the dependency create the Secret.
There is no default token: the chart refuses to render when neither value is set, and when
`grafana-mcp.serverAuth.token` is `null`, which turns authentication off.

What the chart creates:

- A Deployment, a Service (`ClusterIP`), a ServiceAccount and, for a token value, a Secret, all named
  `<release>-grafana-mcp`. They come from the dependency.
- A hook Job, after each install and upgrade, that creates the Grafana service account
  `infrahub-grafana-mcp` and stores its token in the Secret `grafana-mcp-service-account-token`.
  The Job logs in to Grafana as the admin user, with the admin Secret of the Grafana sub-chart or
  `grafana-mcp-setup.grafanaAdminSecret`. It keeps a stored token that Grafana still accepts and replaces
  one that Grafana refuses. The Job and the server never print a token.

The name of the Grafana token Secret is the `secretName` of the volume `grafana-token` in
`grafana-mcp.volumes`. The Job reads the name from there, and the chart refuses to render without that
volume. A list of volumes cannot be templated, so the name does not contain the release name: two
releases of this chart in one namespace share the Secret, and each Job replaces the token of the other
when their Grafana servers differ. Give each release its own name in `grafana-mcp.volumes`.

The Grafana address is `grafana-mcp.grafana.url`. Its default, `http://obs-grafana`, is the Service of
a release named `obs`. With another release name, or with `grafana.enabled=false`, set the address: the
chart refuses to render with the default in those cases.

After an install, the pod gets the token file about one to two minutes after the Job writes the
Secret, because the kubelet refreshes mounted Secrets on a timer. Until then, calls to Grafana
through the server fail with HTTP 401. The server reads the file on every call, so it needs no restart.
`helm uninstall` does not remove the token Secret, because the Job created it: delete it by hand.

### Read-only options

`grafana-mcp.disableWrite` and `grafana-mcp.disabledCategories` (`api`, `docs`, `plugin`) make the
server read-only. The chart refuses to render when one flag is missing, whether it comes from these
values or from `grafana-mcp.extraArgs`.

### Connecting from your computer

Forward the port. The default `grafana-mcp.allowedHosts.extra` accepts `localhost:8100`:

```sh
kubectl port-forward -n infrahub svc/<release>-grafana-mcp 8100:8000
```

The server is then at `http://localhost:8100/mcp`, and the assistant sends the token as
`Authorization: Bearer <token>`. The dependency also accepts the names of the Service and, with
`grafana-mcp.ingress.enabled`, the hosts of the Ingress. For another host name or port, add it to
`grafana-mcp.allowedHosts.extra`.

### TLS

Without TLS flags, the server serves plain HTTP, so the token travels unencrypted. An Ingress in front
of it must use TLS. A `LoadBalancer` or `NodePort` Service needs the server to serve HTTPS: the chart
refuses to render without `--server.tls-cert-file` in `grafana-mcp.extraArgs`. Mount a
`kubernetes.io/tls` Secret (for example from cert-manager) and add the flags. A list in a values file
replaces the default list, so repeat the default arguments and the default `grafana-token` volume:

```yaml
grafana-mcp:
  extraArgs:
    - --transport
    - streamable-http
    - --address
    - 0.0.0.0:8000
    - --healthz-address
    - ":8081"
    - --usage-stats=disabled
    - --server.tls-cert-file=/etc/grafana-mcp/tls/tls.crt
    - --server.tls-key-file=/etc/grafana-mcp/tls/tls.key
  volumes:
    - name: grafana-token
      secret:
        secretName: grafana-mcp-service-account-token
        optional: true
        defaultMode: 0440
    - name: tls
      secret:
        secretName: my-tls-secret
        defaultMode: 0440
  volumeMounts:
    - name: grafana-token
      mountPath: /var/run/grafana-mcp
      readOnly: true
    - name: tls
      mountPath: /etc/grafana-mcp/tls
      readOnly: true
```

The probes check `/healthz` on the side listener, which serves plain HTTP also when the main port
serves HTTPS, so they need no change. The pod runs with `fsGroup: 999`, so that the server can read the
key. Restart the pod after a certificate renewal, so that the server reads the new files.

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
| https://grafana-community.github.io/helm-charts | grafana-mcp | 0.37.0 |
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
| grafana-mcp-setup | object | `{"enabled":false,"grafanaAdminSecret":"","tokenJob":{"containerSecurityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true},"image":{"pullPolicy":"","repository":"grafana/grafana","tag":"11.1.5"},"resources":{},"securityContext":{"fsGroup":472,"runAsGroup":472,"runAsNonRoot":true,"runAsUser":472}}}` | -------------------------------------------------------------------------- |
| grafana-mcp-setup.enabled | bool | `false` | Install the Grafana MCP server. This one flag turns on both the `grafana-mcp` dependency and the hook Job of this chart. When false, the chart creates no object for the server. |
| grafana-mcp-setup.grafanaAdminSecret | string | `""` | Name of the Secret with the Grafana admin user and password, which the hook Job uses to create the service account. Empty: the admin Secret of the grafana sub-chart (or `grafana.admin.existingSecret` when that is set). |
| grafana-mcp-setup.tokenJob.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | Container-level security context of the Job. |
| grafana-mcp-setup.tokenJob.image | object | `{"pullPolicy":"","repository":"grafana/grafana","tag":"11.1.5"}` | Image of the hook Job. It needs curl, sed, grep and base64: the Grafana image has them. |
| grafana-mcp-setup.tokenJob.resources | object | `{}` | Resources of the Job. |
| grafana-mcp-setup.tokenJob.securityContext | object | `{"fsGroup":472,"runAsGroup":472,"runAsNonRoot":true,"runAsUser":472}` | Pod-level security context of the Job pod. |
| grafana-mcp.allowedHosts | object | `{"extra":["localhost:8100","127.0.0.1:8100"]}` | Host header values that the server accepts, besides the loopback addresses and the names of the Service. A client that uses another address, such as `kubectl port-forward svc/<name> 8100:8000`, needs its host and port here. |
| grafana-mcp.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true,"runAsGroup":999,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Container-level security context. |
| grafana-mcp.disableWrite | bool | `true` |  |
| grafana-mcp.disabledCategories[0] | string | `"api"` |  |
| grafana-mcp.disabledCategories[1] | string | `"docs"` |  |
| grafana-mcp.disabledCategories[2] | string | `"plugin"` |  |
| grafana-mcp.env | object | `{"DO_NOT_TRACK":"1","GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE":"/var/run/grafana-mcp/token"}` | Environment variables of the server. |
| grafana-mcp.env.DO_NOT_TRACK | string | `"1"` | Do not send usage data. |
| grafana-mcp.env.GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE | string | `"/var/run/grafana-mcp/token"` | File with the Grafana token. The hook Job writes the token to a Secret that the `grafana-token` volume mounts here. The server reads the file on every call. |
| grafana-mcp.extraArgs | list | `["--transport","streamable-http","--address","0.0.0.0:8000","--healthz-address",":8081","--usage-stats=disabled","--instructions-append","In this stack the Grafana MCP server only reads: it has no tool that creates or changes dashboards, folders, annotations, incidents, alert rules or data sources."]` | Arguments of the server. The dependency adds the flags of disableWrite, disabledCategories and allowedHosts itself. To serve HTTPS, add `--server.tls-cert-file=/etc/grafana-mcp/tls/tls.crt` and `--server.tls-key-file=/etc/grafana-mcp/tls/tls.key`, and mount the Secret with `volumes` and `volumeMounts` (see the README). Do not change the port of `--address` without `service.port`. |
| grafana-mcp.grafana.url | string | `"http://obs-grafana"` | Address of Grafana. The default is the Service of a release named `obs`. With another release name, set it to `http://<release>-grafana`: the chart refuses to render otherwise. When `grafana.enabled` is false, set the address of your Grafana. |
| grafana-mcp.image.repository | string | `"grafana/mcp-grafana"` | Image of the Grafana MCP server. |
| grafana-mcp.image.tag | string | `"2.0.2@sha256:78d208116ec52b09b44f0eca66892073b39aefcb64483c54d43255c8eab7e97a"` | Tag and digest of the image. The dependency builds the image as repository:tag, so the digest is part of the tag. The image is under security review at this version. |
| grafana-mcp.livenessProbe.httpGet.httpHeaders | string | `nil` |  |
| grafana-mcp.livenessProbe.httpGet.path | string | `"/healthz"` |  |
| grafana-mcp.livenessProbe.httpGet.port | int | `8081` |  |
| grafana-mcp.livenessProbe.periodSeconds | int | `20` |  |
| grafana-mcp.livenessProbe.timeoutSeconds | string | `nil` |  |
| grafana-mcp.readinessProbe.httpGet.path | string | `"/healthz"` |  |
| grafana-mcp.readinessProbe.httpGet.port | int | `8081` |  |
| grafana-mcp.readinessProbe.periodSeconds | int | `10` |  |
| grafana-mcp.readinessProbe.tcpSocket | string | `nil` |  |
| grafana-mcp.securityContext | object | `{"fsGroup":999,"runAsGroup":999,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. The image runs as user 1000, group 999. fsGroup lets that group read a mounted TLS key. |
| grafana-mcp.serverAuth | object | `{"token":"","tokenSecret":{"key":"token","name":""}}` | Token that AI assistants send to the server, as a bearer token. Set `token` or `tokenSecret.name`, or the chart refuses to render: without it, the dependency would generate a token or turn authentication off. |
| grafana-mcp.serverAuth.token | string | `""` | The token as a plain value. The dependency stores it in a Secret. Prefer `tokenSecret`. |
| grafana-mcp.serverAuth.tokenSecret.key | string | `"token"` | Key of the token in that Secret. |
| grafana-mcp.serverAuth.tokenSecret.name | string | `""` | Name of an existing Secret that holds the token. Takes the place of `token`. |
| grafana-mcp.startupProbe | object | `{"failureThreshold":30,"httpGet":{"path":"/healthz","port":8081},"periodSeconds":2}` | Probes on /healthz of the side listener (--healthz-address). It serves plain HTTP also when the main port serves HTTPS, and it is outside the Host check that rejects a probe, which sends the pod IP as its Host header. The default liveness probe of the dependency calls the main port. |
| grafana-mcp.volumeMounts | list | `[{"mountPath":"/var/run/grafana-mcp","name":"grafana-token","readOnly":true}]` | Volume mounts of the server. |
| grafana-mcp.volumes | list | `[{"name":"grafana-token","secret":{"defaultMode":288,"optional":true,"secretName":"grafana-mcp-service-account-token"}}]` | Volumes of the pod. The volume named `grafana-token` must stay: the hook Job writes the Grafana token to the Secret it names, and the chart refuses to render without it. The Secret is optional so the pod starts before the Job has written it, and `helm install --wait` can reach the hook. The kubelet adds the token file 30 to 90 seconds after the Job. |
| grafana.adminPassword | string | `"admin"` | Default password matches docker-compose dev parity. Override via `grafana.admin.existingSecret` in production. |
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
