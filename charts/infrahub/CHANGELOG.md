## [infrahub-4.28.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.28.0) - 2026-06-24

### Changed

- Bumped the `prefect-server` dependency to `2026.6.5172345`, pulling in native docket support and the Prefect 3.7.x chart defaults. The chart now injects `PREFECT_SERVER_DATABASE_*` environment variables instead of the `PREFECT_API_DATABASE_*` names; the Prefect bundled in Infrahub (3.6.13) accepts both spellings via settings aliases, so this is backward compatible.

## [infrahub-4.27.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-4.27.0) - 2026-06-24

### Added

- Added a `startupProbe` to the Infrahub server deployment. It gives the server up to 5 minutes (60 × 5s) to start before the liveness and readiness probes take over, preventing the container from being restarted mid-startup (CrashLoopBackOff). This is most likely to occur when dozens of active branches with different schemas are present, which slows down the start process. Configure it via `infrahubServer.infrahubServer.startupProbe`.
