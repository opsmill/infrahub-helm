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
