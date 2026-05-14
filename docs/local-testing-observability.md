# Local testing: infrahub + infrahub-observability

This guide walks through installing the [infrahub](../charts/infrahub) and
[infrahub-observability](../charts/infrahub-observability) charts side-by-side
in the same namespace, wiring infrahub to send traces to Tempo, and verifying
that logs, metrics, and traces all reach Grafana.

**Cluster-agnostic.** Any Kubernetes cluster will do (kind, minikube, k3d,
Docker Desktop, EKS/GKE/AKS, etc.) — these steps assume `kubectl` is already
pointed at the cluster you want to test against and the default
StorageClass can provision PVs (Loki, Prometheus, Tempo, Grafana, and Neo4j
all request persistent volumes by default).

## Prerequisites

- `kubectl` configured against a working cluster
- `helm` 3.0+
- A cluster with at least ~8 CPU and ~12 GiB of memory available — the full
  stack (Neo4j, RabbitMQ, Redis, Prefect, Loki, Prometheus, Tempo, Grafana)
  is not lightweight
- A working default StorageClass

Verify:

```sh
kubectl cluster-info
kubectl get storageclass
```

## 1. Create the namespace

Both charts must live in the same namespace so that the observability chart's
service helpers resolve to the right targets.

```sh
kubectl create namespace infrahub
```

## 2. Install the infrahub chart

From the repository root:

```sh
helm dependency update charts/infrahub
helm install infrahub charts/infrahub \
    --namespace infrahub \
    --wait --timeout 15m
```

Wait for the rollout to settle:

```sh
kubectl --namespace infrahub get pods -w
```

You should see (eventually) all of these pods `Running` and `1/1` ready:

- `infrahub-infrahub-server-*`
- `infrahub-infrahub-task-worker-*` (× 2 replicas)
- `infrahub-database-0` (Neo4j, headless StatefulSet)
- `infrahub-cache-master-0` (Redis)
- `infrahub-message-queue-0` (RabbitMQ)
- `infrahub-postgresql-0` (used by Prefect)
- `prefect-server-*` (note: no `infrahub-` prefix — the Prefect subchart
  uses a fixed Service name `prefect-server`, which the observability chart
  scrapes by that exact name)

## 3. Install the infrahub-observability chart

```sh
helm dependency update charts/infrahub-observability
helm install obs charts/infrahub-observability \
    --namespace infrahub \
    --wait --timeout 15m
```

The chart's helpers default to `global.infrahubReleaseName: infrahub` and
the current namespace, so no overrides are needed when both releases live in
the `infrahub` namespace and the infrahub release is named `infrahub`.

If you used a different release name for infrahub, override it:

```sh
helm install obs charts/infrahub-observability \
    --namespace infrahub \
    --set global.infrahubReleaseName=<your-release-name>
```

The post-install NOTES print the exact endpoints — re-read them later with:

```sh
helm status obs --namespace infrahub
```

## 4. Wire infrahub to send traces to Tempo

The infrahub chart exposes a `global.tracing` block that emits the
`INFRAHUB_TRACE_*` env vars on the server and task-worker Deployments. Point
it at the Tempo service the observability chart created:

```sh
helm upgrade infrahub charts/infrahub \
    --namespace infrahub \
    --reuse-values \
    --set global.tracing.enabled=true \
    --set global.tracing.endpoint=obs-tempo:4317 \
    --set global.tracing.protocol=grpc \
    --set global.tracing.insecure=true
```

This triggers a rolling restart of the server and task-worker pods. Confirm
the env vars landed on a running pod:

```sh
kubectl --namespace infrahub get pod \
    -l service=infrahub-server \
    -o jsonpath='{.items[0].spec.containers[0].env[*].name}' \
    | tr ' ' '\n' | grep INFRAHUB_TRACE
```

Expected:

```
INFRAHUB_TRACE_ENABLE
INFRAHUB_TRACE_INSECURE
INFRAHUB_TRACE_EXPORTER_TYPE
INFRAHUB_TRACE_EXPORTER_PROTOCOL
INFRAHUB_TRACE_EXPORTER_ENDPOINT
```

## 5. Access Grafana and verify the stack

Port-forward Grafana:

```sh
kubectl --namespace infrahub port-forward svc/obs-grafana 3000:80
```

Look up the admin password:

```sh
kubectl --namespace infrahub get secret obs-grafana \
    -o jsonpath="{.data.admin-password}" | base64 -d ; echo
```

