# infrahub-sync

A Helm chart to deploy Infrahub Sync on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

## What the chart deploys

The chart deploys the same services as the Infrahub Sync `docker-compose.yml`:

- the Sync API, which receives the requests of the `infrahub-sync` command-line client
- one worker, which executes the runs
- the Prefect server, which hands the runs to the worker
- a bootstrap Job, which creates the database schema, the object store bucket, the Prefect work
  pool and the Prefect deployment, then records the Sync version and the work pool it set up.
  The Sync API and the worker exit at start until that record matches their version and work
  pool, and Kubernetes restarts them, so they restart a few times before the Job completes
- a PostgreSQL server, which holds the Sync database and the Prefect database
- a Silo object store, which holds the artifacts of the runs

The Sync API, the worker, the Prefect server and the bootstrap Job all run the Sync image.
PostgreSQL and the object store are optional: set `postgresql.enabled: false` to use an existing
PostgreSQL server, and `objectStore.enabled: false` with `s3.endpointUrl` to use an existing
S3-compatible object store.

For the full procedure, read the
[Kubernetes deployment](https://docs.infrahub.app/sync/kubernetes-deployment) page of the
Infrahub Sync documentation. Until Infrahub Sync 3.0.0 is released, that page is in the
[documentation preview](https://feature-v3-develop.infrahub-sync.pages.dev/kubernetes-deployment)
built from the `feature/v3-develop` branch.

## The chart is not published yet

The chart is not in the registry until an Infrahub Sync release whose image holds the Prefect
server, the start check and `/usr/bin/tini` is published. The chart starts every Sync container
with `/usr/bin/tini -g --`, so a container from an earlier image, such as 3.0.0a5, fails to
start. Until then, install the chart from a checkout of this repository: replace
`oci://registry.opsmill.io/opsmill/chart/infrahub-sync` with `charts/infrahub-sync` in the
commands below. The chart's `appVersion` is still 3.0.0a5, so also set `image.repository` and
`image.tag` to a Sync image that holds the Prefect server, the start check and `/usr/bin/tini`.

## Access to the Sync image

Before Infrahub Sync 3.0.0, the registry serves the Sync image only to invited testers. Create an
image pull Secret with the registry login you received, and name it in `imagePullSecrets`:

```bash
kubectl create namespace infrahub-sync
kubectl -n infrahub-sync create secret docker-registry opsmill-registry \
  --docker-server=registry.opsmill.io \
  --docker-username=<username> \
  --docker-password=<password>
```

## The credentials Secret

The chart refuses to render without credentials. Create a Secret that holds them, and name it in
`credentials.existingSecret`. Each key is the variable name of the Compose `.env` file, so
`kubectl create secret generic <name> --from-env-file=.env` creates the Secret from that file.

| Key | Required | Read by |
| --- | --- | --- |
| `INFRAHUB_SYNC_SERVICE_BEARER_TOKENS` | always | Sync API |
| `INFRAHUB_SYNC_PREFECT_AUTH_STRING` | always | Prefect server, Sync API, worker, bootstrap |
| `INFRAHUB_SYNC_S3_ACCESS_KEY` | always | Sync API, worker, bootstrap, bundled object store |
| `INFRAHUB_SYNC_S3_SECRET_KEY` | always | Sync API, worker, bootstrap, bundled object store |
| `INFRAHUB_SYNC_POSTGRES_ADMIN_PASSWORD` | bundled PostgreSQL | PostgreSQL |
| `INFRAHUB_SYNC_PRODUCT_PASSWORD` | bundled PostgreSQL | PostgreSQL, Sync API, worker, bootstrap |
| `INFRAHUB_SYNC_PREFECT_PASSWORD` | bundled PostgreSQL | PostgreSQL, Prefect server |
| `INFRAHUB_SYNC_DATABASE_URL` | external PostgreSQL | Sync API, worker, bootstrap |
| `INFRAHUB_SYNC_PREFECT_DATABASE_URL` | external PostgreSQL | Prefect server |
| `INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN` | never | Sync API, worker |

`INFRAHUB_SYNC_PRODUCT_PASSWORD` and `INFRAHUB_SYNC_PREFECT_PASSWORD` are used in connection
strings, so they must be URL-safe.

## Install example

```bash
kubectl -n infrahub-sync create secret generic infrahub-sync --from-env-file=.env

helm install infrahub-sync oci://registry.opsmill.io/opsmill/chart/infrahub-sync \
  --namespace infrahub-sync \
  --set credentials.existingSecret=infrahub-sync \
  --set "imagePullSecrets[0].name=opsmill-registry" \
  --wait --wait-for-jobs --timeout 10m
```

With Helm 4, `--wait` alone does not wait for the bootstrap Job to complete. `--wait-for-jobs`
makes `helm install` return only after the Job is complete.

To send requests to the Sync API from your workstation, forward its port:

```bash
kubectl -n infrahub-sync port-forward svc/infrahub-sync-api 8000:8000
```

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| OpsMill |  | <https://github.com/opsmill> |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| api | object | `{"affinity":{},"extraEnv":[],"nodeSelector":{},"podAnnotations":{},"podLabels":{},"replicaCount":1,"resources":{},"service":{"port":8000,"type":"ClusterIP"},"tolerations":[]}` | The Sync API |
| api.affinity | object | `{}` | Affinity rules |
| api.extraEnv | list | `[]` | Additional environment variables (a list of `env` entries) |
| api.nodeSelector | object | `{}` | Node selector |
| api.podAnnotations | object | `{}` | Pod annotations |
| api.podLabels | object | `{}` | Pod labels |
| api.replicaCount | int | `1` | Number of replicas. One is the only tested value |
| api.resources | object | `{}` | Resource requests and limits |
| api.service | object | `{"port":8000,"type":"ClusterIP"}` | Service of the Sync API |
| api.service.port | int | `8000` | Service port |
| api.service.type | string | `"ClusterIP"` | Service type |
| api.tolerations | list | `[]` | Tolerations |
| bootstrap | object | `{"affinity":{},"backoffLimit":6,"extraEnv":[],"nodeSelector":{},"podAnnotations":{},"podLabels":{},"resources":{},"tolerations":[]}` | The bootstrap Job |
| bootstrap.affinity | object | `{}` | Affinity rules |
| bootstrap.backoffLimit | int | `6` | Number of retries before the Job is marked failed |
| bootstrap.extraEnv | list | `[]` | Additional environment variables (a list of `env` entries) |
| bootstrap.nodeSelector | object | `{}` | Node selector |
| bootstrap.podAnnotations | object | `{}` | Pod annotations |
| bootstrap.podLabels | object | `{}` | Pod labels |
| bootstrap.resources | object | `{}` | Resource requests and limits |
| bootstrap.tolerations | list | `[]` | Tolerations |
| caCertificates | object | `{"certificates":{},"existingConfigMap":""}` | CA certificates, mounted read-only at `/etc/infrahub-sync/ca` in the Sync API, the worker and the bootstrap Job. Public certificates only: the image refuses to start when a file in the directory holds a private key |
| caCertificates.certificates | object | `{}` | File name to PEM content; the chart creates the ConfigMap |
| caCertificates.existingConfigMap | string | `""` | Name of an existing ConfigMap of `*.pem` or `*.crt` files |
| credentials | object | `{"bearerTokens":"","databaseUrl":"","existingSecret":"","infrahubApiToken":"","postgresAdminPassword":"","prefectAuthString":"","prefectDatabaseUrl":"","prefectPassword":"","productPassword":"","s3AccessKey":"","s3SecretKey":""}` | Credentials of the deployment. Each key of the Secret is the variable name of the Compose `.env` file, so `kubectl create secret generic <name> --from-env-file=.env` creates it. |
| credentials.bearerTokens | string | `""` | `INFRAHUB_SYNC_SERVICE_BEARER_TOKENS`: a JSON object of API principals, for example `{"operator": {"token": "<random>", "administrator": true}}`. Required |
| credentials.databaseUrl | string | `""` | `INFRAHUB_SYNC_DATABASE_URL`: the product database connection string. Required with an external PostgreSQL |
| credentials.existingSecret | string | `""` | Name of an existing Secret that holds the credential keys. When set, the chart creates no Secret and the values below are not read |
| credentials.infrahubApiToken | string | `""` | `INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN`: the destination credential, given to the Sync API and the worker. Optional |
| credentials.postgresAdminPassword | string | `""` | `INFRAHUB_SYNC_POSTGRES_ADMIN_PASSWORD`: the PostgreSQL administrator password. Required with the bundled PostgreSQL |
| credentials.prefectAuthString | string | `""` | `INFRAHUB_SYNC_PREFECT_AUTH_STRING`: the Prefect API credential. Required |
| credentials.prefectDatabaseUrl | string | `""` | `INFRAHUB_SYNC_PREFECT_DATABASE_URL`: the Prefect database connection string. Required with an external PostgreSQL |
| credentials.prefectPassword | string | `""` | `INFRAHUB_SYNC_PREFECT_PASSWORD`: the password of the Prefect role. Required with the bundled PostgreSQL. It is used in a connection string, so it must be URL-safe |
| credentials.productPassword | string | `""` | `INFRAHUB_SYNC_PRODUCT_PASSWORD`: the password of the product role. Required with the bundled PostgreSQL. It is used in a connection string, so it must be URL-safe |
| credentials.s3AccessKey | string | `""` | `INFRAHUB_SYNC_S3_ACCESS_KEY`: the object store access key. Required |
| credentials.s3SecretKey | string | `""` | `INFRAHUB_SYNC_S3_SECRET_KEY`: the object store secret key. Required |
| fullnameOverride | string | `""` | Override the full name |
| gatewayApi | object | `{"enabled":false,"gateway":{"annotations":{},"className":"","enabled":false,"labels":{},"listeners":[],"name":""},"httpRoute":{"annotations":{},"extraRules":[],"hostnames":[],"labels":{},"name":"","parentRefs":[],"path":"/"}}` | Gateway API configuration for the Sync API. ref: https://gateway-api.sigs.k8s.io/ Mutually exclusive with `ingress`. |
| gatewayApi.enabled | bool | `false` | Whether to enable Gateway API HTTPRoute for the Sync API |
| gatewayApi.gateway.annotations | object | `{}` | Additional annotations for the Gateway resource |
| gatewayApi.gateway.className | string | `""` | GatewayClass name (required when gateway.enabled is true) |
| gatewayApi.gateway.enabled | bool | `false` | Whether to create a Gateway resource (most users reference an existing Gateway through httpRoute.parentRefs) |
| gatewayApi.gateway.labels | object | `{}` | Additional labels for the Gateway resource |
| gatewayApi.gateway.listeners | list | `[]` | Gateway listeners configuration. At least one is required when gateway.enabled is true |
| gatewayApi.gateway.name | string | `""` | Gateway resource name (defaults to "<fullname>-gateway") |
| gatewayApi.httpRoute.annotations | object | `{}` | Additional annotations for the HTTPRoute resource |
| gatewayApi.httpRoute.extraRules | list | `[]` | Additional HTTPRoute rules beyond the generated one |
| gatewayApi.httpRoute.hostnames | list | `[]` | Hostnames that this HTTPRoute should match |
| gatewayApi.httpRoute.labels | object | `{}` | Additional labels for the HTTPRoute resource |
| gatewayApi.httpRoute.name | string | `""` | HTTPRoute resource name (defaults to "<fullname>-httproute") |
| gatewayApi.httpRoute.parentRefs | list | `[]` | Parent Gateway references |
| gatewayApi.httpRoute.path | string | `"/"` | Path prefix for the default matching rule |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"registry.opsmill.io/opsmill/infrahub-sync","tag":""}` | Sync image, used by the Sync API, the worker, the Prefect server and the bootstrap Job |
| image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| image.repository | string | `"registry.opsmill.io/opsmill/infrahub-sync"` | Image repository |
| image.tag | string | `""` | Image tag, as a string: quote a numeric tag. Empty means the chart's `appVersion` |
| imagePullSecrets | list | `[]` | Image pull secrets, applied to every pod of the release |
| ingress | object | `{"annotations":{},"enabled":false,"extraHosts":[],"extraTls":[],"hostname":"","ingressClassName":"","path":"/","pathType":"Prefix","tls":false}` | Ingress for the Sync API. Mutually exclusive with `gatewayApi` |
| ingress.annotations | object | `{}` | Annotations to configure on the ingress |
| ingress.enabled | bool | `false` | Whether to enable Ingress for the Sync API |
| ingress.extraHosts | list | `[]` | Additional hosts to expose (each entry: hostname, path, pathType) |
| ingress.extraTls | list | `[]` | Additional TLS configuration entries (raw `tls` list items) |
| ingress.hostname | string | `""` | Hostname to configure for the ingress. Required when `ingress.enabled` is true |
| ingress.ingressClassName | string | `""` | IngressClass name to use |
| ingress.path | string | `"/"` | Path prefix under which the Sync API is exposed |
| ingress.pathType | string | `"Prefix"` | PathType for the ingress rule |
| ingress.tls | bool | `false` | Enable TLS for `hostname` using the secret "<fullname>-tls" |
| nameOverride | string | `""` | Override the chart name |
| objectStore | object | `{"affinity":{},"enabled":true,"image":{"digest":"sha256:2636fc4155d9a7e41ff58cdb65ddd13ba9304e67184e13c25bc5cb34016269d7","repository":"pgsty/silo","tag":"RELEASE.2026-10-18T00-00-00Z"},"nodeSelector":{},"persistence":{"size":"10Gi","storageClass":""},"podAnnotations":{},"podLabels":{},"resources":{},"tolerations":[]}` | The bundled object store (Silo, a maintained build of the MinIO server, AGPLv3) |
| objectStore.affinity | object | `{}` | Affinity rules |
| objectStore.enabled | bool | `true` | Deploy the bundled object store. When false, set `s3.endpointUrl` |
| objectStore.image | object | `{"digest":"sha256:2636fc4155d9a7e41ff58cdb65ddd13ba9304e67184e13c25bc5cb34016269d7","repository":"pgsty/silo","tag":"RELEASE.2026-10-18T00-00-00Z"}` | Object store image, pinned by digest as in `docker-compose.yml` |
| objectStore.image.digest | string | `"sha256:2636fc4155d9a7e41ff58cdb65ddd13ba9304e67184e13c25bc5cb34016269d7"` | Image digest |
| objectStore.image.repository | string | `"pgsty/silo"` | Image repository |
| objectStore.image.tag | string | `"RELEASE.2026-10-18T00-00-00Z"` | Image tag, as a string: quote a numeric tag |
| objectStore.nodeSelector | object | `{}` | Node selector |
| objectStore.persistence | object | `{"size":"10Gi","storageClass":""}` | Persistent volume of the object store |
| objectStore.persistence.size | string | `"10Gi"` | Size of the volume claim |
| objectStore.persistence.storageClass | string | `""` | Storage class of the volume claim. Empty means the cluster default |
| objectStore.podAnnotations | object | `{}` | Pod annotations |
| objectStore.podLabels | object | `{}` | Pod labels |
| objectStore.resources | object | `{}` | Resource requests and limits |
| objectStore.tolerations | list | `[]` | Tolerations |
| podSecurityContext | object | `{"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod security context of the Sync pods |
| postgresql | object | `{"adminRole":"postgres","affinity":{},"enabled":true,"image":{"digest":"sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685","repository":"postgres","tag":"16-alpine"},"nodeSelector":{},"persistence":{"size":"10Gi","storageClass":""},"podAnnotations":{},"podLabels":{},"prefectDatabase":"prefect","prefectRole":"prefect","productDatabase":"infrahub_sync","productRole":"infrahub_sync","resources":{},"tolerations":[]}` | The bundled PostgreSQL |
| postgresql.adminRole | string | `"postgres"` | Administrator role |
| postgresql.affinity | object | `{}` | Affinity rules |
| postgresql.enabled | bool | `true` | Deploy the bundled PostgreSQL. When false, set `credentials.databaseUrl` and `credentials.prefectDatabaseUrl`, or provide them in `credentials.existingSecret` |
| postgresql.image | object | `{"digest":"sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685","repository":"postgres","tag":"16-alpine"}` | PostgreSQL image, pinned by digest as in `docker-compose.yml` |
| postgresql.image.digest | string | `"sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"` | Image digest |
| postgresql.image.repository | string | `"postgres"` | Image repository |
| postgresql.image.tag | string | `"16-alpine"` | Image tag, as a string: quote a numeric tag |
| postgresql.nodeSelector | object | `{}` | Node selector |
| postgresql.persistence | object | `{"size":"10Gi","storageClass":""}` | Persistent volume of PostgreSQL |
| postgresql.persistence.size | string | `"10Gi"` | Size of the volume claim |
| postgresql.persistence.storageClass | string | `""` | Storage class of the volume claim. Empty means the cluster default |
| postgresql.podAnnotations | object | `{}` | Pod annotations |
| postgresql.podLabels | object | `{}` | Pod labels |
| postgresql.prefectDatabase | string | `"prefect"` | Prefect database |
| postgresql.prefectRole | string | `"prefect"` | Role that owns the Prefect database |
| postgresql.productDatabase | string | `"infrahub_sync"` | Product database |
| postgresql.productRole | string | `"infrahub_sync"` | Role that owns the product database |
| postgresql.resources | object | `{}` | Resource requests and limits |
| postgresql.tolerations | list | `[]` | Tolerations |
| prefectServer | object | `{"affinity":{},"extraEnv":[],"nodeSelector":{},"podAnnotations":{},"podLabels":{},"resources":{},"tolerations":[],"uiEnabled":false}` | The Prefect server, run from the Sync image |
| prefectServer.affinity | object | `{}` | Affinity rules |
| prefectServer.extraEnv | list | `[]` | Additional environment variables (a list of `env` entries) |
| prefectServer.nodeSelector | object | `{}` | Node selector |
| prefectServer.podAnnotations | object | `{}` | Pod annotations |
| prefectServer.podLabels | object | `{}` | Pod labels |
| prefectServer.resources | object | `{}` | Resource requests and limits |
| prefectServer.tolerations | list | `[]` | Tolerations |
| prefectServer.uiEnabled | bool | `false` | `PREFECT_UI_ENABLED`. The chart offers no route to the UI |
| s3 | object | `{"addressingStyle":"","bucket":"infrahub-sync","endpointUrl":"","prefix":"infrahub-sync","region":"us-east-1"}` | S3 settings of the Sync processes |
| s3.addressingStyle | string | `""` | `INFRAHUB_SYNC_S3_ADDRESSING_STYLE`: `path` or `virtual`. Empty means `path` |
| s3.bucket | string | `"infrahub-sync"` | `INFRAHUB_SYNC_S3_BUCKET` |
| s3.endpointUrl | string | `""` | `INFRAHUB_SYNC_S3_ENDPOINT_URL`. Required when `objectStore.enabled` is false; refused when it is true |
| s3.prefix | string | `"infrahub-sync"` | `INFRAHUB_SYNC_S3_PREFIX` |
| s3.region | string | `"us-east-1"` | `INFRAHUB_SYNC_S3_REGION` |
| securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | Container security context of the Sync containers |
| serviceAccount | object | `{"annotations":{},"create":true,"name":""}` | ServiceAccount configuration. No pod mounts its token |
| serviceAccount.annotations | object | `{}` | Annotations to add to the ServiceAccount |
| serviceAccount.create | bool | `true` | Create a ServiceAccount |
| serviceAccount.name | string | `""` | Name of the ServiceAccount (generated if empty) |
| settings | object | `{"prefectUiUrl":"","requireApproval":false,"runAdmissionTtlSeconds":300,"workPool":"infrahub-sync","workerHeartbeatSeconds":10,"workerQuerySeconds":10}` | Settings of the Sync processes |
| settings.prefectUiUrl | string | `""` | `INFRAHUB_SYNC_PREFECT_UI_URL`: the Prefect UI address that run responses link to. Empty turns the link off |
| settings.requireApproval | bool | `false` | `INFRAHUB_SYNC_REQUIRE_APPROVAL`: when true, `apply` refuses a plan without a matching approval, and `sync` is refused |
| settings.runAdmissionTtlSeconds | int | `300` | `INFRAHUB_SYNC_RUN_ADMISSION_TTL_SECONDS` |
| settings.workPool | string | `"infrahub-sync"` | `INFRAHUB_SYNC_SERVICE_WORK_POOL` and the worker's `--pool` |
| settings.workerHeartbeatSeconds | int | `10` | `PREFECT_WORKER_HEARTBEAT_SECONDS` |
| settings.workerQuerySeconds | int | `10` | `PREFECT_WORKER_QUERY_SECONDS` |
| waitTimeoutSeconds | int | `600` | How long the init containers of the Prefect server and the bootstrap Job wait for PostgreSQL and the Prefect server before they fail, in seconds |
| worker | object | `{"affinity":{},"credentials":{},"credentialsExistingSecrets":[],"extraEnv":[],"nodeSelector":{},"podAnnotations":{},"podLabels":{},"replicaCount":1,"resources":{},"tolerations":[]}` | The worker |
| worker.affinity | object | `{}` | Affinity rules |
| worker.credentials | object | `{}` | Worker credentials, `INFRAHUB_SYNC_CREDENTIAL_<NAME>` to value. The chart creates a Secret that only the worker reads |
| worker.credentialsExistingSecrets | list | `[]` | Names of existing Secrets whose keys are passed to the worker as variables |
| worker.extraEnv | list | `[]` | Additional environment variables (a list of `env` entries) |
| worker.nodeSelector | object | `{}` | Node selector |
| worker.podAnnotations | object | `{}` | Pod annotations |
| worker.podLabels | object | `{}` | Pod labels |
| worker.replicaCount | int | `1` | Number of replicas. One is the only tested value |
| worker.resources | object | `{}` | Resource requests and limits |
| worker.tolerations | list | `[]` | Tolerations |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.
