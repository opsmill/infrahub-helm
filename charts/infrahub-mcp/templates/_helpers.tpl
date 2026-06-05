{{/*
Expand the name of the chart.
*/}}
{{- define "infrahub-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "infrahub-mcp.fullname" -}}
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
{{- define "infrahub-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "infrahub-mcp.labels" -}}
helm.sh/chart: {{ include "infrahub-mcp.chart" . }}
{{ include "infrahub-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "infrahub-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "infrahub-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "infrahub-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "infrahub-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the image name
*/}}
{{- define "infrahub-mcp.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Name for the HTTPRoute resource
*/}}
{{- define "infrahub-mcp.httproute.name" -}}
{{- if .Values.gatewayApi.httpRoute.name -}}
  {{- .Values.gatewayApi.httpRoute.name -}}
{{- else -}}
  {{- printf "%s-httproute" (include "infrahub-mcp.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Name for the Gateway resource
*/}}
{{- define "infrahub-mcp.gateway.name" -}}
{{- if .Values.gatewayApi.gateway.name -}}
  {{- .Values.gatewayApi.gateway.name -}}
{{- else -}}
  {{- printf "%s-gateway" (include "infrahub-mcp.fullname" .) -}}
{{- end -}}
{{- end -}}
