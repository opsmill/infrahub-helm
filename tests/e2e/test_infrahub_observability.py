"""E2E: deploy infrahub-observability alongside Infrahub and prove that
Infrahub's own metrics and traces are present and queryable through Grafana.

Flow: Infrahub runs with tracing -> Tempo and Alloy scraping its /metrics;
generate API traffic; then via Grafana's datasource proxy assert that
Infrahub-server metrics are in Prometheus and Infrahub traces are in Tempo.
"""

import pytest

from tests.e2e.conftest import portforward_service
from tests.helpers.utils import (
    generate_infrahub_traffic,
    grafana_list_datasources,
    grafana_proxy_get,
    grafana_query_prometheus,
    grafana_tempo_traceql,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.observability]


async def test_grafana_can_query_infrahub_metrics_and_traces(observability_k8s):
    """Grafana can query Infrahub metrics (Prometheus) and traces (Tempo)."""
    kubeconfig = observability_k8s["kubeconfig_path"]
    namespace = observability_k8s["namespace"]
    auth = observability_k8s["grafana_auth"]
    token = observability_k8s["token"]
    query_name = "E2eBuiltinTagProbe"

    # Drive some Infrahub API traffic to produce metrics and traces.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=observability_k8s["server_label"], ready_path="/api/config",
    ) as infrahub_url:
        await generate_infrahub_traffic(infrahub_url, token, query_name)

    # Grafana's container listens on 3000; kr8s forwards remote_port straight to
    # the backing pod (no Service port -> targetPort translation).
    async with portforward_service(
        kubeconfig, namespace, 3000,
        label_selector=observability_k8s["grafana_label"],
        ready_path="/api/health",
    ) as url:
        datasources = await grafana_list_datasources(url, auth)
        by_type = {ds["type"]: ds for ds in datasources}
        for ds_type in ("prometheus", "loki", "tempo"):
            assert ds_type in by_type, (
                f"Missing '{ds_type}' datasource; got {sorted(by_type)}"
            )
        prometheus_uid = by_type["prometheus"]["uid"]

        # Metrics: Alloy scrapes the Infrahub server's /metrics endpoint. A
        # successful scrape yields up{job="infrahub-server"} == 1 ...
        await grafana_query_prometheus(
            url, auth, prometheus_uid, 'up{job="infrahub-server"} == 1'
        )
        # ... and the endpoint exposes real Infrahub application metrics (i.e.
        # series beyond the synthetic `up`/`scrape_*` ones the scraper adds).
        infrahub_metrics = await grafana_query_prometheus(
            url, auth, prometheus_uid,
            'count({job="infrahub-server", __name__!="up", __name__!~"scrape_.+"})',
        )
        assert infrahub_metrics, "No Infrahub application metrics in Prometheus"

        # Logs: Loki answers a label query through the proxy.
        labels = await grafana_proxy_get(
            url, auth, by_type["loki"]["uid"], "/loki/api/v1/labels"
        )
        assert labels.get("status") == "success", f"Loki labels query failed: {labels}"

        # Traces: the BuiltinTag GraphQL query we drove carries the operation
        # name `query_name`, which Infrahub records on the `execute_graphql`
        # span's `operation` attribute. Query Tempo for exactly that span — a
        # targeted TraceQL search (no fetch-all), so background traces don't
        # interfere and the match is unambiguously our BuiltinTag query.
        traces = await grafana_tempo_traceql(
            url, auth, by_type["tempo"]["uid"],
            f'{{ span.operation = "{query_name}" }}',
        )
        assert traces, f"No Infrahub trace for GraphQL operation {query_name!r} in Tempo"
