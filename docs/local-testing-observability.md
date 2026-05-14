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

You should see (eventually) `infrahub-infrahub-server`,
`infrahub-infrahub-task-worker`, `infrahub-database-0` (Neo4j),
`infrahub-cache-master-0` (Redis), `infrahub-rabbitmq-0`, and
`infrahub-task-manager-*` pods all `Running` and `1/1` ready.

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

In **Explore**, pick the **Prometheus** datasource, and run:

```promql
up{}
```

You should see at least the Prometheus self-scrape and Alloy targets.
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
# in a separate terminal, hit the GraphQL endpoint a few times
curl -s http://localhost:8000/api/schema/summary > /dev/null
curl -s http://localhost:8000/api/storage/object/about > /dev/null
```

In Grafana, **Explore** → **Tempo** → **Search**, set Service Name to
`infrahub-server`, and click **Run query**. You should see traces appear
within a minute.

## 6. (Optional) Teardown

```sh
helm uninstall obs --namespace infrahub
helm uninstall infrahub --namespace infrahub

# Persistent volumes for Loki/Prometheus/Tempo/Grafana/Neo4j are NOT
# deleted with the releases. Remove them too if you want a clean slate:
kubectl --namespace infrahub delete pvc --all

kubectl delete namespace infrahub
```

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