Open <http://localhost:3000> and sign in as `admin` with that password.

### Verify datasources

Go to **Connections → Data sources**. You should see three datasources
auto-provisioned by the sidecar (the chart ships a ConfigMap labelled
`grafana_datasource=1`):

- **Prometheus** — `http://obs-prometheus-server`
- **Loki** — `http://obs-loki:3100`
- **Tempo** — `http://obs-tempo:3100`

Click each and hit **Save & test** — all three should report healthy.

### Verify dashboards

Go to **Dashboards**. You should see seven dashboards provisioned (one
ConfigMap per dashboard, labelled `grafana_dashboard=1`):

- Container Resources
- Infrahub Monitoring
- Loki Monitoring
- Neo4j Monitoring
- Prefect Flow Run Overview
- Prefect Platform Overview
- RabbitMQ Instance Monitoring

Open **Infrahub Monitoring** — panels backed by Prometheus should populate
within a few minutes.

### Verify logs are flowing into Loki

In Grafana, go to **Explore**, pick the **Loki** datasource, and run:

```logql
{namespace="infrahub"}
```

You should see streaming log lines from infrahub pods within ~30 seconds of
the pods generating output. Alloy (running as a DaemonSet) is scraping
`/var/log/pods` and pushing into Loki.

### Verify metrics are flowing into Prometheus

Note: Prometheus does no scraping itself in this stack — Alloy is the source
of truth for scrapes and pushes via remote-write — so `kubectl port-forward
svc/obs-prometheus-server 9090:80` then visiting `/targets` will show an
empty page. Verify via the metrics themselves.

In **Explore**, pick the **Prometheus** datasource, and run:

```promql
group by (job) ({__name__!=""})
```

You should see 8 jobs: `infrahub-server`, `infrahub-worker`, `logs`,
`message-queue`, `node-exporter`, `prometheus`, `task-manager`,
`task-manager-exporter`. The `database` job is not present by default
because the Neo4j chart doesn't expose prometheus metrics (see "Service
discovery and toggles" below).

For Prefect-specific metrics:

```promql
prefect_info_flow_runs
```

This series is populated by the Prefect exporter Deployment shipped by this
chart.

### Verify traces are flowing into Tempo

Exercise infrahub a bit so it emits spans:

```sh
kubectl --namespace infrahub port-forward svc/infrahub-infrahub-server 8000:8000
# in a separate terminal, hit a few endpoints
for i in $(seq 1 10); do
    curl -s http://localhost:8000/api/schema/summary > /dev/null
    curl -s -X POST -H "Content-Type: application/json" \
        -d '{"query":"{ Branch { edges { node { name } } } }"}' \
        http://localhost:8000/graphql > /dev/null
done
```

Wait ~10 seconds (Tempo batches), then in Grafana, **Explore** → **Tempo**
→ **Search**, set Service Name to `infrahub-server`, and click **Run
query**. You should see traces appear.

You can also check from the CLI:

```sh
kubectl --namespace infrahub port-forward svc/obs-tempo 3100:3100
# separate terminal:
curl -s 'http://localhost:3100/api/search?tags=service.name%3Dinfrahub-server' | jq '.traces | length'
```

A non-zero count confirms traces are landing in Tempo.

**Gotcha:** If you see `WRONG_VERSION_NUMBER` SSL handshake errors in the
infrahub-server logs (`kubectl logs -l service=infrahub-server`), make sure
you're running an infrahub chart that includes the `OTEL_EXPORTER_OTLP_INSECURE`
env-var fallback. Upstream infrahub's tracing wrapper doesn't honour
`INFRAHUB_TRACE_INSECURE` for the gRPC exporter — the OTel SDK env var is
what actually disables TLS.

## 6. (Optional) Teardown

```sh
helm uninstall obs --namespace infrahub
helm uninstall infrahub --namespace infrahub

# Persistent volumes for Loki/Prometheus/Tempo/Grafana/Neo4j are NOT
# deleted with the releases. Remove them too if you want a clean slate:
kubectl --namespace infrahub delete pvc --all

kubectl delete namespace infrahub
```

## Service discovery and toggles

It's useful to know what the chart actually does for discovery — what it
scrapes by default, how it finds targets, and what the knobs are.

### Logs — namespace-scoped pod discovery

