## [infrahub-observability-0.3.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-observability-0.3.0) - 2026-10-21

### Fixed

- Added `prefectExporter.readinessProbe` and `prefectExporter.extraEnv`, and raised the default readiness probe timeout to 10 seconds, so the prefect-exporter pod becomes Ready on instances where `/metrics` takes more than 1 second to respond.

## [infrahub-observability-0.2.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-observability-0.2.0) - 2026-07-07

### Added

- Added `prefectExporter.containerSecurityContext` so a container-level `securityContext` can be set on the prefect-exporter container, in addition to the existing pod-level `prefectExporter.securityContext`. This lets the deployment satisfy cluster policies that require a container-level security context. It is empty by default and therefore non-breaking.
