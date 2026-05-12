# Infrahub Observability Chart Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Finish the new `infrahub-observability` Helm chart so it deploys the same observability stack that upstream `opsmill/infrahub` ships for local Docker Compose dev (Alloy + Loki + Prometheus + Tempo + Grafana + Prefect exporter) onto Kubernetes alongside the existing `infrahub` / `infrahub-enterprise` charts.

**Architecture:**
- Subchart dependencies are already declared in [charts/infrahub-observability/Chart.yaml](../../charts/infrahub-observability/Chart.yaml).
- This chart's own templates supply: an Alloy `config.alloy` ConfigMap (so we can ship our pipelines instead of the subchart's auto-config), Grafana datasource and dashboard ConfigMaps consumed by Grafana's sidecar, and a Deployment+Service for `prefecthq/prometheus-prefect-exporter` (no upstream chart exists).
- URL/name helpers are already defined in [charts/infrahub-observability/templates/_helpers.tpl](../../charts/infrahub-observability/templates/_helpers.tpl) — reuse them (`infrahub-observability.prometheusRemoteWriteUrl`, `lokiPushUrl`, `tempoOtlpGrpcEndpoint`, `alloyConfigMapName`, `prefectExporterFullname`, `prefectApiUrl`).
- Label/annotation pattern to mirror: see [charts/infrahub/templates/infrahub-server.yaml](../../charts/infrahub/templates/infrahub-server.yaml) — top-level `service: <name>` label plus the chart's `labels` / `selectorLabels` / `annotations` helpers.

