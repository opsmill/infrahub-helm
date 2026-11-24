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
Name of the Secret that the hook Job writes with the Grafana token.
*/}}
{{- define "infrahub-observability.grafanaMcpGrafanaTokenSecret" -}}
{{ include "infrahub-observability.grafanaMcpFullname" . }}-grafana-token
{{- end }}

{{/*
Name of the Secret with the token that AI assistants send.
*/}}
{{- define "infrahub-observability.grafanaMcpServerTokenSecret" -}}
{{- if .Values.grafanaMcp.serverToken.existingSecret -}}
{{ .Values.grafanaMcp.serverToken.existingSecret }}
{{- else -}}
{{ include "infrahub-observability.grafanaMcpFullname" . }}
{{- end -}}
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
Address of Grafana for the Grafana MCP server and its hook Job.
*/}}
{{- define "infrahub-observability.grafanaMcpGrafanaUrl" -}}
{{- if .Values.grafanaMcp.grafana.url -}}
{{ .Values.grafanaMcp.grafana.url }}
{{- else -}}
{{- $port := int (default 80 (.Values.grafana.service).port) -}}
http://{{ include "infrahub-observability.grafanaFullname" . }}{{ if ne $port 80 }}:{{ $port }}{{ end }}
{{- end -}}
{{- end }}

{{/*
Check the values of the Grafana MCP server. Called by the Deployment.
*/}}
{{- define "infrahub-observability.grafanaMcpValidate" -}}
{{- if not (or .Values.grafanaMcp.serverToken.value .Values.grafanaMcp.serverToken.existingSecret) -}}
{{- fail "grafanaMcp.serverToken.value or grafanaMcp.serverToken.existingSecret is required" -}}
{{- end -}}
{{- if and (ne .Values.grafanaMcp.service.type "ClusterIP") (not .Values.grafanaMcp.tls.existingSecret) -}}
{{- fail (printf "grafanaMcp.service.type is %s, which is open to a network: set grafanaMcp.tls.existingSecret" .Values.grafanaMcp.service.type) -}}
{{- end -}}
{{- if and (not .Values.grafanaMcp.grafana.url) (not .Values.grafana.enabled) -}}
{{- fail "grafanaMcp.grafana.url is required when grafana.enabled is false" -}}
{{- end -}}
{{- end }}
