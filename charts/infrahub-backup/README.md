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
| backup.storage.s3.endpoint | string | `""` | S3 endpoint URL (for S3-compatible storage other than AWS S3) |
| backup.storage.s3.prefix | string | `""` | S3 key prefix for backup artifacts |
| backup.storage.s3.region | string | `"us-east-1"` | S3 region |
| backup.storage.s3.secretName | string | `""` | Name of Kubernetes Secret containing AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY |
| backup.storage.type | string | `"s3"` | Storage type: "s3" or "local" |
| cronJob | object | `{"concurrencyPolicy":"Forbid","failedJobsHistoryLimit":3,"startingDeadlineSeconds":null,"successfulJobsHistoryLimit":3,"suspend":false,"timeZone":""}` | CronJob specific settings |
| cronJob.concurrencyPolicy | string | `"Forbid"` | Concurrency policy: "Forbid", "Replace", or "Allow" |
| cronJob.failedJobsHistoryLimit | int | `3` | Number of failed job history to keep |
| cronJob.startingDeadlineSeconds | string | `nil` | Job deadline in seconds (optional) |
| cronJob.successfulJobsHistoryLimit | int | `3` | Number of successful job history to keep |
| cronJob.suspend | bool | `false` | Suspend the CronJob (useful for maintenance) |
| cronJob.timeZone | string | `""` | Time zone for `backup.schedule` and `restore.schedule`, as an IANA name such as "Europe/Zurich". Empty uses the time zone of the kube-controller-manager, usually UTC. |
| externalDatabase | object | `{"allowRestore":false,"insecureTLS":false,"neo4jAddress":"","neo4jBackupPort":"","postgresAddress":"","scratchSize":"","timeout":""}` | Settings for a Neo4j or PostgreSQL database that runs outside the Infrahub namespace. They have no effect on a database that runs in the namespace. The backup and restore pods run in the Infrahub namespace, so infrahub-backup runs `neo4j-admin`, `cypher-shell` and the PostgreSQL client in its own container, and creates no Job and no Secret. Needs an infrahub-backup image with external database support. |
| externalDatabase.allowRestore | bool | `false` | Allow a restore to overwrite an external database. Sets `INFRAHUB_ALLOW_EXTERNAL_RESTORE` on the restore containers only. A restore of an external Neo4j database also needs `restore.storage.type: s3`: infrahub-backup copies the artifact under `seed/` in `restore.storage.s3.bucket`, and the Neo4j servers download it from there. So the credentials in `restore.storage.s3.secretName` must be able to write to that bucket, also with `restore.storage.s3.key`, and the Neo4j servers must be able to read from it. |
| externalDatabase.insecureTLS | bool | `false` | Connect to an external database without verifying its certificate, and accept a connection with no encryption when the deployment has TLS disabled. Sets `INFRAHUB_EXTERNAL_DB_INSECURE_TLS`. An external Neo4j server with TLS disabled needs it. |
| externalDatabase.neo4jAddress | string | `""` | Neo4j hosts to back up from, as "host[:port][,host[:port]...]". Sets `INFRAHUB_NEO4J_ADDRESS`. Empty uses the address the Infrahub server is configured with. For a Neo4j cluster, list every member, so that the backup can use another member when one is down. |
| externalDatabase.neo4jBackupPort | string | `""` | Port of the Neo4j backup service on every host, not the Bolt port. Sets `INFRAHUB_NEO4J_BACKUP_PORT`. Empty uses the infrahub-backup default, 6362. |
| externalDatabase.postgresAddress | string | `""` | PostgreSQL endpoint of the task manager database, as "host[:port]". Sets `INFRAHUB_POSTGRES_ADDRESS`. Empty uses the address the task manager is configured with. |
| externalDatabase.scratchSize | string | `""` | Free disk space that a capture of an external database needs, such as "20Gi". Sets `INFRAHUB_EXTERNAL_DB_SCRATCH_SIZE`. Empty derives it from the database size, which Neo4j 2025 does not report. infrahub-backup writes the capture under `TMPDIR` (`/tmp` when unset): to use a larger volume, add it with `extraVolumes` and `extraVolumeMounts`, and set `TMPDIR` to its mount path with `extraEnv`. |
| externalDatabase.timeout | string | `""` | Time limit for each operation against an external database, with a unit such as "4h" or "90m". Sets `INFRAHUB_EXTERNAL_DB_TIMEOUT`. Empty uses the infrahub-backup default, 2h. |
| extraEnv | list | `[]` | Extra environment variables for the backup and restore containers, appended after the ones the chart sets. For example, trust a private CA for an S3 endpoint with a self-signed or internal certificate: `[{name: SSL_CERT_FILE, value: /etc/ssl/custom/ca.crt}]` together with the volume below. |
| extraVolumeMounts | list | `[]` | Extra volume mounts for the backup and restore containers: `[{name: s3-ca, mountPath: /etc/ssl/custom, readOnly: true}]` |
| extraVolumes | list | `[]` | Extra volumes for the backup and restore pods, for example a ConfigMap holding a CA certificate: `[{name: s3-ca, configMap: {name: s3-ca}}]` |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"registry.opsmill.io/opsmill/infrahub-backup","tag":""}` | Container image configuration |
| image.tag | string | `""` | Tag defaults to chart appVersion if not specified |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries |
| job | object | `{"activeDeadlineSeconds":null,"backoffLimit":0,"ttlSecondsAfterFinished":null}` | Job specific settings |
| job.activeDeadlineSeconds | string | `nil` | Active deadline in seconds (optional) |
| job.backoffLimit | int | `0` | Number of retries before marking job as failed |
| job.ttlSecondsAfterFinished | string | `nil` | Time to live after job completion (seconds, null to keep indefinitely) |
| nodeSelector | object | `{}` | Node selector for pod scheduling |
| podSecurityContext | object | `{"runAsNonRoot":true,"runAsUser":1000}` | Pod security context |
| priorityClassName | string | `""` | Priority class for the backup and restore pods. A backup or restore stops Infrahub while it runs, so a pod that is preempted midway leaves Infrahub stopped. |
| rbac | object | `{"create":true}` | RBAC configuration |
| rbac.create | bool | `true` | Create Role and RoleBinding for pod exec permissions |
| resources | object | `{"requests":{"cpu":"100m","memory":"256Mi"}}` | Resource limits and requests |
| restore | object | `{"enabled":false,"mode":"job","options":{"excludeTaskmanager":false,"extraArgs":[],"migrateFormat":false,"neo4jClusterOnlineTimeout":"","sleep":"3m"},"schedule":"0 4 * * *","storage":{"local":{"filename":"infrahub_backup_latest.tar.gz"},"path":"/infrahub_backups","s3":{"bucket":"","endpoint":"","key":"","latest":false,"prefix":"","region":"us-east-1","secretName":""},"type":"s3"}}` | Restore configuration |
| restore.enabled | bool | `false` | Enable restore functionality (mutually exclusive with backup) |
| restore.mode | string | `"job"` | Restore mode: "job" for one-shot, "cronjob" for scheduled (e.g. a nightly prod -> staging sync) |
| restore.options | object | `{"excludeTaskmanager":false,"extraArgs":[],"migrateFormat":false,"neo4jClusterOnlineTimeout":"","sleep":"3m"}` | Restore options |
| restore.options.excludeTaskmanager | bool | `false` | Exclude task-manager database from restore |
| restore.options.extraArgs | list | `[]` | Extra arguments to pass to the restore command |
| restore.options.migrateFormat | bool | `false` | Migrate backup format from older versions |
| restore.options.neo4jClusterOnlineTimeout | string | `""` | With a Neo4j cluster, how long the restore waits for the database to come online on every server, such as "15m". Passes `--neo4j-cluster-online-timeout`, which needs infrahub-backup 2.4.1 or later. Empty uses the infrahub-backup default. |
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
| restore.storage.s3.prefix | string | `""` | S3 key prefix the backups live under (with latest, match the source's backup.storage.s3.prefix). A restore of an external Neo4j database also copies the artifact under `<prefix>/seed/`, so it needs write access to the bucket |
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

