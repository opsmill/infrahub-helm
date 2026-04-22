# infrahub-mcp

Helm chart for Infrahub MCP Server on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

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
| image | object | `{"pullPolicy":"IfNotPresent","repository":"registry.opsmill.io/opsmill/infrahub-mcp","tag":""}` | Container image configuration |
| image.tag | string | `""` | Tag defaults to chart appVersion if not specified |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries |
| infrahub | object | `{"address":"","apiToken":"","existingSecret":"","existingSecretKey":"INFRAHUB_API_TOKEN"}` | Infrahub connection settings |
| infrahub.address | string | `""` | Infrahub server address (auto-configured when used as sub-chart) |
| infrahub.apiToken | string | `""` | API token for authenticating with Infrahub |
| infrahub.existingSecret | string | `""` | Name of an existing Secret containing INFRAHUB_API_TOKEN |
| infrahub.existingSecretKey | string | `"INFRAHUB_API_TOKEN"` | Key within the existing Secret that holds the API token |
| livenessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/health","port":"http"},"initialDelaySeconds":5,"periodSeconds":10,"timeoutSeconds":5}` | Liveness probe configuration |
| mcp | object | `{"authMode":"none","branching":{"maxRetries":5,"pattern":"mcp/session-{date}-{hex}"},"cache":{"enabled":false,"listTtl":300,"readTtl":3600},"dereferenceSchemas":false,"logLevel":"info","observability":{"otelEnabled":false,"pingIntervalMs":0,"prometheusEnabled":false},"rateLimit":{"burst":0,"rps":0},"readOnly":false,"retry":{"baseDelay":1,"maxAttempts":0}}` | MCP server configuration |
| mcp.authMode | string | `"none"` | Authentication mode: "none", "token-passthrough", "basic-passthrough", "oidc" |
| mcp.branching | object | `{"maxRetries":5,"pattern":"mcp/session-{date}-{hex}"}` | Branching configuration |
| mcp.branching.maxRetries | int | `5` | Max retries for branch creation on name collision |
| mcp.branching.pattern | string | `"mcp/session-{date}-{hex}"` | Branch name pattern for auto-created branches |
| mcp.cache | object | `{"enabled":false,"listTtl":300,"readTtl":3600}` | Caching configuration |
| mcp.cache.enabled | bool | `false` | Enable response caching |
| mcp.cache.listTtl | int | `300` | TTL in seconds for list operations |
| mcp.cache.readTtl | int | `3600` | TTL in seconds for read operations |
| mcp.dereferenceSchemas | bool | `false` | Enable JSON $ref dereferencing in schemas |
| mcp.logLevel | string | `"info"` | Log level: "debug", "info", "warning", "error" |
| mcp.observability | object | `{"otelEnabled":false,"pingIntervalMs":0,"prometheusEnabled":false}` | Observability configuration |
| mcp.observability.otelEnabled | bool | `false` | Enable OpenTelemetry tracing |
| mcp.observability.pingIntervalMs | int | `0` | Ping keepalive interval in milliseconds (0 = disabled) |
| mcp.observability.prometheusEnabled | bool | `false` | Enable Prometheus metrics endpoint |
| mcp.rateLimit | object | `{"burst":0,"rps":0}` | Rate limiting configuration |
| mcp.rateLimit.burst | int | `0` | Burst allowance (0 = disabled) |
| mcp.rateLimit.rps | int | `0` | Requests per second (0 = disabled) |
| mcp.readOnly | bool | `false` | Enable read-only mode (blocks all write operations) |
| mcp.retry | object | `{"baseDelay":1,"maxAttempts":0}` | Retry configuration |
| mcp.retry.baseDelay | int | `1` | Base delay between retries in seconds |
| mcp.retry.maxAttempts | int | `0` | Max retry attempts (0 = disabled) |
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
