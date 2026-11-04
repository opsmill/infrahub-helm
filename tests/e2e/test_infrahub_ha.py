"""Three Neo4j primaries from the pinned chart: placement, loss of the writer and recovery."""

import json

import pytest

from tests.e2e.ha_checks import check_writer_loss_and_recovery
from tests.helpers.ha import REPLICATED_SERVICES, kubectl

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.ha]


def _pod_nodes(kubeconfig: str, selector: str) -> list[str]:
    pods = json.loads(kubectl(kubeconfig, "get", "pods", "-l", selector, "-o", "json"))
    return [pod["spec"]["nodeName"] for pod in pods["items"]]


async def test_neo4j_members_run_on_distinct_nodes(infrahub_ha_k8s):
    nodes = _pod_nodes(infrahub_ha_k8s, "app=infrahub-ha")
    assert len(nodes) == 3, f"Expected three Neo4j members, got {len(nodes)}"
    assert len(set(nodes)) == 3, f"Neo4j members must occupy distinct nodes: {nodes}"


@pytest.mark.parametrize("selector", REPLICATED_SERVICES)
async def test_infrahub_services_run_two_replicas_on_distinct_nodes(
    infrahub_ha_k8s, selector
):
    nodes = _pod_nodes(infrahub_ha_k8s, selector)
    assert len(nodes) == 2, f"Expected two replicas for {selector}, got {len(nodes)}"
    assert len(set(nodes)) == 2, f"The replicas of {selector} must occupy distinct nodes: {nodes}"


async def test_neo4j_writer_loss_and_recovery(infrahub_ha_k8s):
    await check_writer_loss_and_recovery(infrahub_ha_k8s)
