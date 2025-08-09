{{- define "infrahub.validateConfigPreset" -}}
{{- if .Values.configPreset }}
  {{- $envList := default list (index .Values "infrahub" "prefect-server" "server" "env") }}

  {{- $errors := list }}

  {{- $prefectRedisFound := false }}
  {{- $cacheAddressFound := false }}

  {{- range $env := $envList }}
    {{- $nameUpper := upper (default "" $env.name) }}
    {{- $trimmedValue := trim (default "" $env.value) }}

    {{- if eq $nameUpper "PREFECT_REDIS_MESSAGING_HOST" }}
      {{- $prefectRedisFound = true }}
      {{- if eq $trimmedValue "" }}
        {{- $errors = append $errors "PREFECT_REDIS_MESSAGING_HOST has an empty or whitespace-only value" }}
      {{- end }}
    {{- end }}

    {{- if eq $nameUpper "INFRAHUB_CACHE_ADDRESS" }}
      {{- $cacheAddressFound = true }}
      {{- if eq $trimmedValue "" }}
        {{- $errors = append $errors "INFRAHUB_CACHE_ADDRESS has an empty or whitespace-only value" }}
      {{- end }}
    {{- end }}
  {{- end }}

  {{- if not $prefectRedisFound }}
    {{- $errors = append $errors "PREFECT_REDIS_MESSAGING_HOST is missing from infrahub.prefect-server.server.env" }}
  {{- end }}
  {{- if not $cacheAddressFound }}
    {{- $errors = append $errors "INFRAHUB_CACHE_ADDRESS is missing from infrahub.prefect-server.server.env" }}
  {{- end }}

  {{- if gt (len $errors) 0 }}
    {{- fail (printf "Validation errors:\n- %s" (join "\n- " $envList)) }}
  {{- end }}
{{- end -}}
{{- end -}}