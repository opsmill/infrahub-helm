{{- define "infrahub.validateConfigPreset" -}}
{{- if and .Values.configPreset (index .Values "infrahub" "prefect-server" "enabled") }}
  {{- $redisHost := default "" (index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "redis" "host") }}

  {{- $errors := list }}

  {{- if eq (trim $redisHost) "example-infrahub-cache-master" }}
    {{- $errors = append $errors "infrahub.prefect-server.backgroundServices.messaging.redis.host still has the example value 'example-infrahub-cache-master', please set the correct hostname" }}
  {{- end }}

  {{- if gt (len $errors) 0 }}
    {{- fail (printf "Validation errors:\n- %s" (join "\n- " $errors)) }}
  {{- end }}
{{- end -}}
{{- end -}}