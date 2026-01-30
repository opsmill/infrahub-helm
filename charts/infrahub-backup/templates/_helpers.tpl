{{/*
Expand the name of the chart.
*/}}
{{- define "infrahub-backup.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "infrahub-backup.fullname" -}}
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
{{- define "infrahub-backup.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "infrahub-backup.labels" -}}
helm.sh/chart: {{ include "infrahub-backup.chart" . }}
{{ include "infrahub-backup.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "infrahub-backup.selectorLabels" -}}
app.kubernetes.io/name: {{ include "infrahub-backup.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "infrahub-backup.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "infrahub-backup.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the image name
*/}}
{{- define "infrahub-backup.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Return S3 environment variables for backup
*/}}
{{- define "infrahub-backup.s3EnvVars" -}}
- name: INFRAHUB_S3_BUCKET
  value: {{ .Values.backup.storage.s3.bucket | quote }}
{{- if .Values.backup.storage.s3.prefix }}
- name: INFRAHUB_S3_PREFIX
  value: {{ .Values.backup.storage.s3.prefix | quote }}
{{- end }}
{{- if .Values.backup.storage.s3.endpoint }}
- name: INFRAHUB_S3_ENDPOINT
  value: {{ .Values.backup.storage.s3.endpoint | quote }}
{{- end }}
- name: INFRAHUB_S3_REGION
  value: {{ .Values.backup.storage.s3.region | quote }}
{{- if .Values.backup.storage.s3.secretName }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.backup.storage.s3.secretName }}
      key: AWS_ACCESS_KEY_ID
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.backup.storage.s3.secretName }}
      key: AWS_SECRET_ACCESS_KEY
{{- end }}
{{- end }}

{{/*
Return S3 environment variables for restore
*/}}
{{- define "infrahub-backup.restoreS3EnvVars" -}}
{{- if eq .Values.restore.storage.type "s3" }}
- name: INFRAHUB_S3_REGION
  value: {{ .Values.restore.storage.s3.region | quote }}
{{- if .Values.restore.storage.s3.secretName }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.restore.storage.s3.secretName }}
      key: AWS_ACCESS_KEY_ID
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.restore.storage.s3.secretName }}
      key: AWS_SECRET_ACCESS_KEY
{{- end }}
{{- end }}
{{- end }}

{{/*
Return backup command arguments
*/}}
{{- define "infrahub-backup.backupArgs" -}}
- create
{{- if .Values.backup.options.force }}
- --force
{{- end }}
{{- if .Values.backup.options.excludeTaskmanager }}
- --exclude-taskmanager
{{- end }}
- --neo4jmetadata={{ .Values.backup.options.neo4jMetadata }}
{{- if eq .Values.backup.storage.type "s3" }}
- --s3-upload
{{- if .Values.backup.options.keepLocal }}
- --s3-keep-local
{{- end }}
{{- end }}
{{- if eq .Values.backup.storage.type "local" }}
- --backup-dir={{ .Values.backup.storage.path }}
{{- if .Values.backup.options.sleep }}
- --sleep={{ .Values.backup.options.sleep }}
{{- end }}
{{- end }}
{{- range .Values.backup.options.extraArgs }}
- {{ . | quote }}
{{- end }}
{{- end }}

{{/*
Return restore command arguments
*/}}
{{- define "infrahub-backup.restoreArgs" -}}
- restore
{{- if .Values.restore.options.excludeTaskmanager }}
- --exclude-taskmanager
{{- end }}
{{- if .Values.restore.options.migrateFormat }}
- --migrate-format
{{- end }}
{{- if eq .Values.restore.storage.type "local" }}
{{- if .Values.restore.options.sleep }}
- --sleep={{ .Values.restore.options.sleep }}
{{- end }}
- "{{ .Values.restore.storage.path }}/{{ .Values.restore.storage.local.filename }}"
{{- else }}
{{- if .Values.restore.storage.s3.endpoint }}
- --s3-endpoint={{ .Values.restore.storage.s3.endpoint }}
{{- end }}
- "s3://{{ .Values.restore.storage.s3.bucket }}/{{ .Values.restore.storage.s3.key }}"
{{- end }}
{{- range .Values.restore.options.extraArgs }}
- {{ . | quote }}
{{- end }}
{{- end }}
