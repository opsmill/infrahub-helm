{{/*
Expand the name of the chart.
*/}}
{{- define "infrahub-helm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "infrahub-helm.fullname" -}}
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
{{- define "infrahub-helm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "infrahub-helm.labels" -}}
helm.sh/chart: {{ include "infrahub-helm.chart" . }}
{{ include "infrahub-helm.selectorLabels" . }}
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
{{- define "infrahub-helm.annotations" -}}
{{- if gt (len .Values.global.commonAnnotations) 0 -}}
{{ .Values.global.commonAnnotations | toYaml }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "infrahub-helm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "infrahub-helm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if gt (len .Values.global.podLabels) 0 }}
{{ .Values.global.podLabels | toYaml }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use.
Returns an empty string when no ServiceAccount is created nor named, so that
the serviceAccountName field can be omitted from pod specs.
*/}}
{{- define "infrahub-helm.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "infrahub-helm.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name for the HTTPRoute resource
*/}}
{{- define "infrahub-helm.httproute.name" -}}
{{- if .Values.infrahubServer.gatewayApi.httpRoute.name -}}
  {{- .Values.infrahubServer.gatewayApi.httpRoute.name -}}
{{- else -}}
  {{- printf "%s-httproute" (include "infrahub-helm.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Name for the Gateway resource
*/}}
{{- define "infrahub-helm.gateway.name" -}}
{{- if .Values.infrahubServer.gatewayApi.gateway.name -}}
  {{- .Values.infrahubServer.gatewayApi.gateway.name -}}
{{- else -}}
  {{- printf "%s-gateway" (include "infrahub-helm.fullname" .) -}}
{{- end -}}
{{- end -}}