**Upstream source of truth** for Alloy config and Grafana provisioning files: `opsmill/infrahub` repo at ref `infrahub-v1.9.3` (matches [.dashboards-source](../../charts/infrahub-observability/.dashboards-source) and `Chart.yaml`'s `appVersion`). Likely paths:
- `development/alloy/config.alloy` (Alloy pipelines)
- `development/grafana/provisioning/datasources/datasources.yaml` (Grafana datasources)
- `development/grafana/provisioning/dashboards/` (already vendored)

Verify exact paths with: `gh api repos/opsmill/infrahub/contents/development?ref=infrahub-v1.9.3 --jq '.[].name'`

**Tech Stack:** Helm 3, Grafana Alloy 1.0.3, Loki 6.16.0, Tempo 1.10.0, Grafana 8.5.0, Prometheus 25.27.0, prometheus-node-exporter 4.36.0.

**Branch state at plan time:** `feat/infrahub-observability-chart` has no commits yet — everything under [charts/infrahub-observability/](../../charts/infrahub-observability/), [scripts/](../../scripts/), [Makefile](../../Makefile), and `docs/` is untracked. Commit incrementally per task.

---

### Task 1: Add Alloy `config.alloy` ConfigMap

**Files:**
- Create: `charts/infrahub-observability/templates/alloy-config.yaml`

**Step 1: Fetch the upstream Alloy config**

```bash
gh api repos/opsmill/infrahub/contents/development/alloy/config.alloy?ref=infrahub-v1.9.3 \
    --jq '.content' | base64 -d > /tmp/upstream-config.alloy
```

If the path differs, list candidates: `gh api repos/opsmill/infrahub/contents/development?ref=infrahub-v1.9.3 --jq '.[].name'`.

**Step 2: Adapt the config for Kubernetes**

In the upstream Docker Compose config, endpoints are container names like `loki:3100`. For Kubernetes, rewrite endpoints using the helpers so they resolve to the right Service:
- Prometheus remote_write URL → `{{ include "infrahub-observability.prometheusRemoteWriteUrl" . }}`
- Loki push URL → `{{ include "infrahub-observability.lokiPushUrl" . }}`
- Tempo OTLP gRPC → `{{ include "infrahub-observability.tempoOtlpGrpcEndpoint" . }}`

Log-discovery and pod-scrape blocks should use `discovery.kubernetes` (component name varies by Alloy version — confirm with the Alloy 1.0.3 reference) instead of the Docker container discovery used upstream. Scope discovery to `{{ include "infrahub-observability.infrahubNamespace" . }}` so we only collect from the sibling infrahub release.

**Step 3: Write the ConfigMap template**

```yaml
{{- if .Values.alloy.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "infrahub-observability.alloyConfigMapName" . }}
  namespace: {{ .Release.Namespace | quote }}
  labels:
    service: alloy
    {{- include "infrahub-observability.labels" . | nindent 4 }}
  annotations:
    {{- include "infrahub-observability.annotations" . | nindent 4 }}
data:
  config.alloy: |-
    {{- /* adapted config goes here, indented 4 */ -}}
{{- end }}
```

Note: `values.yaml` already sets `alloy.alloy.configMap.create: false` and `alloy.alloy.configMap.key: config.alloy`. We also need to set `alloy.alloy.configMap.name` to the rendered helper value — do this in [charts/infrahub-observability/values.yaml](../../charts/infrahub-observability/values.yaml) by changing the `name: ""` line (currently L42) to a templated reference. The Alloy subchart resolves a `name: ""` by trying to render it as a template, so emit:

```yaml
    name: '{{ printf "%s-alloy" (include "infrahub-observability.fullname" .) }}'
```

(Confirm this against the Alloy subchart's `_helpers.tpl` — if it doesn't template the `name` field, document this in `NOTES.txt` and require users to pass `alloy.alloy.configMap.name` explicitly, OR switch to providing the config via `alloy.configMap.content`.)

**Step 4: Validate**

```bash
make deps-observability
helm template test charts/infrahub-observability | yq 'select(.kind == "ConfigMap" and (.metadata.name | test("alloy")))'
```

Expected: the ConfigMap renders with a non-empty `config.alloy` key and the Alloy DaemonSet mounts it.

**Step 5: Commit**

```bash
git add charts/infrahub-observability/templates/alloy-config.yaml charts/infrahub-observability/values.yaml
git commit -m "feat(observability): ship Alloy config.alloy as ConfigMap"
```

---

### Task 2: Add Grafana datasources ConfigMap

**Files:**
- Create: `charts/infrahub-observability/templates/grafana-datasources.yaml`

**Step 1: Fetch the upstream Grafana datasources config**

```bash
gh api repos/opsmill/infrahub/contents/development/grafana/provisioning/datasources?ref=infrahub-v1.9.3 --jq '.[].name'
gh api repos/opsmill/infrahub/contents/development/grafana/provisioning/datasources/datasources.yaml?ref=infrahub-v1.9.3 \
    --jq '.content' | base64 -d > /tmp/upstream-datasources.yaml
```

**Step 2: Write the ConfigMap, rewriting URLs via helpers**

Replace upstream `http://prometheus:9090` / `http://loki:3100` / `http://tempo:3200` with the helpers. The sidecar (already enabled at [values.yaml:192-196](../../charts/infrahub-observability/values.yaml#L192-L196) with label `grafana_datasource: "1"`) auto-loads any ConfigMap with that label.

```yaml
{{- if .Values.grafana.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "infrahub-observability.fullname" . }}-grafana-datasources
  namespace: {{ .Release.Namespace | quote }}
  labels:
    grafana_datasource: "1"
    service: grafana
    {{- include "infrahub-observability.labels" . | nindent 4 }}
  annotations:
    {{- include "infrahub-observability.annotations" . | nindent 4 }}
data:
  datasources.yaml: |-
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: {{ include "infrahub-observability.prometheusUrl" . }}
        isDefault: true
        jsonData:
          httpMethod: POST
          timeInterval: 30s
      - name: Loki
        type: loki
        access: proxy
        url: {{ include "infrahub-observability.lokiUrl" . }}
        jsonData:
          maxLines: 1000
      - name: Tempo
        type: tempo
        access: proxy
        url: {{ include "infrahub-observability.tempoUrl" . }}
        jsonData:
          tracesToLogsV2:
            datasourceUid: loki
{{- end }}
```

Cross-check the `jsonData` blocks against the upstream `datasources.yaml` and bring over anything we're missing (UID-based linking between Tempo and Loki, exemplar config, etc.).

**Step 3: Validate**

```bash
helm template test charts/infrahub-observability | yq 'select(.kind == "ConfigMap" and (.metadata.labels.grafana_datasource? == "1"))'
```

Expected: one ConfigMap with three datasources.

**Step 4: Commit**

```bash
git add charts/infrahub-observability/templates/grafana-datasources.yaml
git commit -m "feat(observability): provision Grafana datasources via sidecar ConfigMap"
```

---

### Task 3: Add Grafana dashboard ConfigMaps (one per dashboard)

**Files:**
- Create: `charts/infrahub-observability/templates/grafana-dashboards.yaml`

**Why one ConfigMap per dashboard:** etcd's hard limit on a single ConfigMap is 1 MiB. The vendored JSONs total ~917 KB and [dashboards/loki_monitoring.json](../../charts/infrahub-observability/dashboards/loki_monitoring.json) alone is 389 KB — bundling all seven into a single ConfigMap would risk hitting the limit and breaking installs. Iterating with `Files.Glob` produces one ConfigMap per file.

**Step 1: Write the template**

```yaml
{{- if .Values.grafana.enabled }}
{{- $root := . }}
{{- range $path, $_ := .Files.Glob "dashboards/*.json" }}
{{- $name := base $path | trimSuffix ".json" }}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "infrahub-observability.fullname" $root }}-dashboard-{{ $name | replace "_" "-" }}
  namespace: {{ $root.Release.Namespace | quote }}
  labels:
    grafana_dashboard: "1"
    service: grafana
    {{- include "infrahub-observability.labels" $root | nindent 4 }}
  annotations:
    {{- include "infrahub-observability.annotations" $root | nindent 4 }}
data:
  {{ base $path }}: |-
    {{- $root.Files.Get $path | nindent 4 }}
{{- end }}
{{- end }}
```

**Step 2: Validate**

```bash
helm template test charts/infrahub-observability | yq 'select(.kind == "ConfigMap" and (.metadata.labels.grafana_dashboard? == "1")) | .metadata.name'
```

Expected: 7 ConfigMap names (one per file in [dashboards/](../../charts/infrahub-observability/dashboards/)). Also confirm each rendered ConfigMap stays under 1 MiB:

```bash
helm template test charts/infrahub-observability \
  | yq 'select(.kind == "ConfigMap" and (.metadata.labels.grafana_dashboard? == "1")) | [.metadata.name, (.data | to_entries | .[0].value | length)] | @tsv'
```

**Step 3: Commit**

```bash
git add charts/infrahub-observability/templates/grafana-dashboards.yaml
git commit -m "feat(observability): provision vendored Grafana dashboards via sidecar ConfigMaps"
```

---

### Task 4: Add Prefect exporter Deployment

**Files:**
- Create: `charts/infrahub-observability/templates/prefect-exporter-deployment.yaml`

**Step 1: Write the template**

Mirror the pattern from [charts/infrahub/templates/infrahub-server.yaml](../../charts/infrahub/templates/infrahub-server.yaml) (top-level `service:` label + chart helpers). Image/log-level/replicas/probes come from `values.yaml`. The exporter listens on `:8000` by default and exposes `/metrics`.

```yaml
{{- if .Values.prefectExporter.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "infrahub-observability.prefectExporterFullname" . }}
  namespace: {{ .Release.Namespace | quote }}
  labels:
    service: prefect-exporter
    {{- include "infrahub-observability.labels" . | nindent 4 }}
  annotations:
    {{- include "infrahub-observability.annotations" . | nindent 4 }}
spec:
  replicas: {{ .Values.prefectExporter.replicas }}
  selector:
    matchLabels:
      service: prefect-exporter
      {{- include "infrahub-observability.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        service: prefect-exporter
        {{- include "infrahub-observability.selectorLabels" . | nindent 8 }}
      {{- with .Values.prefectExporter.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    spec:
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets: {{- toYaml . | nindent 8 }}
      {{- end }}
      securityContext:
        {{- toYaml .Values.prefectExporter.securityContext | nindent 8 }}
      containers:
        - name: prefect-exporter
          image: "{{ .Values.prefectExporter.image.repository }}:{{ .Values.prefectExporter.image.tag }}"
          imagePullPolicy: {{ default .Values.global.imagePullPolicy .Values.prefectExporter.image.pullPolicy }}
          env:
            - name: PREFECT_API_URL
              value: {{ include "infrahub-observability.prefectApiUrl" . | quote }}
            - name: LOG_LEVEL
              value: {{ .Values.prefectExporter.logLevel | quote }}
          ports:
            - name: metrics
              containerPort: 8000
              protocol: TCP
          readinessProbe:
            httpGet:
              path: /metrics
              port: metrics
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            {{- toYaml .Values.prefectExporter.resources | nindent 12 }}
      {{- with .Values.prefectExporter.nodeSelector }}
      nodeSelector: {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.prefectExporter.tolerations }}
      tolerations: {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.prefectExporter.affinity }}
      affinity: {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
```

Verify the actual env-var names against the `prefecthq/prometheus-prefect-exporter` image docs at `docker.io/prefecthq/prometheus-prefect-exporter` (README on Docker Hub) before committing — `PREFECT_API_URL` and `LOG_LEVEL` are the documented names as of v3.x but confirm.

**Step 2: Validate**

```bash
helm template test charts/infrahub-observability | yq 'select(.kind == "Deployment" and (.metadata.name | test("prefect-exporter")))'
```

Expected: Deployment with PREFECT_API_URL pointing at `http://infrahub-task-manager-server:4200/api`.

**Step 3: Commit**

```bash
git add charts/infrahub-observability/templates/prefect-exporter-deployment.yaml
git commit -m "feat(observability): add Prefect prometheus exporter Deployment"
```

---

### Task 5: Add Prefect exporter Service

**Files:**
- Create: `charts/infrahub-observability/templates/prefect-exporter-service.yaml`

**Step 1: Write the template**

Annotate with `prometheus.io/scrape: "true"` so Alloy's annotation-based service discovery picks it up automatically.

```yaml
{{- if .Values.prefectExporter.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "infrahub-observability.prefectExporterFullname" . }}
  namespace: {{ .Release.Namespace | quote }}
  labels:
    service: prefect-exporter
    {{- include "infrahub-observability.labels" . | nindent 4 }}
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: {{ .Values.prefectExporter.service.port | quote }}
    prometheus.io/path: "/metrics"
    {{- include "infrahub-observability.annotations" . | nindent 4 }}
spec:
  type: {{ .Values.prefectExporter.service.type }}
  ports:
    - name: metrics
      port: {{ .Values.prefectExporter.service.port }}
      targetPort: metrics
      protocol: TCP
  selector:
    service: prefect-exporter
    {{- include "infrahub-observability.selectorLabels" . | nindent 4 }}
{{- end }}
```

**Step 2: Validate**

```bash
helm template test charts/infrahub-observability | yq 'select(.kind == "Service" and (.metadata.name | test("prefect-exporter")))'
```

Expected: Service on port 8000, selector matches the Deployment from Task 4.

**Step 3: Commit**

```bash
git add charts/infrahub-observability/templates/prefect-exporter-service.yaml
git commit -m "feat(observability): expose Prefect exporter via Service with scrape annotations"
```

---

### Task 6: Add `NOTES.txt`

**Files:**
- Create: `charts/infrahub-observability/templates/NOTES.txt`

**Step 1: Write install notes**

Cover the top three questions a user will have after `helm install`:

1. How to port-forward Grafana (`kubectl port-forward svc/{{ .Release.Name }}-grafana 3000:80`) and the default admin password (look up via `kubectl get secret`).
2. How to point the sibling infrahub release at this Tempo (the `global.tracing.endpoint` snippet from [README.md.gotmpl:32-41](../../charts/infrahub-observability/README.md.gotmpl#L32-L41)).
3. The OTLP gRPC endpoint, Prometheus remote-write URL, and Loki push URL — render via the helpers so the user gets the exact in-cluster DNS name for their release.

Keep it under ~40 lines. Use `printf` / helper expressions for any release-name-dependent strings.

**Step 2: Validate**

```bash
helm install --dry-run test charts/infrahub-observability | sed -n '/^NOTES:/,$p'
```

Expected: notes render with the actual release name substituted.

**Step 3: Commit**

```bash
git add charts/infrahub-observability/templates/NOTES.txt
git commit -m "feat(observability): add post-install NOTES with port-forward and wiring tips"
```

---

### Task 7: Add `global.tracing` to the infrahub chart (cross-chart)

**Why this lives in the infrahub chart, not the observability chart:** the env vars need to land on the infrahub server and task-worker pods. The observability chart only provides the collector — it can't reach across releases to inject env on someone else's Deployment. So we add a single `global.tracing` block to the infrahub chart that emits the OTEL/INFRAHUB_TRACE env vars to both workloads. Defaults to `enabled: false` so existing users without an OTLP collector aren't affected; observability users flip one flag.

**Files:**
- Modify: [charts/infrahub/values.yaml](../../charts/infrahub/values.yaml)
- Modify: [charts/infrahub/templates/_env.tpl](../../charts/infrahub/templates/_env.tpl)
- Modify: [charts/infrahub/templates/infrahub-server.yaml](../../charts/infrahub/templates/infrahub-server.yaml)
- Modify: [charts/infrahub/templates/infrahub-task-worker.yaml](../../charts/infrahub/templates/infrahub-task-worker.yaml)
- Possibly modify: [charts/infrahub-enterprise/values.yaml](../../charts/infrahub-enterprise/values.yaml) and any preset values files (only if they shadow `global:`)
- Modify: [charts/infrahub-observability/README.md.gotmpl](../../charts/infrahub-observability/README.md.gotmpl) so the wiring snippet matches reality

**Step 1: Verify the exact env-var names against upstream**

The README.md.gotmpl currently uses placeholder names. Look up what `opsmill/infrahub@infrahub-v1.9.3` actually reads:

```bash
# Search the upstream Python codebase for the env vars it consumes
gh search code --repo opsmill/infrahub --filename "*.py" "INFRAHUB_TRACE"
gh search code --repo opsmill/infrahub --filename "*.py" "OTEL_EXPORTER_OTLP_ENDPOINT"
# Also check the Docker Compose dev setup for the names it sets:
gh api repos/opsmill/infrahub/contents/development?ref=infrahub-v1.9.3 --jq '.[] | select(.name | test("compose|env")) | .name'
```

Capture the *exact* names — likely `INFRAHUB_TRACE_ENABLED`, `INFRAHUB_TRACE_EXPORTER_PROTOCOL`, `INFRAHUB_TRACE_EXPORTER_ENDPOINT`, `INFRAHUB_TRACE_INSECURE`, but **do not assume** — use whatever the upstream code actually reads. If both `INFRAHUB_TRACE_*` and `OTEL_*` are needed, emit both.

**Step 2: Add `global.tracing` to `charts/infrahub/values.yaml`**

Add to the `global:` block at [charts/infrahub/values.yaml:2-16](../../charts/infrahub/values.yaml#L2-L16):

```yaml
  # -- Send traces to an OTLP collector. When enabled, OTEL/Infrahub trace env
  # vars are injected into the server and task-worker Deployments. Pair with
  # the infrahub-observability chart (Tempo endpoint: <obs-release>-tempo:4317)
  # or any other OTLP-compatible collector.
  tracing:
    # -- Enable tracing instrumentation on server and task-worker pods.
    enabled: false
    # -- OTLP endpoint. For grpc protocol, use host:port (no scheme).
    # For http/protobuf, use a full URL. Example: "obs-tempo:4317".
    endpoint: ""
    # -- OTLP protocol. One of: grpc, http/protobuf.
    protocol: grpc
    # -- Skip TLS verification when talking to the collector.
    insecure: true
```

Keep `enabled: false`. Leave the block uncommented so it shows up in helm-docs and is one `--set` away.

**Step 3: Add a `tracingEnv` helper to `_env.tpl`**

In [charts/infrahub/templates/_env.tpl](../../charts/infrahub/templates/_env.tpl), add a reusable define near the bottom:

```gotmpl
{{/*
Tracing env vars emitted onto server and task-worker pods when
.Values.global.tracing.enabled is true. Use the exact env-var names
confirmed in Step 1.
*/}}
{{- define "infrahub-helm.tracingEnv" -}}
{{- if .Values.global.tracing.enabled }}
- name: INFRAHUB_TRACE_ENABLED
  value: "true"
- name: INFRAHUB_TRACE_EXPORTER_PROTOCOL
  value: {{ .Values.global.tracing.protocol | quote }}
- name: INFRAHUB_TRACE_EXPORTER_ENDPOINT
  value: {{ .Values.global.tracing.endpoint | quote }}
- name: INFRAHUB_TRACE_INSECURE
  value: {{ .Values.global.tracing.insecure | quote }}
{{- end }}
{{- end }}
```

Adjust names to whatever Step 1 turned up. If upstream also reads stock OTEL SDK vars, emit those alongside (e.g., `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_SERVICE_NAME` set to the workload name).

**Step 4: Include the helper in server + task-worker templates**

Find the `env:` block in [infrahub-server.yaml](../../charts/infrahub/templates/infrahub-server.yaml) (around L120) and append the helper output after the existing default env:

```gotmpl
          env:
            {{- include "infrahub-helm.infrahubServer.defaultEnv" . | nindent 12 }}
            {{- include "infrahub-helm.tracingEnv" . | nindent 12 }}
            {{- range $key, $value := .Values.infrahubServer.infrahubServer.env }}
            - name: {{ $key }}
              value: {{ $value | quote }}
            {{- end }}
```

Do the same in [infrahub-task-worker.yaml](../../charts/infrahub/templates/infrahub-task-worker.yaml). The existing user-supplied `env:` map should still take precedence — keep it last so a user can override a tracing var explicitly if needed.

**Step 5: Update the observability chart README to point at the real keys**

Replace the snippet at [charts/infrahub-observability/README.md.gotmpl:30-41](../../charts/infrahub-observability/README.md.gotmpl#L30-L41) so it reflects the actual key shape and uses `host:port` for the grpc endpoint:

```yaml
# infrahub values
global:
  tracing:
    enabled: true
    endpoint: "obs-tempo:4317"   # <obs-release-name>-tempo:4317
    protocol: grpc
    insecure: true
```

**Step 6: Add the one-liner to the observability NOTES.txt (from Task 6)**

When Task 6 is being executed, include a section like:

```
2. Send traces from infrahub to this stack:

     helm upgrade {{ .Values.global.infrahubReleaseName }} ./charts/infrahub \
         --reuse-values \
         --set global.tracing.enabled=true \
         --set global.tracing.endpoint={{ include "infrahub-observability.tempoOtlpGrpcEndpoint" . }}
```

This is the entire "wiring" step from the user's perspective. If Task 6 has already been committed, treat this as an amendment to NOTES.txt in this task.

**Step 7: Validate**

```bash
# Render with tracing off — no INFRAHUB_TRACE_* vars on server or task-worker
helm template test charts/infrahub | yq 'select(.kind == "Deployment") | .spec.template.spec.containers[0].env' | grep -i trace || echo "OK: no tracing env"

# Render with tracing on — vars appear on both deployments
helm template test charts/infrahub \
    --set global.tracing.enabled=true \
    --set global.tracing.endpoint=obs-tempo:4317 \
  | yq 'select(.kind == "Deployment") | {(.metadata.name): [.spec.template.spec.containers[0].env[] | select(.name | test("TRACE|OTEL"))]}'

# Re-lint both base + enterprise (enterprise inherits the global block)
helm lint charts/infrahub
helm lint charts/infrahub-enterprise
```

Expected: both `infrahub-server` and `infrahub-task-worker` Deployments emit the trace env vars when enabled; both lints clean.

**Step 8: Commit**

```bash
git add charts/infrahub/values.yaml \
        charts/infrahub/templates/_env.tpl \
        charts/infrahub/templates/infrahub-server.yaml \
        charts/infrahub/templates/infrahub-task-worker.yaml \
        charts/infrahub-observability/README.md.gotmpl \
        charts/infrahub-observability/templates/NOTES.txt
git commit -m "feat(infrahub): add global.tracing for OTLP collector wiring

Adds an opt-in global.tracing block on the infrahub chart that emits
INFRAHUB_TRACE_* (and OTEL_*) env vars onto the server and task-worker
Deployments. Defaults to disabled so existing users are unaffected;
users of the new infrahub-observability chart can flip it on with one
flag and point at the chart's Tempo endpoint."
```

---

### Task 8: Wire the chart into CI

**Files:**
- Modify: [.github/workflows/ci.yml](../../.github/workflows/ci.yml)

**Step 1: Add lint step**

After the existing `Linting: helm lint infrahub enterprise` step at [.github/workflows/ci.yml:31-32](../../.github/workflows/ci.yml#L31-L32), append:

```yaml
      - name: "Updating dependencies: infrahub-observability"
        run: "helm dependency update charts/infrahub-observability"
      - name: "Linting: helm lint infrahub-observability"
        run: "helm lint charts/infrahub-observability"
```

**Step 2: Validate**

```bash
yamllint .github/workflows/ci.yml
make lint
```

Expected: yamllint passes, `make lint` succeeds for all three charts.

**Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint infrahub-observability chart in CI"
```

---

### Task 9: Render `README.md` from gotmpl + final end-to-end verification

**Files:**
- Create: `charts/infrahub-observability/README.md` (generated)

**Step 1: Render README via helm-docs**

```bash
# https://github.com/norwoodj/helm-docs
helm-docs --chart-search-root=charts/infrahub-observability
```

If `helm-docs` isn't installed, document the command in `Makefile` and skip the actual render until CI handles it. Check whether the other charts have a committed `README.md` — if so, follow that convention; if not, leave it gotmpl-only.

**Step 2: Final end-to-end checks**

```bash
make deps-observability
make lint-observability
make template-observability > /tmp/rendered.yaml
# Spot-check: every Kubernetes object renders, no template errors
yq '.kind' /tmp/rendered.yaml | sort | uniq -c
# Spot-check: no dashboard ConfigMap exceeds 1 MiB
yq 'select(.kind == "ConfigMap" and (.metadata.labels.grafana_dashboard? == "1")) | [.metadata.name, (.data | to_entries | .[0].value | length)] | @tsv' /tmp/rendered.yaml
# Optional: dry-run install against a kind cluster if available
helm install --dry-run --debug test charts/infrahub-observability > /dev/null
```

Expected: zero `helm lint` errors, all helpers resolve, dashboard ConfigMap sizes well under 1048576.

**Step 3: Commit**

```bash
git add charts/infrahub-observability/README.md  # if generated
git commit -m "docs(observability): render README from gotmpl"
```

---

### Task 10: Open the PR

**Step 1: Push and open PR**

```bash
git push -u origin feat/infrahub-observability-chart
gh pr create --base stable --title "feat: add infrahub-observability chart" --body "$(cat <<'EOF'
## Summary
- New `infrahub-observability` Helm chart bundling Alloy + Loki + Tempo + Prometheus + Grafana + Prefect exporter for Kubernetes installs.
- Vendors seven Grafana dashboards from `opsmill/infrahub@infrahub-v1.9.3` via [scripts/sync-dashboards.sh](../../scripts/sync-dashboards.sh).
- Provisions Grafana datasources and dashboards via sidecar ConfigMaps; ships an in-chart Deployment+Service for the Prefect prometheus exporter (no upstream chart exists).
- Adds an opt-in `global.tracing` block to the infrahub chart so users can wire OTLP/INFRAHUB_TRACE env vars onto server + task-worker with a single flag.
- CI now lints all three charts.

## Test plan
- [ ] `make lint` passes locally
- [ ] `helm template test charts/infrahub-observability` renders without errors
- [ ] All dashboard ConfigMaps stay under 1 MiB
- [ ] Manual install into a kind cluster shows Grafana with all three datasources reachable and all dashboards visible
- [ ] Wire infrahub `global.tracing.endpoint` at the chart's Tempo and confirm traces appear
EOF
)"
```

**Step 2: Verify**

```bash
gh pr view --web
```

---

## Known unknowns to investigate during execution

- **Alloy subchart `configMap.name` templating:** confirm whether the Alloy 1.0.3 subchart renders `alloy.alloy.configMap.name` as a template (Task 1 Step 3). If not, switch strategy.
- **Upstream `development/` paths:** Task 1 and Task 2 both assume specific paths under `opsmill/infrahub@infrahub-v1.9.3` — verify with `gh api` before fetching.
- **Prefect exporter env-var names:** Task 4 assumes `PREFECT_API_URL` and `LOG_LEVEL` — confirm against the image docs.
- **Infrahub tracing env-var names:** Task 7 assumes `INFRAHUB_TRACE_*` — confirm the exact names (and whether stock `OTEL_*` SDK vars are also needed) by searching the upstream infrahub Python source at ref `infrahub-v1.9.3` before writing the helper.
- **helm-docs availability:** Task 9 assumes `helm-docs` is installable; if not, leave README rendering for a follow-up.
