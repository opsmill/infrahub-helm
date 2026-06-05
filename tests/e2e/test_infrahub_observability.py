"""E2E: deploy infrahub-observability alongside Infrahub and prove that
Infrahub's own metrics and traces are present and queryable through Grafana.

Flow: Infrahub runs with tracing -> Tempo and Alloy scraping its /metrics;
generate API traffic; then via Grafana's datasource proxy assert that
Infrahub-server metrics are in Prometheus and Infrahub traces are in Tempo.
"""

import pytest

from tests.conftest import CHARTS_DIR
from tests.e2e.conftest import portforward_service
from tests.helpers.utils import (
    dashboard_concrete_datasource_uids,
    dashboard_datasource_variable_types,
    dashboard_templatefree_prometheus_exprs,
    generate_infrahub_traffic,
    grafana_get_dashboard,
    grafana_list_datasources,
    grafana_promql_is_valid,
    grafana_proxy_get,
    grafana_query_prometheus,
    grafana_tempo_traceql,
    grafana_wait_for_dashboards,
    load_vendored_dashboards,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.observability]

# Dashboards the chart vendors under charts/infrahub-observability/dashboards/.
DASHBOARDS_DIR = CHARTS_DIR / "infrahub-observability" / "dashboards"
# The one dashboard whose data this suite actively generates (Infrahub traffic),
# so its panel queries can be checked against live series — matched by title.
INFRAHUB_DASHBOARD_TITLE = "Infrahub Monitoring"


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


async def test_grafana_dashboards_present_and_functional(observability_k8s):
    """The chart's pre-installed Grafana dashboards import and actually work.

    For every dashboard the chart ships we assert it is imported, provisioned
    by the sidecar, has panels, and that all the datasources it references
    resolve (no dangling UID, no empty datasource picker). Then, for the
    Infrahub dashboard specifically, we run its own template-free panel queries
    against the live Prometheus to prove the shipped queries are valid and that
    at least one returns the Infrahub series we generate traffic for — i.e. the
    panels would render real data rather than "No data" / a datasource error.
    """
    kubeconfig = observability_k8s["kubeconfig_path"]
    namespace = observability_k8s["namespace"]
    auth = observability_k8s["grafana_auth"]
    token = observability_k8s["token"]

    vendored = load_vendored_dashboards(DASHBOARDS_DIR)
    assert vendored, f"No vendored dashboards found under {DASHBOARDS_DIR}"

    # Produce Infrahub series/labels so the Infrahub dashboard's panels (and its
    # `app_name`/`job` template-variable queries) have something to resolve.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=observability_k8s["server_label"], ready_path="/api/config",
    ) as infrahub_url:
        await generate_infrahub_traffic(infrahub_url, token, "E2eDashboardProbe")

    async with portforward_service(
        kubeconfig, namespace, 3000,
        label_selector=observability_k8s["grafana_label"],
        ready_path="/api/health",
    ) as url:
        # Present: the sidecar imports every dashboard ConfigMap the chart ships.
        expected_uids = {d["uid"] for d in vendored}
        found = await grafana_wait_for_dashboards(url, auth, expected_uids)
        found_titles = {d.get("uid"): d.get("title") for d in found}

        # The datasources every dashboard's references are validated against.
        datasources = await grafana_list_datasources(url, auth)
        live_ds_uids = {ds["uid"] for ds in datasources}
        live_ds_types = {ds["type"] for ds in datasources}

        for dash in vendored:
            uid, title, model = dash["uid"], dash["title"], dash["model"]

            # Title round-trips through Grafana (catches a mis-imported file).
            assert found_titles.get(uid) == title, (
                f"Dashboard {uid!r}: chart title {title!r} != Grafana {found_titles.get(uid)!r}"
            )

            # Loads cleanly and came from our sidecar provisioning (not the API).
            loaded = await grafana_get_dashboard(url, auth, uid)
            assert loaded.get("meta", {}).get("provisioned") is True, (
                f"Dashboard {title!r} was not provisioned by the sidecar"
            )
            assert loaded["dashboard"].get("panels"), f"Dashboard {title!r} has no panels"

            # Wiring: hard-coded datasource UIDs exist, and every datasource-typed
            # template variable has a matching datasource so its picker isn't empty.
            for ds_uid in dashboard_concrete_datasource_uids(model):
                assert ds_uid in live_ds_uids, (
                    f"Dashboard {title!r} references missing datasource uid {ds_uid!r}; "
                    f"have {sorted(live_ds_uids)}"
                )
            for ds_type in dashboard_datasource_variable_types(model):
                assert ds_type in live_ds_types, (
                    f"Dashboard {title!r} has a {ds_type!r} datasource variable but no "
                    f"such datasource exists; have {sorted(live_ds_types)}"
                )

        # Works well: run the Infrahub dashboard's own template-free Prometheus
        # queries against the live datasource.
        prometheus_uid = next(ds["uid"] for ds in datasources if ds["type"] == "prometheus")
        infrahub_model = next(
            d["model"] for d in vendored if d["title"] == INFRAHUB_DASHBOARD_TITLE
        )
        exprs = dashboard_templatefree_prometheus_exprs(infrahub_model)
        assert exprs, (
            f"No template-free Prometheus queries in {INFRAHUB_DASHBOARD_TITLE!r} dashboard"
        )

        for expr in exprs:
            payload = await grafana_promql_is_valid(url, auth, prometheus_uid, expr)
            assert payload.get("status") == "success", (
                f"Infrahub dashboard query did not execute: {expr!r} -> {payload}"
            )

        # ... and at least one of those shipped queries returns the Infrahub
        # request series produced by the traffic above (polls until scraped).
        assert "sum(rate(infrahub_requests_total[5m]))" in exprs, (
            "Expected the Infrahub dashboard to chart infrahub_requests_total"
        )
        await grafana_query_prometheus(
            url, auth, prometheus_uid, "sum(rate(infrahub_requests_total[5m]))"
        )
