{{/*
Check if an environment variable name exists in a list-format env.
Usage: include "infrahub-helm.envHasKey" (dict "env" .Values.component.env "key" "VAR_NAME")
Returns "true" if found, empty string if not.
*/}}
{{- define "infrahub-helm.envHasKey" -}}
{{- $key := .key -}}
{{- range .env -}}
{{- if eq (default "" .name) $key -}}
true
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Define default env variables if required.
*/}}
{{- define "infrahub-helm.infrahubDemoData.defaultEnv" -}}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "KUBERNETES_CLUSTER_DOMAIN")) }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_ADDRESS")) }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_INTERNAL_ADDRESS")) }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_DB_ADDRESS"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_DB_PORT"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_BROKER_ADDRESS"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_BROKER_USERNAME"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_CACHE_ADDRESS"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubDemoData.env "key" "INFRAHUB_CACHE_PORT"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.infrahubServer.defaultEnv" -}}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "KUBERNETES_CLUSTER_DOMAIN")) }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_ADDRESS")) }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_INTERNAL_ADDRESS")) }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_DB_ADDRESS"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_DB_PORT"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_BROKER_ADDRESS"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_BROKER_USERNAME"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_CACHE_ADDRESS"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubServer.infrahubServer.env "key" "INFRAHUB_CACHE_PORT"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.infrahubTaskWorker.defaultEnv" -}}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "KUBERNETES_CLUSTER_DOMAIN")) }}
- name: KUBERNETES_CLUSTER_DOMAIN
  value: {{ quote .Values.global.kubernetesClusterDomain }}
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_ADDRESS")) }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_INTERNAL_ADDRESS")) }}
- name: INFRAHUB_INTERNAL_ADDRESS
  value: "http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_DB_ADDRESS"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_ADDRESS
  value: "{{ include "neo4j.fullname" .Subcharts.neo4j }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_DB_PORT"))) .Values.neo4j.enabled }}
- name: INFRAHUB_DB_PORT
  value: "{{ .Values.neo4j.services.neo4j.ports.bolt.port }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_BROKER_ADDRESS"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.rabbitmq }}"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_BROKER_USERNAME"))) .Values.rabbitmq.enabled }}
- name: INFRAHUB_BROKER_USERNAME
  value: {{ .Values.rabbitmq.auth.username | quote }}
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_CACHE_ADDRESS"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_ADDRESS
  value: "{{ include "common.names.fullname" .Subcharts.redis }}-master"
{{- end }}
{{- if and (not (include "infrahub-helm.envHasKey" (dict "env" .Values.infrahubTaskWorker.infrahubTaskWorker.env "key" "INFRAHUB_CACHE_PORT"))) .Values.redis.enabled }}
- name: INFRAHUB_CACHE_PORT
  value: "{{ .Values.redis.master.service.ports.redis }}"
{{- end }}
{{- end }}

{{- define "infrahub-helm.emma.defaultEnv" -}}
{{- if not (include "infrahub-helm.envHasKey" (dict "env" .Values.emma.env "key" "INFRAHUB_ADDRESS")) }}
- name: INFRAHUB_ADDRESS
  value: http://{{ include "infrahub-helm.fullname" . }}-infrahub-server:8000
{{- end }}
{{- end }}
