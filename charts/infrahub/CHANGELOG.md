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
