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
Default Prefect API URL. Resolves to the task-manager service that the sibling
infrahub chart creates. Users can override via .Values.prefectExporter.prefectApiUrl.
*/}}
{{- define "infrahub-observability.prefectApiUrl" -}}
{{- if .Values.prefectExporter.prefectApiUrl -}}
{{ .Values.prefectExporter.prefectApiUrl }}
{{- else -}}
http://{{ .Values.global.infrahubReleaseName }}-task-manager-server:4200/api
{{- end -}}
{{- end }}
