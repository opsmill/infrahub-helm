{{/*
Expand the name of the chart.
*/}}
{{- define "infrahub-observability.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "infrahub-observability.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "infrahub-observability.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "infrahub-observability.labels" -}}
helm.sh/chart: {{ include "infrahub-observability.chart" . }}
{{ include "infrahub-observability.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if gt (len .Values.global.commonLabels) 0 }}
{{ .Values.global.commonLabels | toYaml }}
{{- end }}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "infrahub-observability.annotations" -}}
{{- if gt (len .Values.global.commonAnnotations) 0 -}}
{{ .Values.global.commonAnnotations | toYaml }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "infrahub-observability.selectorLabels" -}}
app.kubernetes.io/name: {{ include "infrahub-observability.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if gt (len .Values.global.podLabels) 0 }}
{{ .Values.global.podLabels | toYaml }}
{{- end }}
{{- end }}

{{/*
Namespace where the sibling infrahub release lives. Defaults to the release namespace.
*/}}
{{- define "infrahub-observability.infrahubNamespace" -}}
{{- default .Release.Namespace .Values.global.infrahubNamespace -}}
{{- end }}

{{/*
Service URL helpers — derived from the release name and the conventions of each
upstream sub-chart. Sub-chart service names follow `<release>-<chart>` for grafana,
loki, tempo, alloy, node-exporter; `<release>-prometheus-server` for prometheus.
*/}}
{{- define "infrahub-observability.prometheusUrl" -}}
http://{{ .Release.Name }}-prometheus-server
{{- end }}

{{- define "infrahub-observability.prometheusRemoteWriteUrl" -}}
{{ include "infrahub-observability.prometheusUrl" . }}/api/v1/write
{{- end }}

{{- define "infrahub-observability.lokiUrl" -}}
http://{{ .Release.Name }}-loki:3100
{{- end }}

{{- define "infrahub-observability.lokiPushUrl" -}}
{{ include "infrahub-observability.lokiUrl" . }}/loki/api/v1/push
{{- end }}

{{- define "infrahub-observability.tempoUrl" -}}
http://{{ .Release.Name }}-tempo:3100
{{- end }}

{{- define "infrahub-observability.tempoOtlpGrpcEndpoint" -}}
{{ .Release.Name }}-tempo:4317
{{- end }}

{{/*
ConfigMap that holds Alloy's config.alloy. Must match what the Alloy subchart
resolves to when `alloy.alloy.configMap.name` is empty (see Alloy chart
templates/_config.tpl → `alloy.fullname`). Mirroring its logic here lets us
leave `configMap.name` unset in values.yaml.
*/}}
{{- define "infrahub-observability.alloyConfigMapName" -}}
{{- if contains "alloy" .Release.Name -}}
{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{ printf "%s-alloy" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- end }}

{{- define "infrahub-observability.prefectExporterFullname" -}}
{{ include "infrahub-observability.fullname" . }}-prefect-exporter
{{- end }}

{{/*
Default Prefect API URL. The infrahub chart embeds prefect-server as a
subchart whose Service is fixed-named "prefect-server" (not release-prefixed)
and the infrahub chart hard-codes PREFECT_API_URL accordingly. Users can
override via .Values.prefectExporter.prefectApiUrl.
*/}}
{{- define "infrahub-observability.prefectApiUrl" -}}
{{- if .Values.prefectExporter.prefectApiUrl -}}
{{ .Values.prefectExporter.prefectApiUrl }}
{{- else -}}
http://prefect-server:4200/api
{{- end -}}
{{- end }}

{{/*
Grafana MCP server. Names are cut so that the longest one, the Job name, stays
under the 63 characters that Kubernetes allows.
*/}}
{{- define "infrahub-observability.grafanaMcpFullname" -}}
{{ include "infrahub-observability.fullname" . | trunc 45 | trimSuffix "-" }}-grafana-mcp
{{- end }}

{{/*
Name of the Service of the grafana sub-chart. It follows the fullname logic of
the sub-chart: the release name when it contains "grafana", else <release>-grafana.
*/}}
{{- define "infrahub-observability.grafanaFullname" -}}
{{- if .Values.grafana.fullnameOverride -}}
{{ .Values.grafana.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{- $name := default "grafana" .Values.grafana.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Name of the Secret that holds the Grafana token. The hook Job writes it and the server pod
mounts it, so both read it from one place: the volume named "grafana-token" in the values of
the grafana-mcp dependency. A volume list cannot be templated, so the name is a fixed string.
Empty when the volume is missing.
*/}}
{{- define "infrahub-observability.grafanaMcpGrafanaTokenSecret" -}}
{{- $name := "" -}}
{{- range ((index .Values "grafana-mcp").volumes | default list) -}}
{{- if and (eq (.name | toString) "grafana-token") .secret -}}
{{- $name = (.secret.secretName | default "" | toString) -}}
{{- end -}}
{{- end -}}
{{- $name -}}
{{- end }}

{{/*
Address of the Grafana Service of this release, in the form of the default value of
grafana-mcp.grafana.url.
*/}}
{{- define "infrahub-observability.grafanaServiceUrl" -}}
{{- $port := int (default 80 (.Values.grafana.service).port) -}}
http://{{ include "infrahub-observability.grafanaFullname" . }}{{ if ne $port 80 }}:{{ $port }}{{ end }}
{{- end }}

{{/*
Checks of the Grafana MCP server. Fails the render when a setting would leave the server
open, writable or unable to reach Grafana.
*/}}
{{- define "infrahub-observability.grafanaMcpValidate" -}}
{{- $m := index .Values "grafana-mcp" -}}
{{- $auth := $m.serverAuth | default dict -}}
{{- $tokenSecret := $auth.tokenSecret | default dict -}}
{{- if not (or $auth.token $tokenSecret.name) -}}
{{- fail "grafana-mcp.serverAuth.token or grafana-mcp.serverAuth.tokenSecret.name is required" -}}
{{- end -}}
{{- if and $tokenSecret.name (not $tokenSecret.key) -}}
{{- fail "grafana-mcp.serverAuth.tokenSecret.key is required with grafana-mcp.serverAuth.tokenSecret.name" -}}
{{- end -}}
{{- $args := list -}}
{{- if $m.disableWrite -}}
{{- $args = append $args "--disable-write" -}}
{{- end -}}
{{- range ($m.disabledCategories | default list) -}}
{{- $args = append $args (printf "--disable-%s" (. | toString)) -}}
{{- end -}}
{{- range ($m.extraArgs | default list) -}}
{{- $arg := toString . -}}
{{- if regexMatch "^--disable-(write|api|docs|plugin)=(false|0)$" $arg -}}
{{- fail (printf "grafana-mcp.extraArgs has %s, which turns a read-only flag off" $arg) -}}
{{- end -}}
{{- $args = append $args $arg -}}
{{- end -}}
{{- range list "--disable-write" "--disable-api" "--disable-docs" "--disable-plugin" -}}
{{- if not (has . $args) -}}
{{- fail (printf "grafana-mcp must pass %s, so that the server has no tool that writes: keep grafana-mcp.disableWrite true and api, docs and plugin in grafana-mcp.disabledCategories" .) -}}
{{- end -}}
{{- end -}}
{{- $tls := false -}}
{{- range ($m.extraArgs | default list) -}}
{{- if hasPrefix "--server.tls-cert-file" (toString .) -}}
{{- $tls = true -}}
{{- end -}}
{{- end -}}
{{- $type := ($m.service | default dict).type | default "ClusterIP" -}}
{{- if and (ne $type "ClusterIP") (not $tls) -}}
{{- fail (printf "grafana-mcp.service.type is %s, which is open to a network: serve HTTPS with --server.tls-cert-file and --server.tls-key-file in grafana-mcp.extraArgs" $type) -}}
{{- end -}}
{{- if not (include "infrahub-observability.grafanaMcpGrafanaTokenSecret" .) -}}
{{- fail "grafana-mcp.volumes must have a volume named grafana-token with a secret.secretName: the hook Job writes the Grafana token to that Secret" -}}
{{- end -}}
{{- $url := ($m.grafana | default dict).url | default "" -}}
{{- if not $url -}}
{{- fail "grafana-mcp.grafana.url is required" -}}
{{- end -}}
{{- if eq $url "http://obs-grafana" -}}
{{- if not .Values.grafana.enabled -}}
{{- fail "grafana-mcp.grafana.url is required when grafana.enabled is false: set the address of your Grafana" -}}
{{- end -}}
{{- if ne (include "infrahub-observability.grafanaServiceUrl" .) $url -}}
{{- fail (printf "grafana-mcp.grafana.url is the default for a release named obs, and this release is named %s: set it to %s" .Release.Name (include "infrahub-observability.grafanaServiceUrl" .)) -}}
{{- end -}}
{{- end -}}
{{- end }}
