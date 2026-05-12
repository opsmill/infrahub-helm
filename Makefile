.PHONY: help sync-dashboards lint lint-observability template-observability deps-observability

help:
	@echo "Available targets:"
	@echo "  sync-dashboards          - sync vendored dashboards from upstream infrahub (REF=<ref> to override)"
	@echo "  deps-observability       - run 'helm dependency update' for the observability chart"
	@echo "  lint-observability       - run 'helm lint' for the observability chart"
	@echo "  template-observability   - render the observability chart with default values"
	@echo "  lint                     - lint every chart in charts/"

sync-dashboards:
	./scripts/sync-dashboards.sh $(REF)

deps-observability:
	helm dependency update charts/infrahub-observability

lint-observability: deps-observability
	helm lint charts/infrahub-observability

template-observability: deps-observability
	helm template test charts/infrahub-observability

lint:
	@for chart in charts/*/; do \
	    echo "==> linting $$chart"; \
	    helm dependency update "$$chart" >/dev/null; \
	    helm lint "$$chart"; \
	done
