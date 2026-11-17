{{/*
Expand the name of the chart.
*/}}
{{- define "infrahub-sync.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "infrahub-sync.fullname" -}}
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
Name of one component's resources: "<fullname>-<component>".
Argument: (dict "context" $ "component" "api")
*/}}
{{- define "infrahub-sync.componentName" -}}
{{- printf "%s-%s" (include "infrahub-sync.fullname" .context) .component | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Name of the HTTPRoute that routes to the Sync API.
*/}}
{{- define "infrahub-sync.httproute.name" -}}
{{- if .Values.gatewayApi.httpRoute.name -}}
  {{- .Values.gatewayApi.httpRoute.name -}}
{{- else -}}
  {{- printf "%s-httproute" (include "infrahub-sync.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Name of the Gateway the chart creates when gatewayApi.gateway.enabled is true.
*/}}
{{- define "infrahub-sync.gateway.name" -}}
{{- if .Values.gatewayApi.gateway.name -}}
  {{- .Values.gatewayApi.gateway.name -}}
{{- else -}}
  {{- printf "%s-gateway" (include "infrahub-sync.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "infrahub-sync.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
Argument: (dict "context" $ "component" "api"); "component" may be left out.
*/}}
{{- define "infrahub-sync.labels" -}}
helm.sh/chart: {{ include "infrahub-sync.chart" .context }}
{{ include "infrahub-sync.selectorLabels" . }}
{{- if .context.Chart.AppVersion }}
app.kubernetes.io/version: {{ .context.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
{{- end }}

{{/*
Selector labels.
Argument: (dict "context" $ "component" "api"); "component" may be left out.
*/}}
{{- define "infrahub-sync.selectorLabels" -}}
app.kubernetes.io/name: {{ include "infrahub-sync.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
{{- with .component }}
app.kubernetes.io/component: {{ . }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "infrahub-sync.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "infrahub-sync.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
The first three items of every Sync container command. tini is the image's entrypoint, and a
Kubernetes `command` replaces the entrypoint, so the chart names it again, as the infrahub chart
does for its Prefect server. tini runs as PID 1: it passes SIGTERM on to the whole process group
(`-g`), so the worker and the child process of each run receive it, and it collects orphaned
processes. Without it the command is PID 1, which the kernel sends no signal it has no handler for.
*/}}
{{- define "infrahub-sync.tini" -}}
- /usr/bin/tini
- -g
- --
{{- end -}}

{{/*
The Sync image: "repository:tag", the tag defaulting to the chart's appVersion.
*/}}
{{- define "infrahub-sync.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" (toString .Values.image.repository) (toString $tag) }}
{{- end }}

{{/*
An image pinned by digest: "repository:tag@digest".
Argument: an image block, for example .Values.postgresql.image
*/}}
{{- define "infrahub-sync.digestImage" -}}
{{- printf "%s:%s@%s" (toString .repository) (toString .tag) (toString .digest) }}
{{- end }}

{{/*
Name of the Secret that holds the credentials: the existing Secret, or "<fullname>".
*/}}
{{- define "infrahub-sync.secretName" -}}
{{- if .Values.credentials.existingSecret }}
{{- .Values.credentials.existingSecret }}
{{- else }}
{{- include "infrahub-sync.fullname" . }}
{{- end }}
{{- end }}

{{/*
Name of the Secret that the chart creates from worker.credentials.
*/}}
{{- define "infrahub-sync.workerCredentialsSecretName" -}}
{{- printf "%s-worker-credentials" (include "infrahub-sync.fullname" .) }}
{{- end }}

{{/*
Name of the CA ConfigMap: the existing ConfigMap, or "<fullname>-ca". Empty when no CA value is set.
*/}}
{{- define "infrahub-sync.caConfigMapName" -}}
{{- if .Values.caCertificates.existingConfigMap }}
{{- .Values.caCertificates.existingConfigMap }}
{{- else if .Values.caCertificates.certificates }}
{{- printf "%s-ca" (include "infrahub-sync.fullname" .) }}
{{- end }}
{{- end }}

{{/*
An env entry read from one key of the credentials Secret.
Argument: (dict "context" $ "name" "PREFECT_API_AUTH_STRING" "key" "INFRAHUB_SYNC_PREFECT_AUTH_STRING")
*/}}
{{- define "infrahub-sync.env.secretRef" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ include "infrahub-sync.secretName" .context }}
      key: {{ .key }}
{{- end }}

{{/*
The Prefect server's API address.
*/}}
{{- define "infrahub-sync.prefectApiUrl" -}}
{{- printf "http://%s:4200/api" (include "infrahub-sync.componentName" (dict "context" . "component" "prefect-server")) }}
{{- end }}

{{/*
The Prefect client environment: the API address and the API credential.
*/}}
{{- define "infrahub-sync.env.prefectClient" -}}
- name: PREFECT_API_URL
  value: {{ include "infrahub-sync.prefectApiUrl" . | quote }}
{{ include "infrahub-sync.env.secretRef" (dict "context" . "name" "PREFECT_API_AUTH_STRING" "key" "INFRAHUB_SYNC_PREFECT_AUTH_STRING") }}
{{- end }}

{{/*
Everything a Sync process needs to reach its durable state: the `x-sync-storage` anchor of
docker-compose.yml, as an env list. The Sync API, the worker and the bootstrap Job get the same
endpoints. No entry holds a credential value: credentials come from secretKeyRef, and the bundled
PostgreSQL connection string expands the password variable defined just before it. An optional
setting that is not set is left out, because the image refuses an empty one.
*/}}
{{- define "infrahub-sync.env.storage" -}}
{{- if .Values.postgresql.enabled }}
{{ include "infrahub-sync.env.secretRef" (dict "context" . "name" "INFRAHUB_SYNC_PRODUCT_PASSWORD" "key" "INFRAHUB_SYNC_PRODUCT_PASSWORD") }}
- name: INFRAHUB_SYNC_DATABASE_URL
  value: {{ printf "postgresql://%s:$(INFRAHUB_SYNC_PRODUCT_PASSWORD)@%s:5432/%s" .Values.postgresql.productRole (include "infrahub-sync.componentName" (dict "context" . "component" "postgresql")) .Values.postgresql.productDatabase | quote }}
{{- else }}
{{ include "infrahub-sync.env.secretRef" (dict "context" . "name" "INFRAHUB_SYNC_DATABASE_URL" "key" "INFRAHUB_SYNC_DATABASE_URL") }}
{{- end }}
{{- with .Values.s3.bucket }}
- name: INFRAHUB_SYNC_S3_BUCKET
  value: {{ . | toString | quote }}
{{- end }}
{{- with .Values.s3.prefix }}
- name: INFRAHUB_SYNC_S3_PREFIX
  value: {{ . | toString | quote }}
{{- end }}
{{- if .Values.objectStore.enabled }}
- name: INFRAHUB_SYNC_S3_ENDPOINT_URL
  value: {{ printf "http://%s:9000" (include "infrahub-sync.componentName" (dict "context" . "component" "object-store")) | quote }}
- name: INFRAHUB_SYNC_S3_ADDRESSING_STYLE
  value: "path"
{{- else }}
{{- with .Values.s3.endpointUrl }}
- name: INFRAHUB_SYNC_S3_ENDPOINT_URL
  value: {{ . | toString | quote }}
{{- end }}
{{- with .Values.s3.addressingStyle }}
- name: INFRAHUB_SYNC_S3_ADDRESSING_STYLE
  value: {{ . | toString | quote }}
{{- end }}
{{- end }}
{{- with .Values.s3.region }}
- name: INFRAHUB_SYNC_S3_REGION
  value: {{ . | toString | quote }}
{{- end }}
{{ include "infrahub-sync.env.secretRef" (dict "context" . "name" "AWS_ACCESS_KEY_ID" "key" "INFRAHUB_SYNC_S3_ACCESS_KEY") }}
{{ include "infrahub-sync.env.secretRef" (dict "context" . "name" "AWS_SECRET_ACCESS_KEY" "key" "INFRAHUB_SYNC_S3_SECRET_KEY") }}
- name: INFRAHUB_SYNC_SERVICE_WORK_POOL
  value: {{ .Values.settings.workPool | toString | quote }}
{{ include "infrahub-sync.env.prefectClient" . }}
{{- end }}

{{/*
True (non-empty) when a CA value is set.
*/}}
{{- define "infrahub-sync.ca.enabled" -}}
{{- if or .Values.caCertificates.existingConfigMap .Values.caCertificates.certificates }}true{{- end }}
{{- end }}

{{/*
The CA directory variable, only when a CA value is set. Renders nothing otherwise.
*/}}
{{- define "infrahub-sync.env.ca" -}}
{{- if include "infrahub-sync.ca.enabled" . }}
- name: INFRAHUB_SYNC_CA_DIRECTORY
  value: "/etc/infrahub-sync/ca"
{{- end }}
{{- end }}

{{/*
The CA ConfigMap volume, only when a CA value is set. Renders nothing otherwise.
*/}}
{{- define "infrahub-sync.volumes.ca" -}}
{{- if include "infrahub-sync.ca.enabled" . }}
- name: ca-certificates
  configMap:
    name: {{ include "infrahub-sync.caConfigMapName" . }}
{{- end }}
{{- end }}

{{/*
The read-only CA mount, only when a CA value is set. Renders nothing otherwise.
*/}}
{{- define "infrahub-sync.mounts.ca" -}}
{{- if include "infrahub-sync.ca.enabled" . }}
- name: ca-certificates
  mountPath: /etc/infrahub-sync/ca
  readOnly: true
{{- end }}
{{- end }}

{{/*
The image's three writable roots, memory-backed and private to the pod (the `x-sync-scratch`
tmpfs mounts of docker-compose.yml).
*/}}
{{- define "infrahub-sync.volumes.scratch" -}}
- name: scratch-home
  emptyDir:
    medium: Memory
- name: scratch-prefect
  emptyDir:
    medium: Memory
- name: scratch-tmp
  emptyDir:
    medium: Memory
{{- end }}

{{- define "infrahub-sync.mounts.scratch" -}}
- name: scratch-home
  mountPath: /var/lib/infrahub-sync
- name: scratch-prefect
  mountPath: /var/lib/infrahub-sync/prefect
- name: scratch-tmp
  mountPath: /tmp/infrahub-sync
{{- end }}

{{/*
Init container of the bootstrap Job: waits until the Prefect server answers its health probe,
which Prefect leaves open without the API credential.
*/}}
{{- define "infrahub-sync.initContainer.waitForPrefect" -}}
- name: wait-for-prefect
  image: {{ include "infrahub-sync.image" . | quote }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  command:
    - python
    - -c
    - |
      import sys
      import time

      import httpx

      URL = sys.argv[1]
      TIMEOUT = float(sys.argv[2])
      start = time.monotonic()
      print(f"waiting for {URL}", flush=True)
      while True:
          try:
              httpx.get(URL, timeout=5).raise_for_status()
              print(f"the Prefect server is healthy after {time.monotonic() - start:.0f}s", flush=True)
              sys.exit(0)
          except httpx.HTTPError:
              pass
          if time.monotonic() - start >= TIMEOUT:
              print(f"the Prefect server is not healthy after {time.monotonic() - start:.0f}s", file=sys.stderr, flush=True)
              sys.exit(1)
          time.sleep(5)
    - {{ printf "%s/health" (include "infrahub-sync.prefectApiUrl" .) | quote }}
    - {{ .Values.waitTimeoutSeconds | int | toString | quote }}
  volumeMounts:
    {{- include "infrahub-sync.mounts.scratch" . | nindent 4 }}
{{- end }}

{{/*
Init container of the Prefect server, with the bundled PostgreSQL only: waits until PostgreSQL
accepts connections. It runs `pg_isready` from the PostgreSQL image and needs no credential.
*/}}
{{- define "infrahub-sync.initContainer.waitForPostgresql" -}}
- name: wait-for-postgresql
  image: {{ include "infrahub-sync.digestImage" .Values.postgresql.image | quote }}
  imagePullPolicy: IfNotPresent
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  command:
    - /bin/sh
    - -ec
    - |
      host="$1"
      timeout="$2"
      role="$3"
      waited=0
      echo "waiting for PostgreSQL at ${host}:5432"
      # The user has no passwd entry in this image, so pg_isready needs a role name to try.
      until pg_isready -q -h "$host" -p 5432 -U "$role" -d "$role"; do
        if [ "$waited" -ge "$timeout" ]; then
          echo "PostgreSQL is not ready after ${waited}s" >&2
          exit 1
        fi
        sleep 5
        waited=$((waited + 5))
      done
      echo "PostgreSQL is ready after ${waited}s"
    - wait-for-postgresql
    - {{ include "infrahub-sync.componentName" (dict "context" . "component" "postgresql") | quote }}
    - {{ .Values.waitTimeoutSeconds | int | toString | quote }}
    - {{ .Values.postgresql.adminRole | quote }}
{{- end }}

{{/*
The `data` of the credentials Secret: one key per credential value that is set. The key names
are the variable names of the Compose `.env` file.
*/}}
{{- define "infrahub-sync.secret.data" -}}
{{- $keys := dict
  "INFRAHUB_SYNC_SERVICE_BEARER_TOKENS" .Values.credentials.bearerTokens
  "INFRAHUB_SYNC_PREFECT_AUTH_STRING" .Values.credentials.prefectAuthString
  "INFRAHUB_SYNC_S3_ACCESS_KEY" .Values.credentials.s3AccessKey
  "INFRAHUB_SYNC_S3_SECRET_KEY" .Values.credentials.s3SecretKey
  "INFRAHUB_SYNC_POSTGRES_ADMIN_PASSWORD" .Values.credentials.postgresAdminPassword
  "INFRAHUB_SYNC_PRODUCT_PASSWORD" .Values.credentials.productPassword
  "INFRAHUB_SYNC_PREFECT_PASSWORD" .Values.credentials.prefectPassword
  "INFRAHUB_SYNC_DATABASE_URL" .Values.credentials.databaseUrl
  "INFRAHUB_SYNC_PREFECT_DATABASE_URL" .Values.credentials.prefectDatabaseUrl
  "INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN" .Values.credentials.infrahubApiToken
}}
{{- range $key := keys $keys | sortAlpha }}
{{- with get $keys $key }}
{{ $key }}: {{ . | toString | b64enc | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
The `data` of the worker credentials Secret.
*/}}
{{- define "infrahub-sync.workerCredentials.data" -}}
{{- range $key, $value := .Values.worker.credentials }}
{{ $key }}: {{ $value | toString | b64enc | quote }}
{{- end }}
{{- end }}

{{/*
Checksums of the Secret and ConfigMaps that the chart creates, over their content only (not
their labels, so a chart version change alone does not change them). Each is empty when the
chart does not create that resource.
*/}}
{{- define "infrahub-sync.checksum.secret" -}}
{{- if not .Values.credentials.existingSecret }}
{{- include "infrahub-sync.secret.data" . | sha256sum }}
{{- end }}
{{- end }}

{{- define "infrahub-sync.checksum.workerCredentials" -}}
{{- if .Values.worker.credentials }}
{{- include "infrahub-sync.workerCredentials.data" . | sha256sum }}
{{- end }}
{{- end }}

{{- define "infrahub-sync.checksum.ca" -}}
{{- if and .Values.caCertificates.certificates (not .Values.caCertificates.existingConfigMap) }}
{{- toJson .Values.caCertificates.certificates | sha256sum }}
{{- end }}
{{- end }}

{{/*
Pod annotations of the worker, which restart it when a Secret or ConfigMap the chart creates
changes. The Sync API sets only the credentials Secret and CA checksums.
*/}}
{{- define "infrahub-sync.checksums" -}}
checksum/secret: {{ include "infrahub-sync.checksum.secret" . | quote }}
checksum/worker-credentials: {{ include "infrahub-sync.checksum.workerCredentials" . | quote }}
checksum/ca: {{ include "infrahub-sync.checksum.ca" . | quote }}
{{- end }}

{{/*
Suffix of the bootstrap Job name: the first 8 characters of a SHA-256 over what the bootstrap
reads. That is the image reference, its environment (no entry of which holds a credential
value), its extra environment, and the checksums of the credentials Secret and the CA ConfigMap.
The release revision is not part of it, so an upgrade that changes none of these keeps the Job.

A Job's pod template cannot be changed after creation, so every other value that enters the
Job's pod template is part of the hash too: the `bootstrap` block (resources, scheduling, pod
annotations and labels, extra environment), the pull policy and pull secrets, the security
contexts, the service account, the CA ConfigMap name and the wait timeout. The chart version is
part of it too, because a new chart version can change the Job's template itself. A change to
one of them gives a new Job instead of a patch that Kubernetes refuses.
*/}}
{{- define "infrahub-sync.bootstrapHash" -}}
{{- $inputs := list
  (include "infrahub-sync.image" .)
  (include "infrahub-sync.env.storage" .)
  (include "infrahub-sync.env.ca" .)
  (toJson .Values.bootstrap)
  (toString .Values.image.pullPolicy)
  (toJson .Values.imagePullSecrets)
  (toJson .Values.podSecurityContext)
  (toJson .Values.securityContext)
  (include "infrahub-sync.serviceAccountName" .)
  (toString .Values.waitTimeoutSeconds)
  (include "infrahub-sync.caConfigMapName" .)
  (toString .Chart.Version)
  (include "infrahub-sync.checksum.secret" .)
  (include "infrahub-sync.checksum.ca" .)
}}
{{- join "\n" $inputs | sha256sum | trunc 8 }}
{{- end }}

{{/*
The pod-level fields that every pod of the release shares: the service account (whose token is
never mounted), no service link variables, the pull secrets, and the component's scheduling
values.
Argument: (dict "context" $ "values" .Values.api)
*/}}
{{- define "infrahub-sync.pod.common" -}}
serviceAccountName: {{ include "infrahub-sync.serviceAccountName" .context }}
automountServiceAccountToken: false
enableServiceLinks: false
{{- with .context.Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/*
The optional destination credential, given to the Sync API and the worker. `optional: true`
lets the pod start when the Secret has no such key.
*/}}
{{- define "infrahub-sync.env.destinationCredential" -}}
- name: INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "infrahub-sync.secretName" . }}
      key: INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN
      optional: true
{{- end }}
