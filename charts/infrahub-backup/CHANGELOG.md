## [infrahub-backup-1.3.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-backup-1.3.0) - 2026-08-05

### Added

- Added a scheduled restore mode: `restore.mode=cronjob` with `restore.schedule` renders a CronJob instead of a one-shot Job, and `restore.storage.s3.latest=true` (with the new `restore.storage.s3.prefix`) restores the newest backup under the bucket/prefix instead of naming an exact archive — enabling an unattended, recurring prod → staging sync. The bundled `infrahub-backup` image was bumped to `2.3.0`, which provides the required `restore --latest` support. Invalid combinations (both or neither of `key`/`latest`, cronjob mode with local storage, cronjob restore alongside `backup.enabled`) now fail at render time. ([#80](https://github.com/opsmill/infrahub-helm/issues/80))

## [infrahub-backup-1.2.1](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-backup-1.2.1) - 2026-06-26

### Fixed

- Bumped the `infrahub-backup` image to `1.7.4`, which fixes backup and restore Jobs failing against the task-manager PostgreSQL with `password authentication failed for user "postgres"`.
