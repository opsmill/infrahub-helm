{{- define "infrahub.validateConfigPreset" -}}
{{- if .Values.configPreset }}
  {{- $envList := default list (index .Values "infrahub" "prefect-server" "server" "env") }}
  {{- $redisHost := default "" (index .Values "infrahub" "prefect-server" "backgroundServices" "messaging" "redis" "host") }}

  {{- $errors := list }}

  {{- $cacheAddressFound := false }}

  {{- range $env := $envList }}
    {{- $nameUpper := upper (default "" $env.name) }}
    {{- $trimmedValue := trim (default "" $env.value) }}

    {{- if eq $nameUpper "INFRAHUB_CACHE_ADDRESS" }}
      {{- $cacheAddressFound = true }}
      {{- if eq $trimmedValue "example-infrahub-cache-master" }}
        {{- $errors = append $errors "INFRAHUB_CACHE_ADDRESS still has the example value 'example-infrahub-cache-master', please set the correct hostname" }}
      {{- end }}
    {{- end }}
  {{- end }}

  {{- if eq (trim $redisHost) "example-infrahub-cache-master" }}
    {{- $errors = append $errors "infrahub.prefect-server.backgroundServices.messaging.redis.host still has the example value 'example-infrahub-cache-master', please set the correct hostname" }}
  {{- end }}
  {{- if not $cacheAddressFound }}
    {{- $errors = append $errors "INFRAHUB_CACHE_ADDRESS is missing from infrahub.prefect-server.server.env" }}
  {{- end }}

  {{- if gt (len $errors) 0 }}
    {{- fail (printf "Validation errors:\n- %s" (join "\n- " $errors)) }}
  {{- end }}
{{- end -}}
{{- end -}}