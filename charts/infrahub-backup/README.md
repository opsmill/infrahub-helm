# infrahub-backup

Backup and restore Helm chart for Infrahub on Kubernetes

**Homepage:** <https://github.com/opsmill/infrahub-helm>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| OpsMill |  | <https://github.com/opsmill> |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` | Affinity rules for pod scheduling |
| backup | object | `{"enabled":false,"mode":"job","options":{"excludeTaskmanager":false,"extraArgs":[],"force":false,"keepLocal":false,"neo4jMetadata":"all","sleep":"3m"},"schedule":"0 2 * * *","storage":{"local":{},"path":"/infrahub_backups","s3":{"bucket":"","endpoint":"","prefix":"","region":"us-east-1","secretName":""},"type":"s3"}}` | Backup configuration |
| backup.enabled | bool | `false` | Enable backup functionality |
| backup.mode | string | `"job"` | Backup mode: "job" for one-shot, "cronjob" for scheduled |
| backup.options | object | `{"excludeTaskmanager":false,"extraArgs":[],"force":false,"keepLocal":false,"neo4jMetadata":"all","sleep":"3m"}` | Backup options |
| backup.options.excludeTaskmanager | bool | `false` | Exclude task-manager database from backup |
| backup.options.extraArgs | list | `[]` | Extra arguments to pass to the backup command |
| backup.options.force | bool | `false` | Force backup even if another backup is in progress |
| backup.options.keepLocal | bool | `false` | Keep local file after S3 upload (only applies when storage.type is "s3") |
| backup.options.neo4jMetadata | string | `"all"` | Neo4j metadata to include: "all", "none", or specific types |
| backup.options.sleep | string | `"3m"` | Sleep duration after backup when using local storage (allows time to copy files) |
| backup.schedule | string | `"0 2 * * *"` | Schedule for CronJob mode (cron expression) |
| backup.storage | object | `{"local":{},"path":"/infrahub_backups","s3":{"bucket":"","endpoint":"","prefix":"","region":"us-east-1","secretName":""},"type":"s3"}` | Storage configuration |
| backup.storage.local | object | `{}` | Local storage settings |
| backup.storage.path | string | `"/infrahub_backups"` | Path within the pod to store backups |
| backup.storage.s3 | object | `{"bucket":"","endpoint":"","prefix":"","region":"us-east-1","secretName":""}` | S3 storage settings |
| backup.storage.s3.bucket | string | `""` | S3 bucket name |
| backup.storage.s3.endpoint | string | `""` | S3 endpoint URL (for non-AWS S3-compatible storage like MinIO) |
| backup.storage.s3.prefix | string | `""` | S3 key prefix for backup artifacts |
| backup.storage.s3.region | string | `"us-east-1"` | S3 region |
| backup.storage.s3.secretName | string | `""` | Name of Kubernetes Secret containing AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY |
| backup.storage.type | string | `"s3"` | Storage type: "s3" or "local" |
| cronJob | object | `{"concurrencyPolicy":"Forbid","failedJobsHistoryLimit":3,"startingDeadlineSeconds":null,"successfulJobsHistoryLimit":3,"suspend":false}` | CronJob specific settings |
| cronJob.concurrencyPolicy | string | `"Forbid"` | Concurrency policy: "Forbid", "Replace", or "Allow" |
| cronJob.failedJobsHistoryLimit | int | `3` | Number of failed job history to keep |
| cronJob.startingDeadlineSeconds | string | `nil` | Job deadline in seconds (optional) |
| cronJob.successfulJobsHistoryLimit | int | `3` | Number of successful job history to keep |
| cronJob.suspend | bool | `false` | Suspend the CronJob (useful for maintenance) |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"registry.opsmill.io/opsmill/infrahub-backup","tag":""}` | Container image configuration |
| image.tag | string | `""` | Tag defaults to chart appVersion if not specified |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries |
| job | object | `{"activeDeadlineSeconds":null,"backoffLimit":0,"ttlSecondsAfterFinished":null}` | Job specific settings |
| job.activeDeadlineSeconds | string | `nil` | Active deadline in seconds (optional) |
| job.backoffLimit | int | `0` | Number of retries before marking job as failed |
| job.ttlSecondsAfterFinished | string | `nil` | Time to live after job completion (seconds, null to keep indefinitely) |
| nodeSelector | object | `{}` | Node selector for pod scheduling |
| podSecurityContext | object | `{"runAsNonRoot":true,"runAsUser":1000}` | Pod security context |
| rbac | object | `{"create":true}` | RBAC configuration |
| rbac.create | bool | `true` | Create Role and RoleBinding for pod exec permissions |
| resources | object | `{"requests":{"cpu":"100m","memory":"256Mi"}}` | Resource limits and requests |
| restore | object | `{"enabled":false,"mode":"job","options":{"excludeTaskmanager":false,"extraArgs":[],"migrateFormat":false,"sleep":"3m"},"schedule":"0 4 * * *","storage":{"local":{"filename":"infrahub_backup_latest.tar.gz"},"path":"/infrahub_backups","s3":{"bucket":"","endpoint":"","key":"","latest":false,"prefix":"","region":"us-east-1","secretName":""},"type":"s3"}}` | Restore configuration |
| restore.enabled | bool | `false` | Enable restore functionality (mutually exclusive with backup) |
| restore.mode | string | `"job"` | Restore mode: "job" for one-shot, "cronjob" for scheduled (e.g. a nightly prod -> staging sync) |
| restore.options | object | `{"excludeTaskmanager":false,"extraArgs":[],"migrateFormat":false,"sleep":"3m"}` | Restore options |
| restore.options.excludeTaskmanager | bool | `false` | Exclude task-manager database from restore |
| restore.options.extraArgs | list | `[]` | Extra arguments to pass to the restore command |
| restore.options.migrateFormat | bool | `false` | Migrate backup format from older versions |
| restore.options.sleep | string | `"3m"` | Sleep duration before restore when using local storage (allows time to copy files) |
| restore.schedule | string | `"0 4 * * *"` | Schedule for CronJob mode (cron expression) |
| restore.storage | object | `{"local":{"filename":"infrahub_backup_latest.tar.gz"},"path":"/infrahub_backups","s3":{"bucket":"","endpoint":"","key":"","latest":false,"prefix":"","region":"us-east-1","secretName":""},"type":"s3"}` | Storage configuration |
| restore.storage.local | object | `{"filename":"infrahub_backup_latest.tar.gz"}` | Local storage settings |
| restore.storage.local.filename | string | `"infrahub_backup_latest.tar.gz"` | File name of the backup to restore |
| restore.storage.path | string | `"/infrahub_backups"` | Path within the pod to store backups |
| restore.storage.s3 | object | `{"bucket":"","endpoint":"","key":"","latest":false,"prefix":"","region":"us-east-1","secretName":""}` | S3 artifact location |
| restore.storage.s3.bucket | string | `""` | S3 bucket containing the backup |
| restore.storage.s3.endpoint | string | `""` | S3 endpoint URL (for non-AWS S3-compatible storage) |
| restore.storage.s3.key | string | `""` | S3 key (path) to the backup artifact (exactly one of key or latest must be set) |
| restore.storage.s3.latest | bool | `false` | Restore the newest backup under bucket/prefix instead of naming one (exactly one of key or latest must be set) |
| restore.storage.s3.prefix | string | `""` | S3 key prefix the backups live under (only used with latest; match the source's backup.storage.s3.prefix) |
| restore.storage.s3.region | string | `"us-east-1"` | S3 region |
| restore.storage.s3.secretName | string | `""` | Name of Kubernetes Secret containing AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY |
| restore.storage.type | string | `"s3"` | Storage type: "s3" or "local" ("cronjob" mode requires "s3") |
| securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":false}` | Container security context |
| serviceAccount | object | `{"annotations":{},"create":true,"name":""}` | ServiceAccount configuration |
| serviceAccount.annotations | object | `{}` | Annotations to add to the ServiceAccount |
| serviceAccount.create | bool | `true` | Create a ServiceAccount for the backup/restore pods |
| serviceAccount.name | string | `""` | Name of the ServiceAccount (auto-generated if empty) |
| tolerations | list | `[]` | Tolerations for pod scheduling |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

For more detailed configuration and additional parameters, refer to the `values.yaml` file.

