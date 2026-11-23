{{/*
Render-time refusals. Each message names the value it refuses. Every template of the chart
includes this, so `helm template` and `helm install` run it whatever the chart renders.

With credentials.existingSecret set, the chart cannot read the Secret's keys at render time;
Kubernetes then names a missing key in the status of the pod that needs it.
*/}}
{{- define "infrahub-sync.validate" -}}
{{- $credentials := .Values.credentials }}
{{- if not $credentials.existingSecret }}
{{- $_ := required "credentials.adminAccountPassword is required when credentials.existingSecret is empty" $credentials.adminAccountPassword }}
{{- $_ = required "credentials.encryptionKey is required when credentials.existingSecret is empty" $credentials.encryptionKey }}
{{- $_ = required "credentials.workerToken is required when credentials.existingSecret is empty" $credentials.workerToken }}
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
{{- /*
Values that the chart renders as text. Helm reads an unquoted number as a floating-point
number, so 3.0 would render as 3 and 12345678 as 1.2345678e+07. Each must be a string or unset.
*/}}
{{- $strings := dict
  "image.tag" .Values.image.tag
  "postgresql.image.tag" .Values.postgresql.image.tag
  "objectStore.image.tag" .Values.objectStore.image.tag
  "s3.bucket" .Values.s3.bucket
  "s3.prefix" .Values.s3.prefix
  "s3.region" .Values.s3.region
  "settings.workPool" .Values.settings.workPool
}}
{{- range $key, $value := .Values.credentials }}
{{- $_ := set $strings (printf "credentials.%s" $key) $value }}
{{- end }}
{{- $_ := set $strings "worker.apiUrl" .Values.worker.apiUrl }}
{{- range $name, $value := $strings }}
{{- if not (or (kindIs "string" $value) (kindIs "invalid" $value)) }}
{{- fail (printf "%s must be a string: quote it in the values, for example \"17\" instead of 17, or pass it with --set-string. Helm reads an unquoted number as a floating-point number, which can change the value (3.0 becomes 3, 12345678 becomes 1.2345678e+07)" $name) }}
{{- end }}
{{- end }}
{{- /*
The rules that the Sync API applies at start to the `admin` account variables, checked here so
that the render refuses a value that would stop the Sync API. The messages never hold the value.
`len` counts bytes, not characters, so a password of 12 characters or more that the Sync API
accepts always passes. The upper limit of 1,024 characters is left to the Sync API.
*/}}
{{- if not $credentials.existingSecret }}
{{- if lt (len $credentials.adminAccountPassword) 12 }}
{{- fail "credentials.adminAccountPassword must be at least 12 characters long" }}
{{- end }}
{{- with $credentials.adminAccountToken }}
{{- if lt (len .) 16 }}
{{- fail "credentials.adminAccountToken must be at least 16 characters long, or empty for no admin token" }}
{{- end }}
{{- if or (hasPrefix "ifs_pat_" .) (hasPrefix "ifs_ses_" .) }}
{{- fail "credentials.adminAccountToken must not start with ifs_pat_ or ifs_ses_: these prefixes are reserved for the tokens that the Sync API creates" }}
{{- end }}
{{- end }}
{{- /*
The key of stored credentials: the standard base64 encoding of 32 bytes is exactly 43 characters
of the base64 alphabet followed by one `=`.
*/}}
{{- if not (regexMatch "^[A-Za-z0-9+/]{43}=$" ($credentials.encryptionKey | toString | trim)) }}
{{- fail "credentials.encryptionKey must be 32 bytes, base64-encoded: generate one with python -c \"import base64,os;print(base64.b64encode(os.urandom(32)).decode())\"" }}
{{- end }}
{{- $workerToken := $credentials.workerToken | toString }}
{{- if lt (len $workerToken) 16 }}
{{- fail "credentials.workerToken must be at least 16 characters long" }}
{{- end }}
{{- if or (hasPrefix "ifs_pat_" $workerToken) (hasPrefix "ifs_ses_" $workerToken) }}
{{- fail "credentials.workerToken must not start with ifs_pat_ or ifs_ses_: these prefixes are reserved for the tokens that the Sync API creates" }}
{{- end }}
{{- if and $credentials.adminAccountToken (eq $workerToken ($credentials.adminAccountToken | toString)) }}
{{- fail "credentials.workerToken must differ from credentials.adminAccountToken" }}
{{- end }}
{{- end }}
{{- with .Values.worker.apiUrl }}
{{- if not (regexMatch "^https?://[^/@[:space:]]+(/[^[:space:]]*)?$" (toString .)) }}
{{- fail "worker.apiUrl must be an http:// or https:// address with a host, and no user name or password, or empty for the Sync API Service of the release" }}
{{- end }}
{{- end }}
{{- with .Values.settings.sessionIdleSeconds }}
{{- if not (and (regexMatch "^[0-9]+$" (toString .)) (ge (int .) 60)) }}
{{- fail "settings.sessionIdleSeconds must be a whole number of at least 60, or empty for the Sync API's default of 28800" }}
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
{{- if and .Values.ingress.enabled .Values.gatewayApi.enabled }}
{{- fail "ingress.enabled and gatewayApi.enabled are mutually exclusive: turn one of them off" }}
{{- end }}
{{- if and .Values.ingress.enabled (not .Values.ingress.hostname) }}
{{- fail "ingress.hostname is required when ingress.enabled is true" }}
{{- end }}
{{- if .Values.gatewayApi.enabled }}
{{- if and (not .Values.gatewayApi.httpRoute.parentRefs) (not .Values.gatewayApi.gateway.enabled) }}
{{- fail "gatewayApi.httpRoute.parentRefs is required when gatewayApi.enabled is true and gatewayApi.gateway.enabled is false" }}
{{- end }}
{{- if and .Values.gatewayApi.gateway.enabled (not .Values.gatewayApi.gateway.className) }}
{{- fail "gatewayApi.gateway.className is required when gatewayApi.gateway.enabled is true" }}
{{- end }}
{{- if and .Values.gatewayApi.gateway.enabled (not .Values.gatewayApi.gateway.listeners) }}
{{- fail "gatewayApi.gateway.listeners needs at least one listener when gatewayApi.gateway.enabled is true" }}
{{- end }}
{{- end }}
{{- if and .Values.caCertificates.existingConfigMap .Values.caCertificates.certificates }}
{{- fail "caCertificates.existingConfigMap and caCertificates.certificates are mutually exclusive: set one of them" }}
{{- end }}
{{- end }}
