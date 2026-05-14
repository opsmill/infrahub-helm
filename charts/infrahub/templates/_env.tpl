{{/*
Define default env variables if required.
*/}}
{{- define "infrahub-helm.infrahubDemoData.defaultEnv" -}}
{{- if not .Values.infrahubDemoData.env.KUBERNETES_CLUSTER_DOMAIN }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not .Values.infrahubDemoData.env.INFRAHUB_ADDRESS }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not .Values.infrahubDemoData.env.INFRAHUB_INTERNAL_ADDRESS }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_DB_ADDRESS) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_DB_PORT) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_BROKER_ADDRESS) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_BROKER_USERNAME) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_CACHE_ADDRESS) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not .Values.infrahubDemoData.env.INFRAHUB_CACHE_PORT) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.infrahubServer.defaultEnv" -}}
{{- if not .Values.infrahubServer.infrahubServer.env.KUBERNETES_CLUSTER_DOMAIN }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not .Values.infrahubServer.infrahubServer.env.INFRAHUB_ADDRESS }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not .Values.infrahubServer.infrahubServer.env.INFRAHUB_INTERNAL_ADDRESS }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_DB_ADDRESS) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_DB_PORT) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_BROKER_ADDRESS) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_BROKER_USERNAME) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_CACHE_ADDRESS) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not .Values.infrahubServer.infrahubServer.env.INFRAHUB_CACHE_PORT) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.infrahubTaskWorker.defaultEnv" -}}
{{- if not .Values.infrahubTaskWorker.infrahubTaskWorker.env.KUBERNETES_CLUSTER_DOMAIN }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_ADDRESS }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_INTERNAL_ADDRESS }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_DB_ADDRESS) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_DB_PORT) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_BROKER_ADDRESS) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_BROKER_USERNAME) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_CACHE_ADDRESS) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not .Values.infrahubTaskWorker.infrahubTaskWorker.env.INFRAHUB_CACHE_PORT) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.emma.defaultEnv" -}}
{{- if not .Values.emma.env.INFRAHUB_ADDRESS }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- end }}

{{/*
Tracing env vars emitted onto server and task-worker pods when
.Values.global.tracing.enabled is true.

The INFRAHUB_TRACE_* names match upstream TraceSettings (env_prefix
INFRAHUB_TRACE_) in backend/infrahub/config.py.

The OTEL_EXPORTER_OTLP_* names are the OpenTelemetry SDK's standard env
vars. They're emitted because upstream infrahub's create_tracer_provider()
constructs the OTLP gRPC exporter without forwarding the `insecure` setting
from INFRAHUB_TRACE_INSECURE — meaning the gRPC client defaults to TLS and
fails the handshake against a plaintext OTLP collector. Setting
OTEL_EXPORTER_OTLP_INSECURE makes the OTel SDK itself honour the setting.
*/}}
{{- define "infrahub-helm.tracingEnv" -}}
{{- if .Values.global.tracing.enabled }}
- name: INFRAHUB_TRACE_ENABLE
  value: "true"
- name: INFRAHUB_TRACE_INSECURE
  value: {{ .Values.global.tracing.insecure | quote }}
- name: INFRAHUB_TRACE_EXPORTER_TYPE
  value: "otlp"
- name: INFRAHUB_TRACE_EXPORTER_PROTOCOL
  value: {{ .Values.global.tracing.protocol | quote }}
- name: INFRAHUB_TRACE_EXPORTER_ENDPOINT
  value: {{ .Values.global.tracing.endpoint | quote }}
- name: OTEL_EXPORTER_OTLP_INSECURE
  value: {{ .Values.global.tracing.insecure | quote }}
- name: OTEL_EXPORTER_OTLP_TRACES_INSECURE
  value: {{ .Values.global.tracing.insecure | quote }}
{{- end }}
{{- end }}
