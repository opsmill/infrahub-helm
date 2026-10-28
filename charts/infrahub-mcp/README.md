# infrahub-mcp

Helm chart for Infrahub MCP Server on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

## Production example

The defaults (`mcp.authMode: none`, `mcp.readOnly: false`) give every client that
reaches the MCP server read and write access through one shared API token. For a
production deployment, require each client to send its own Infrahub API token,
block write operations, and serve the MCP server under `/mcp` on the Infrahub
host.

Create the Secret that holds the API token:

```sh
kubectl create secret generic infrahub-mcp-api-token -n infrahub \
  --from-literal=INFRAHUB_API_TOKEN=<api-token>
```

Then install the chart with these values:

```yaml
infrahub:
  # In-cluster URL of the Infrahub server: http://<infrahub-release>-infrahub-server:8000
  address: "http://infrahub-infrahub-server:8000"
  apiToken:
    # The server uses this token only when `mcp.authMode` is "none" or "oidc".
    # In "token-passthrough" mode it calls Infrahub with each client's token.
    existingSecret: infrahub-mcp-api-token
    existingSecretKey: INFRAHUB_API_TOKEN

mcp:
  # Each request must carry an Infrahub API token in the `Authorization` header.
  authMode: "token-passthrough"
  # Hide write tools and block GraphQL mutations.
  readOnly: true

ingress:
  enabled: true
  ingressClassName: nginx
  # The Infrahub server's ingress hostname
  hostname: infrahub.example.com
  path: /mcp
  pathType: Prefix
  tls: true
```

