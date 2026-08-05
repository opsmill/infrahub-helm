## [infrahub-enterprise-4.18.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.18.0) - 2026-08-05

### Changed

- Bumped the bundled `infrahub` dependency to `4.32.0`, which picks up the `infrahub-backup` `1.3.0` bump adding a scheduled restore mode: `infrahub.infrahub-backup.restore.mode=cronjob` with `infrahub.infrahub-backup.restore.schedule` renders a CronJob instead of a one-shot Job, and `infrahub.infrahub-backup.restore.storage.s3.latest=true` restores the newest backup under the bucket/prefix instead of naming an exact archive.

## [infrahub-enterprise-4.17.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.17.0) - 2026-08-03

### Added

- Bumped the `infrahub` dependency to 4.31.0, which adds `infrahub.upgrade.extraArgs` to pass additional arguments to the `infrahub upgrade` command run by the upgrade hook job, such as `--rebase-branches` to rebase open branches after migrations that require it.

## [infrahub-enterprise-4.16.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.16.0) - 2026-07-24

### Added

- Bumped the `infrahub` dependency to 4.30.0, which adds `global.infrahubImageFlavor` to select a flavored Infrahub image (for example `avd`) without pinning the image tag. When set, the flavor is appended to the resolved image tag as `<tag>-<flavor>`, whether the tag comes from `global.infrahubTag` or defaults to the chart `appVersion`, so upgrading the chart alone is enough to track new versions. ([#79](https://github.com/opsmill/infrahub-helm/issues/79))

## [infrahub-enterprise-4.15.5](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.15.5) - 2026-07-07

No significant changes.

## [infrahub-enterprise-4.15.2](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.15.2) - 2026-06-26

### Changed

- Bumped the bundled `infrahub` dependency to `4.29.2`, which picks up the `infrahub-backup` `1.7.4` fix for backup/restore PostgreSQL authentication.

## [infrahub-enterprise-4.15.1](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.15.1) - 2026-06-25

### Fixed

- Bumped the `infrahub` dependency to 4.29.1, which stops tracing env vars from being injected into the Infrahub server and task-worker pods when `infrahub-observability` is enabled but its bundled Tempo collector is not (`infrahub.infrahub-observability.tempo.enabled: false`). This makes it possible to run just part of the observability stack (for example only the Prefect exporter) while exporting traces to an external OTLP collector, or to none at all.

## [infrahub-enterprise-4.15.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.15.0) - 2026-06-25

### Added

- Bumped the `infrahub` dependency to 4.29.0, which makes the container `tty` setting configurable for the Infrahub server, task worker and Emma containers (previously hardcoded to `true`). It now defaults to `false` and can be enabled via `infrahub.infrahubServer.infrahubServer.tty`, `infrahub.infrahubTaskWorker.infrahubTaskWorker.tty` and `infrahub.emma.tty`.

## [infrahub-enterprise-4.14.1](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.14.1) - 2026-06-24

### Fixed

- Fixed the Prefect background-services pods crashing on startup in the `small`/`medium`/`medium-data`/`large`/`large-data` presets. The Infrahub Enterprise image sets `PROMETHEUS_MULTIPROC_DIR` to a path that is read-only when `readOnlyRootFilesystem` is enabled, so `prometheus_client` failed trying to write its multiprocess metric files there. The presets now set `PROMETHEUS_MULTIPROC_DIR` to an empty value on the background-services deployment so those writes fall back to the writable working directory instead.

## [infrahub-enterprise-4.14.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.14.0) - 2026-06-24

### Changed

- **Breaking change for Infrahub Enterprise users.** Prefect background services now share a single Redis-backed docket instead of each replica using its own in-memory one, which Prefect documents as the cause of duplicate scheduled runs and duplicate automation actions on multi-replica deployments (the medium/large presets run 2 replicas).

  Action required when upgrading: set `infrahub.prefect-server.backgroundServices.messaging.docket.url` to your cache, in the form `redis://<host>:<port>/<db>` (for example `redis://infrahub-cache-master:6379/2`, db 2 alongside messaging on db 1). The config presets ship an example value and chart validation now hard-fails the install if the example hostname is left in place — mirroring the existing `messaging.redis.host` check.

  Also in this release: the per-service `PREFECT_SERVER_SERVICES_*_ENABLED` toggles were dropped from the presets (`PREFECT__SERVER_WEBSERVER_ONLY` already disables background services on the API pods, and the background-services deployment runs them at their defaults), and the `prefect-server` dependency was bumped to `2026.6.5172345` (Prefect 3.7.x defaults). `PREFECT_API_DATABASE_MIGRATE_ON_START=false` is now pinned explicitly on the server so the Infrahub Prefect bootstrap still detects distributed mode under the renamed env vars.

## [infrahub-enterprise-4.13.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-enterprise-4.13.0) - 2026-06-24

### Added

- Bumped the `infrahub` dependency to 4.27.0, which adds a `startupProbe` to the Infrahub server. It gives the server up to 5 minutes to start before the liveness and readiness probes take over, preventing the container from being restarted mid-startup (CrashLoopBackOff). This is most likely to occur when dozens of active branches with different schemas are present, which slows down the start process. Configure it via `infrahub.infrahubServer.infrahubServer.startupProbe`.