Alloy runs as a DaemonSet and uses `discovery.kubernetes` with
`role = "pod"`, scoped to a single namespace (the same namespace as the
sibling infrahub release, override via `global.infrahubNamespace`). **Every
pod in that namespace gets its logs shipped to Loki** — there is no label
filter on log ingestion. Pod log streams arrive in Loki with three
auto-promoted labels (`namespace`, `pod`, `container`) plus one chart-
specific label `component`, which is sourced from the `service:` pod label
that infrahub workloads carry (e.g. `service: infrahub-server`,
`service: database`). The `component` label is what the parsing pipeline
stages in the Alloy config key off of for per-workload log shape parsing.

Toggles:

| Setting | Effect |
| --- | --- |
| `global.infrahubNamespace` | Which namespace Alloy collects pod logs from. Empty = release namespace. |
| `alloy.enabled` | Disable the entire Alloy DaemonSet (no logs, no metric scraping). |
| `loki.enabled` | Disable Loki itself. Alloy will keep collecting but the write will fail; usually only disable both together. |

### cAdvisor — per-container resource metrics

Alloy scrapes the kubelet's `/metrics/cadvisor` endpoint (via the API server
proxy) once per node to collect `container_cpu_usage_seconds_total`,
`container_memory_usage_bytes`, `container_network_*`, and `container_fs_*`
series. These feed the **Container Resources** and **Neo4j Monitoring**
dashboards.

The scrape needs `get` on `nodes/proxy` at cluster scope. The Alloy subchart
grants this by default — no extra RBAC. Disable via
`alloy.cadvisor.enabled: false` if your cluster policy forbids that
permission.

**OrbStack gotcha:** OrbStack's kubelet exposes `/metrics/cadvisor` but
only emits `machine_*` metrics through it (no `container_*`). The container
data is reachable via `/stats/summary` but cAdvisor on that path is broken.
Other distributions (kind, minikube, EKS, GKE, AKS, k3d) work normally.
The dashboards expecting container metrics will be empty on OrbStack only.

### Metrics — mostly hardcoded static targets

For Prometheus metrics, the shipped Alloy config uses **static
`prometheus.scrape` blocks pointing at known Service:port endpoints**, not
annotation- or label-based auto-discovery. The default scrape list is:

| Job | Target | Source chart |
| --- | --- | --- |
| `prometheus` | `<obs-release>-prometheus-server:80` | self |
| `infrahub-server` | `<infrahub-release>-infrahub-server:8000` | infrahub |
| `infrahub-worker` | pods labelled `service=infrahub-task-worker`, port `8000` | infrahub |
| `message-queue` | `<infrahub-release>-message-queue:15692` | infrahub (RabbitMQ exporter) |
| `database` | `<infrahub-release>-database:2004` | infrahub (Neo4j metrics) |
| `task-manager-exporter` | `<obs-release>-infrahub-observability-prefect-exporter:8000` | this chart (Prefect exporter) |
| `task-manager` | `<infrahub-release>-task-manager-server:4200/api/metrics` | infrahub (Prefect server) |
| `logs` | `<obs-release>-loki:3100` and `<obs-release>-alloy:12345` | self |
| `node-exporter` | `<obs-release>-prometheus-node-exporter:9100` | self |

The only dynamic discovery on the metrics side is for **`infrahub-task-worker`**:
the task-worker has no Service in the infrahub chart, so Alloy uses
`discovery.kubernetes` with `role = "pod"` and a `keep` relabel filtering on
the pod's `service=infrahub-task-worker` label, then rewrites the port to
`8000`.

#### Annotation-based scrape — not currently consumed

The Prefect exporter Service the chart creates carries the conventional
`prometheus.io/scrape: "true"`, `prometheus.io/port`, `prometheus.io/path`
annotations. **The shipped Alloy config does not consume those annotations**
— the exporter is scraped via a static target block instead. The annotations
are decorative for now (useful if someone runs their own Prometheus alongside
that does honour them, but Alloy ignores them). If you want to enable
annotation-driven scrape across the whole namespace, you need to override the
Alloy config; see below.

Toggles:

| Setting | Effect |
| --- | --- |
| `prefectExporter.enabled` | Toggle the Prefect prometheus exporter Deployment + Service. Disable if you don't run Prefect / task-manager. |
| `prometheus-node-exporter.enabled` | Toggle the host-level metrics DaemonSet. |
| `prometheus.enabled` | Disable the in-cluster Prometheus TSDB entirely. Alloy will then have nowhere to remote-write metrics. |
| `global.infrahubReleaseName` | Used to resolve the `<infrahub-release>-*` Service names. Set this if your infrahub release isn't named `infrahub`. |

