{{- define "infrahub.validateConfigPreset" -}}
{{- if and .Values.configPreset (index .Values "infrahub" "prefect-server" "enabled") }}
  {{- $redisHost := default "" (index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "redis" "host") }}
  {{- $docketUrl := default "" (index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "docket" "url") }}

  {{- $errors := list }}

  {{- if eq (trim $redisHost) "example-infrahub-cache-master" }}
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