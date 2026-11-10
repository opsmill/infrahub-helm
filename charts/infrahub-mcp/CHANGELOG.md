## [infrahub-mcp-0.2.0](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-mcp-0.2.0) - 2026-11-10

### Added

- Added values for the infrahub-mcp settings that the chart did not set: `infrahub.username` and `infrahub.password`, `mcp.host`, `mcp.tokenPassthroughHeader`, `mcp.authScopesWrite`, `mcp.oidc.*` (including `mcp.oidc.jwtSigningKey`, which lets OIDC mode run as a public client without a client secret) and `mcp.schemaExpandPeers`. The chart now sets `MCP_PORT` from `service.targetPort`, so changing the port also changes the port the server listens on.

### Changed

- Bumped the `infrahub-mcp` image to `v1.3.0`. See the [infrahub-mcp 1.2.1](https://github.com/opsmill/infrahub-mcp/releases/tag/v1.2.1) and [infrahub-mcp 1.3.0](https://github.com/opsmill/infrahub-mcp/releases/tag/v1.3.0) release notes.

### Fixed

- Corrected the description of `mcp.rateLimit.burst`: `0` sets the burst allowance to twice `mcp.rateLimit.rps`; it does not disable bursts.

## [infrahub-mcp-0.1.1](https://github.com/opsmill/infrahub-helm/releases/tag/infrahub-mcp-0.1.1) - 2026-11-03

### Fixed

- The install notes print the MCP client URL as `<host>/mcp`. They printed `<host>/mcp/mcp`, which returns 404 because the ingress and the HTTPRoute pass the path to the server without rewriting it.