When you install the MCP server with the `infrahub` or `infrahub-enterprise`
chart, set `infrahub-mcp.enabled: true` and put these values under the
`infrahub-mcp:` key (`infrahub.infrahub-mcp:` for `infrahub-enterprise`).

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| OpsMill |  | <https://github.com/opsmill> |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` | Affinity rules for pod scheduling |
| envFromExistingSecrets | list | `[]` | Name of existing Secret(s) to load as environment variables |
| extraEnv | object | `{}` | Additional environment variables (key: value pairs) |
| fullnameOverride | string | `""` | Override the full name |
| gatewayApi | object | `{"enabled":false,"gateway":{"annotations":{},"className":"","enabled":false,"labels":{},"listeners":[],"name":""},"httpRoute":{"annotations":{},"extraRules":[],"hostnames":[],"labels":{},"name":"","parentRefs":[],"path":"/mcp"}}` | Gateway API configuration for the MCP server. ref: https://gateway-api.sigs.k8s.io/ Mutually exclusive with `ingress`. |
| gatewayApi.enabled | bool | `false` | Whether to enable Gateway API HTTPRoute for the MCP server |
| gatewayApi.gateway.annotations | object | `{}` | Additional annotations for the Gateway resource |
| gatewayApi.gateway.className | string | `""` | GatewayClass name (required when gateway.enabled is true) |
| gatewayApi.gateway.enabled | bool | `false` | Whether to create a Gateway resource (most users will reference an existing Gateway via httpRoute.parentRefs) |
| gatewayApi.gateway.labels | object | `{}` | Additional labels for the Gateway resource |
| gatewayApi.gateway.listeners | list | `[]` | Gateway listeners configuration |
| gatewayApi.gateway.name | string | `""` | Gateway resource name (defaults to "<fullname>-gateway") |
| gatewayApi.httpRoute.annotations | object | `{}` | Additional annotations for the HTTPRoute resource |
| gatewayApi.httpRoute.extraRules | list | `[]` | Additional HTTPRoute rules beyond the auto-generated one |
| gatewayApi.httpRoute.hostnames | list | `[]` | Hostnames that this HTTPRoute should match |
| gatewayApi.httpRoute.labels | object | `{}` | Additional labels for the HTTPRoute resource |
| gatewayApi.httpRoute.name | string | `""` | HTTPRoute resource name (defaults to "<fullname>-httproute") |
| gatewayApi.httpRoute.parentRefs | list | `[]` | Parent Gateway references |
| gatewayApi.httpRoute.path | string | `"/mcp"` | Path prefix for the default matching rule |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"registry.opsmill.io/opsmill/infrahub-mcp","tag":""}` | Container image configuration |
| image.tag | string | `""` | Tag defaults to chart appVersion if not specified |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries |
| infrahub | object | `{"address":"","apiToken":{"existingSecret":"","existingSecretKey":"INFRAHUB_API_TOKEN","value":""},"password":{"existingSecret":"","existingSecretKey":"INFRAHUB_PASSWORD","value":""},"username":""}` | Infrahub connection settings |
| infrahub.address | string | `""` | Infrahub server address (e.g. "http://infrahub-infrahub-server:8000") |
| infrahub.apiToken | object | `{"existingSecret":"","existingSecretKey":"INFRAHUB_API_TOKEN","value":""}` | API token for authenticating with Infrahub |
| infrahub.apiToken.existingSecret | string | `""` | Name of an existing Secret containing the API token. Takes precedence over `value` when set. |
| infrahub.apiToken.existingSecretKey | string | `"INFRAHUB_API_TOKEN"` | Key within the existing Secret that holds the API token |
| infrahub.apiToken.value | string | `""` | API token value, rendered as a plain-text env var. Prefer `existingSecret` for production deployments. |
| infrahub.password | object | `{"existingSecret":"","existingSecretKey":"INFRAHUB_PASSWORD","value":""}` | Password for `username` |
| infrahub.password.existingSecret | string | `""` | Name of an existing Secret containing the password. Takes precedence over `value` when set. |
| infrahub.password.existingSecretKey | string | `"INFRAHUB_PASSWORD"` | Key within the existing Secret that holds the password |
| infrahub.password.value | string | `""` | Password value, rendered as a plain-text env var. Prefer `existingSecret` for production deployments. |
| infrahub.username | string | `""` | Infrahub username. Set it with `password` instead of `apiToken`; the server refuses to start when both are set. |
| ingress | object | `{"annotations":{},"enabled":false,"extraHosts":[],"extraTls":[],"hostname":"","ingressClassName":"","path":"/mcp","pathType":"Prefix","tls":false}` | Ingress configuration for exposing the MCP server externally. To serve the MCP server on the same host as Infrahub (e.g. under a "/mcp" path prefix), set `hostname` to the Infrahub server's ingress hostname and keep the default `path`. |
| ingress.annotations | object | `{}` | Annotations to configure on the ingress |
| ingress.enabled | bool | `false` | Whether to enable Ingress for the MCP server |
| ingress.extraHosts | list | `[]` | Additional hosts to expose (each entry: hostname, path, pathType) |
| ingress.extraTls | list | `[]` | Additional TLS configuration entries (raw `tls` list items) |
| ingress.hostname | string | `""` | Hostname to configure for the ingress |
| ingress.ingressClassName | string | `""` | IngressClass name to use |
| ingress.path | string | `"/mcp"` | Path prefix under which the MCP server is exposed |
| ingress.pathType | string | `"Prefix"` | PathType for the ingress rule |
| ingress.tls | bool | `false` | Enable TLS for `hostname` using the secret "<fullname>-tls" |
| livenessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/health","port":"http"},"initialDelaySeconds":5,"periodSeconds":10,"timeoutSeconds":5}` | Liveness probe configuration |
| mcp | object | `{"authMode":"none","authScopesWrite":"write","branching":{"maxRetries":5,"pattern":"mcp/session-{date}-{hex}"},"cache":{"enabled":false,"listTtl":300,"readTtl":3600},"dereferenceSchemas":false,"host":"0.0.0.0","logLevel":"info","observability":{"otelEnabled":false,"pingIntervalMs":0,"prometheusEnabled":false},"oidc":{"audience":"","baseUrl":"","clientId":"","clientSecret":{"existingSecret":"","existingSecretKey":"INFRAHUB_MCP_OIDC_CLIENT_SECRET","value":""},"configUrl":"","userClaim":"email"},"rateLimit":{"burst":0,"rps":0},"readOnly":false,"retry":{"baseDelay":1,"maxAttempts":0},"schemaExpandPeers":true,"tokenPassthroughHeader":"Authorization"}` | MCP server configuration |
| mcp.authMode | string | `"none"` | Authentication mode: "none", "token-passthrough", "basic-passthrough", "oidc" |
| mcp.authScopesWrite | string | `"write"` | OAuth scopes (comma-separated) a client token must hold to call write tools |
| mcp.branching | object | `{"maxRetries":5,"pattern":"mcp/session-{date}-{hex}"}` | Branching configuration |
| mcp.branching.maxRetries | int | `5` | Max retries for branch creation on name collision |
| mcp.branching.pattern | string | `"mcp/session-{date}-{hex}"` | Branch name pattern for auto-created branches |
| mcp.cache | object | `{"enabled":false,"listTtl":300,"readTtl":3600}` | Caching configuration |
| mcp.cache.enabled | bool | `false` | Enable response caching |
| mcp.cache.listTtl | int | `300` | TTL in seconds for list operations |
| mcp.cache.readTtl | int | `3600` | TTL in seconds for read operations |
| mcp.dereferenceSchemas | bool | `false` | Enable JSON $ref dereferencing in schemas |
| mcp.host | string | `"0.0.0.0"` | Address the HTTP server binds to. The port is `service.targetPort`. |
| mcp.logLevel | string | `"info"` | Log level: "debug", "info", "warning", "error" |
| mcp.observability | object | `{"otelEnabled":false,"pingIntervalMs":0,"prometheusEnabled":false}` | Observability configuration |
| mcp.observability.otelEnabled | bool | `false` | Enable OpenTelemetry tracing |
| mcp.observability.pingIntervalMs | int | `0` | Ping keepalive interval in milliseconds (0 = disabled) |
| mcp.observability.prometheusEnabled | bool | `false` | Enable Prometheus metrics endpoint |
| mcp.oidc | object | `{"audience":"","baseUrl":"","clientId":"","clientSecret":{"existingSecret":"","existingSecretKey":"INFRAHUB_MCP_OIDC_CLIENT_SECRET","value":""},"configUrl":"","userClaim":"email"}` | OIDC configuration, used when `authMode` is "oidc" |
| mcp.oidc.audience | string | `""` | Expected token audience claim |
| mcp.oidc.baseUrl | string | `""` | Public URL where clients reach the MCP server (required when `authMode` is "oidc") |
| mcp.oidc.clientId | string | `""` | OAuth client ID registered with the identity provider (required when `authMode` is "oidc") |
| mcp.oidc.clientSecret | object | `{"existingSecret":"","existingSecretKey":"INFRAHUB_MCP_OIDC_CLIENT_SECRET","value":""}` | OAuth client secret. Leave empty to use PKCE. |
| mcp.oidc.clientSecret.existingSecret | string | `""` | Name of an existing Secret containing the client secret. Takes precedence over `value` when set. |
| mcp.oidc.clientSecret.existingSecretKey | string | `"INFRAHUB_MCP_OIDC_CLIENT_SECRET"` | Key within the existing Secret that holds the client secret |
| mcp.oidc.clientSecret.value | string | `""` | Client secret value, rendered as a plain-text env var. Prefer `existingSecret` for production deployments. |
| mcp.oidc.configUrl | string | `""` | OIDC discovery URL (required when `authMode` is "oidc") |
| mcp.oidc.userClaim | string | `"email"` | JWT claim used as the user identity |
| mcp.rateLimit | object | `{"burst":0,"rps":0}` | Rate limiting configuration |
| mcp.rateLimit.burst | int | `0` | Burst allowance (0 = twice `rps`) |
| mcp.rateLimit.rps | int | `0` | Requests per second (0 = disabled) |
| mcp.readOnly | bool | `false` | Enable read-only mode (blocks all write operations) |
| mcp.retry | object | `{"baseDelay":1,"maxAttempts":0}` | Retry configuration |
| mcp.retry.baseDelay | int | `1` | Base delay between retries in seconds |
| mcp.retry.maxAttempts | int | `0` | Max retry attempts (0 = disabled) |
| mcp.schemaExpandPeers | bool | `true` | Include one level of related peer schemas in schema detail responses. When false, relationships are returned as flat peer references. |
| mcp.tokenPassthroughHeader | string | `"Authorization"` | HTTP header that carries the client's credential when `authMode` is "token-passthrough" or "basic-passthrough" |
| nameOverride | string | `""` | Override the chart name |
| nodeSelector | object | `{}` | Node selector for pod scheduling |
| podAnnotations | object | `{}` | Pod annotations |
| podLabels | object | `{}` | Pod labels |
| podSecurityContext | object | `{"runAsNonRoot":true,"runAsUser":1000}` | Pod security context |
| readinessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/health","port":"http"},"initialDelaySeconds":5,"periodSeconds":10,"timeoutSeconds":5}` | Readiness probe configuration |
| replicaCount | int | `1` | Number of replicas |
| resources | object | `{}` | Resource limits and requests |
| securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | Container security context |
| service | object | `{"port":8001,"targetPort":8001,"type":"ClusterIP"}` | Service configuration |
| service.port | int | `8001` | Service port |
| service.targetPort | int | `8001` | Container target port |
| service.type | string | `"ClusterIP"` | Service type |
| serviceAccount | object | `{"annotations":{},"create":true,"name":""}` | ServiceAccount configuration |
| serviceAccount.annotations | object | `{}` | Annotations to add to the ServiceAccount |
| serviceAccount.create | bool | `true` | Create a ServiceAccount |
| serviceAccount.name | string | `""` | Name of the ServiceAccount (auto-generated if empty) |
| tolerations | list | `[]` | Tolerations for pod scheduling |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.