#### Adding or removing scrape targets

The Alloy config is shipped as a ConfigMap rendered from
[templates/alloy-config.yaml](../charts/infrahub-observability/templates/alloy-config.yaml).
The scrape list is part of that template — it isn't exposed as a Helm value.
If you need to add custom targets or switch to annotation-based discovery:

1. **Quick override** — disable the chart's ConfigMap and provide your own:

   ```yaml
   alloy:
     alloy:
       configMap:
         create: true   # let the Alloy subchart create + own the ConfigMap
         content: |-
           // ...your custom config.alloy...
   ```

2. **Fork the chart's ConfigMap** — copy the rendered `obs-alloy` ConfigMap,
   add your scrape blocks, and set
   `alloy.alloy.configMap.name=<your-name>` to point Alloy at it instead.

### Traces — opt-in, no discovery involved

Traces are not collected via discovery. Workloads have to actively push to
Tempo's OTLP endpoint. For infrahub this is wired via the new
`global.tracing.*` block on the infrahub chart (see Step 4 above). For
custom workloads, point your OTLP client at
`<obs-release>-tempo:4317` (gRPC) or `<obs-release>-tempo:4318` (HTTP).

Toggles:

| Setting | Effect |
| --- | --- |
| `tempo.enabled` | Disable Tempo. |
| `global.tracing.enabled` (on the **infrahub** chart) | Inject `INFRAHUB_TRACE_*` env vars on infrahub server + task-worker. Off by default. |
| `global.tracing.endpoint` / `.protocol` / `.insecure` (infrahub chart) | OTLP destination, transport, TLS skip. |

### Per-component on/off summary

If you only want a subset of the stack, the top-level subchart toggles let
you trim it down:

```yaml
alloy:
  enabled: false   # collector
loki:
  enabled: false   # log storage
tempo:
  enabled: false   # trace storage
prometheus:
  enabled: false   # metric storage
grafana:
  enabled: false   # UI
prometheus-node-exporter:
  enabled: false   # host metrics
prefectExporter:
  enabled: false   # Prefect metrics exporter
```

Most users keep all of these on. Disabling Grafana while keeping the rest is
the common pattern when you have an existing org-wide Grafana you want to
point at this stack's Loki/Prometheus/Tempo.

## Troubleshooting

**Grafana dashboards or datasources don't appear**

The sidecar watches all namespaces by default (`sidecar.dashboards.searchNamespace: ALL`).
Confirm the ConfigMaps exist with the right labels:

```sh
kubectl --namespace infrahub get configmap -l grafana_dashboard=1
kubectl --namespace infrahub get configmap -l grafana_datasource=1
```

Then check sidecar logs:

```sh
kubectl --namespace infrahub logs deploy/obs-grafana -c grafana-sc-dashboard
kubectl --namespace infrahub logs deploy/obs-grafana -c grafana-sc-datasources
```

**Alloy isn't sending data**

```sh
kubectl --namespace infrahub get pod -l app.kubernetes.io/name=alloy
kubectl --namespace infrahub logs ds/obs-alloy
```

The Alloy config comes from the `obs-alloy` ConfigMap (rendered by
[templates/alloy-config.yaml](../charts/infrahub-observability/templates/alloy-config.yaml)) —
inspect it with `kubectl get configmap obs-alloy -o yaml`.

**Tempo can't ingest traces**

Confirm the OTLP gRPC receiver is up:

```sh
kubectl --namespace infrahub port-forward svc/obs-tempo 4317:4317
# from another terminal, check the port is reachable:
nc -zv localhost 4317
```

And that infrahub-server has the trace env vars (Step 4 above).

**Pods are pending due to PVCs**

Your default StorageClass may not be provisioning. Check:

```sh
kubectl get pvc --namespace infrahub
kubectl describe pvc <pending-pvc-name> --namespace infrahub
```

Either install a default StorageClass (kind: `kubectl apply -f https://...local-path-provisioner.yaml`)
or disable persistence in the chart values for a one-off test:

```sh
helm install obs charts/infrahub-observability \
    --namespace infrahub \
    --set loki.singleBinary.persistence.enabled=false \
    --set tempo.persistence.enabled=false \
    --set prometheus.server.persistentVolume.enabled=false \
    --set grafana.persistence.enabled=false
```
