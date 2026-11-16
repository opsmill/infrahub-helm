{{/*
Render-time refusals. Each message names the value it refuses. Every template of the chart
includes this, so `helm template` and `helm install` run it whatever the chart renders.

With credentials.existingSecret set, the chart cannot read the Secret's keys at render time;
Kubernetes then names a missing key in the status of the pod that needs it.
*/}}
{{- define "infrahub-sync.validate" -}}
{{- $credentials := .Values.credentials }}
{{- if not $credentials.existingSecret }}
{{- $_ := required "credentials.bearerTokens is required when credentials.existingSecret is empty" $credentials.bearerTokens }}
{{- $_ = required "credentials.prefectAuthString is required when credentials.existingSecret is empty" $credentials.prefectAuthString }}
{{- $_ = required "credentials.s3AccessKey is required when credentials.existingSecret is empty" $credentials.s3AccessKey }}
{{- $_ = required "credentials.s3SecretKey is required when credentials.existingSecret is empty" $credentials.s3SecretKey }}
{{- if .Values.postgresql.enabled }}
{{- $_ = required "credentials.postgresAdminPassword is required when postgresql.enabled is true and credentials.existingSecret is empty" $credentials.postgresAdminPassword }}
{{- $_ = required "credentials.productPassword is required when postgresql.enabled is true and credentials.existingSecret is empty" $credentials.productPassword }}
{{- $_ = required "credentials.prefectPassword is required when postgresql.enabled is true and credentials.existingSecret is empty" $credentials.prefectPassword }}
{{- else }}
{{- $_ = required "credentials.databaseUrl is required when postgresql.enabled is false and credentials.existingSecret is empty" $credentials.databaseUrl }}
{{- $_ = required "credentials.prefectDatabaseUrl is required when postgresql.enabled is false and credentials.existingSecret is empty" $credentials.prefectDatabaseUrl }}
{{- end }}
{{- end }}
{{- if and .Values.objectStore.enabled .Values.s3.endpointUrl }}
{{- fail "s3.endpointUrl must be empty when objectStore.enabled is true: the bundled object store is the endpoint. Set objectStore.enabled to false to use another S3-compatible store" }}
{{- end }}
{{- if and (not .Values.objectStore.enabled) (not .Values.s3.endpointUrl) }}
{{- fail "s3.endpointUrl is required when objectStore.enabled is false" }}
{{- end }}
{{- with .Values.s3.addressingStyle }}
{{- if not (has (toString .) (list "path" "virtual")) }}
{{- fail (printf "s3.addressingStyle must be \"path\" or \"virtual\", not %q" (toString .)) }}
{{- end }}
{{- end }}
{{- range $key, $_ := .Values.worker.credentials }}
{{- if not (regexMatch "^INFRAHUB_SYNC_CREDENTIAL_[A-Za-z0-9_]+$" $key) }}
{{- fail (printf "worker.credentials key %q must match ^INFRAHUB_SYNC_CREDENTIAL_[A-Za-z0-9_]+$" $key) }}
{{- end }}
{{- end }}
{{- if and .Values.ingress.enabled .Values.gatewayApi.enabled }}
{{- fail "ingress.enabled and gatewayApi.enabled are mutually exclusive: turn one of them off" }}
{{- end }}
{{- if and .Values.caCertificates.existingConfigMap .Values.caCertificates.certificates }}
{{- fail "caCertificates.existingConfigMap and caCertificates.certificates are mutually exclusive: set one of them" }}
{{- end }}
{{- end }}
