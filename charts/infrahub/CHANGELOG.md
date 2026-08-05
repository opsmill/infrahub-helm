## [infrahub-4.32.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.32.0) - 2026-08-05

### Changed

- Bumped the bundled `infrahub-backup` subchart to `1.3.0` (image `2.3.0`), which adds a scheduled restore mode: `infrahub-backup.restore.mode=cronjob` with `infrahub-backup.restore.schedule` renders a CronJob instead of a one-shot Job, and `infrahub-backup.restore.storage.s3.latest=true` (with `infrahub-backup.restore.storage.s3.prefix`) restores the newest backup under the bucket/prefix instead of naming an exact archive — enabling an unattended, recurring prod → staging sync.

## [infrahub-4.31.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.31.0) - 2026-08-03

### Added

- Add `upgrade.extraArgs` (empty by default) to pass additional arguments to the `infrahub upgrade` command run by the upgrade hook job, such as `--rebase-branches` to rebase open branches after migrations that require it.

## [infrahub-4.30.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.30.0) - 2026-07-24

### Added

- Added `global.infrahubImageFlavor` to select a flavored Infrahub image (for example `avd`) without pinning the image tag. When set, the flavor is appended to the resolved image tag as `<tag>-<flavor>`, whether the tag comes from `global.infrahubTag` or defaults to the chart `appVersion`, so upgrading the chart alone is enough to track new versions. ([#79](https://github.com/opsmill/infrahub-helm/issues/79))

## [infrahub-4.29.5](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.29.5) - 2026-07-07

No significant changes.

## [infrahub-4.29.2](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.29.2) - 2026-06-26

### Changed

- Bumped the bundled `infrahub-backup` subchart to `1.2.1` (infrahub-backup `1.7.4`), which fixes backup/restore authentication against the task-manager PostgreSQL.

### Fixed

- Fixed the `prefect-server` pod crash-looping on startup. The Infrahub image bakes `PROMETHEUS_MULTIPROC_DIR` to `/prom_shared`, a root-owned directory on the root filesystem; because the pod runs as a non-root user with a read-only root filesystem, `prometheus_client` could not write its multiprocess metric files there and the container exited before becoming ready. As the Infrahub server and the task worker both wait for `prefect-server` at startup, this could block the whole stack from coming up. `PROMETHEUS_MULTIPROC_DIR` now points at the writable `/tmp` mount that prefect-helm already provides.

## [infrahub-4.29.1](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.29.1) - 2026-06-25

### Fixed

- Tracing env vars are no longer injected into the Infrahub server and task-worker pods when `infrahub-observability` is enabled but its bundled Tempo collector is not (`infrahub-observability.tempo.enabled: false`). Previously the pods received an `INFRAHUB_TRACE_EXPORTER_ENDPOINT` pointing at a non-existent `<release>-tempo` service and continuously failed to export spans. Tracing is now implied on only when the bundled Tempo is actually deployed; otherwise it is governed solely by `global.tracing.enabled` / `global.tracing.endpoint`. This makes it possible to run just part of the observability stack (for example only the Prefect exporter) while exporting traces to an external OTLP collector, or to none at all.

## [infrahub-4.29.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.29.0) - 2026-06-25

### Added

- Made the `tty` setting configurable for the Infrahub server, task worker and Emma containers, instead of being hardcoded to `true`. It now defaults to `false` and can be enabled via `infrahubServer.infrahubServer.tty`, `infrahubTaskWorker.infrahubTaskWorker.tty` and `emma.tty`.

## [infrahub-4.28.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.28.0) - 2026-06-24

### Changed

- Bumped the `prefect-server` dependency to `2026.6.5172345`, pulling in native docket support and the Prefect 3.7.x chart defaults. The chart now injects `PREFECT_SERVER_DATABASE_*` environment variables instead of the `PREFECT_API_DATABASE_*` names; the Prefect bundled in Infrahub (3.6.13) accepts both spellings via settings aliases, so this is backward compatible.

## [infrahub-4.27.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.27.0) - 2026-06-24

### Added

- Added a `startupProbe` to the Infrahub server deployment. It gives the server up to 5 minutes (60 × 5s) to start before the liveness and readiness probes take over, preventing the container from being restarted mid-startup (CrashLoopBackOff). This is most likely to occur when dozens of active branches with different schemas are present, which slows down the start process. Configure it via `infrahubServer.infrahubServer.startupProbe`.
