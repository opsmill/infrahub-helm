{{- define "infrahub.validateConfigPreset" -}}
{{- if and .Values.configPreset (index .Values "infrahub" "prefect-server" "enabled") }}
  {{- $redis := index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "redis" }}
  {{- $redisHost := default "" $redis.host }}
  {{- /* prefect-server ignores the host when a Redis URL is set, so the example value is harmless then. */}}
  {{- $hasRedisUrl := or $redis.url (and $redis.existingSecret $redis.existingSecretUrlKey) }}
  {{- $docketUrl := default "" (index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "docket" "url") }}

  {{- $errors := list }}

  {{- if and (not $hasRedisUrl) (eq (trim $redisHost) "example-infrahub-cache-master") }}
    {{- $errors = append $errors "infrahub.prefect-server.backgroundServices.messaging.redis.host still has the example value 'example-infrahub-cache-master', please set the correct hostname" }}
  {{- end }}

  {{- if contains "example-infrahub-cache-master" $docketUrl }}
    {{- $errors = append $errors "infrahub.prefect-server.backgroundServices.messaging.docket.url still has the example hostname 'example-infrahub-cache-master', please set the correct hostname (format: 'redis://<host>:<port>/<db>', e.g. 'redis://infrahub-cache-master:6379/2')" }}
  {{- end }}

  {{- if gt (len $errors) 0 }}
    {{- fail (printf "Validation errors:\n- %s" (join "\n- " $errors)) }}
  {{- end }}
{{- end -}}
{{- end -}}