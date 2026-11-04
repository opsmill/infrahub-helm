"""Three Neo4j primaries from an older chart: a rolling upgrade of the members to the
pinned chart, then loss of the writer and recovery on the upgraded cluster."""

import os
import uuid

import pytest

from tests.e2e.conftest import portforward_service, wait_for_workloads
from tests.e2e.ha_checks import check_writer_loss_and_recovery
from tests.helpers.ha import (
    MEMBERS,
    NAMESPACE,
    Neo4jUpgrade,
    chart_metadata,
    data_claim,
    kubectl,
    member_pod,
    neo4j_dependency,
    neo4j_release,
    neo4j_version,
    next_upgrade,
    pod_summary,
    pull_neo4j_chart,
    upgrade_from_chart,
    upgrade_required,
    version_key,
    wait_for_marker_write,
    wait_for_recovered_data,
    wait_for_topology,
    writer_member,
)
from tests.helpers.utils import (
    INFRAHUB_ADMIN_TOKEN,
    seed_infrahub_data,
    verify_infrahub_data,
    wait_for_infrahub_branch_ready,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.k8s,
    pytest.mark.ha,
    pytest.mark.ha_upgrade,
    pytest.mark.skipif(
        not os.environ.get("NEO4J_UPGRADE_FROM_CHART", "").strip(),
        reason="NEO4J_UPGRADE_FROM_CHART is not set",
    ),
]


@pytest.fixture(scope="session")
def neo4j_upgrade(staged_charts, tmp_path_factory) -> Neo4jUpgrade:
    """Charts and Neo4j versions before and after the rolling upgrade."""
    source = upgrade_from_chart()
    assert source is not None, "NEO4J_UPGRADE_FROM_CHART is not set"
    target_chart = neo4j_dependency(staged_charts["infrahub"])
    source_chart = pull_neo4j_chart(
        staged_charts["infrahub"], source, tmp_path_factory.mktemp("neo4j-from")
    )
    upgrade = Neo4jUpgrade(
        source_chart=source_chart,
        target_chart=target_chart,
        source_version=str(chart_metadata(source_chart)["appVersion"]),
        target_version=str(chart_metadata(target_chart)["appVersion"]),
    )
    if not upgrade_required(upgrade.source_version, upgrade.target_version):
        pytest.skip(
            f"{source_chart.name} and {target_chart.name} both run Neo4j "
            f"{upgrade.target_version}"
        )
    return upgrade


@pytest.fixture(scope="session")
async def infrahub_ha_upgrade_k8s(neo4j_upgrade, install_infrahub_ha) -> str:
    """Deploy the HA cluster with Neo4j members from the chart the upgrade starts from."""
    return await install_infrahub_ha(neo4j_upgrade.source_chart)


async def test_neo4j_rolling_upgrade(neo4j_upgrade, neo4j_values, infrahub_ha_upgrade_k8s):
    kubeconfig = infrahub_ha_upgrade_k8s
    source, target = neo4j_upgrade.source_version, neo4j_upgrade.target_version
    print(
        f"Neo4j rolling upgrade from {source} ({neo4j_upgrade.source_chart.name}) "
        f"to {target} ({neo4j_upgrade.target_chart.name})"
    )
    for member in MEMBERS:
        version = neo4j_version(kubeconfig, member)
        print(f"Before the upgrade, {member} runs Neo4j {version}")
        assert version_key(version) == version_key(source)
    claims = {
        member: data_claim(kubeconfig, member_pod(kubeconfig, member))
        for member in MEMBERS
    }
    async with portforward_service(
        kubeconfig,
        NAMESPACE,
        8000,
        label_selector="service=infrahub-server",
        ready_path="/api/config",
    ) as url:
        await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)
        seeded = [await seed_infrahub_data(url, INFRAHUB_ADMIN_TOKEN)]
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, seeded[0])
        markers = [str(uuid.uuid4())]
        await wait_for_marker_write(kubeconfig, markers[0])
        remaining, order = list(MEMBERS), []
        while remaining:
            writer = writer_member(await wait_for_topology(kubeconfig))
            member = next_upgrade(remaining, writer)
            print(
                f"Upgrade step {len(order) + 1} of {len(MEMBERS)}: {member} "
                f"to Neo4j {target}; the writer is {writer}"
            )
            previous_pod = member_pod(kubeconfig, member)["metadata"]["uid"]
            neo4j_release(
                kubeconfig, member, neo4j_upgrade.target_chart, neo4j_values, install=False
            )
            wait_for_workloads(namespace=NAMESPACE, kubeconfig=kubeconfig)
            assert member_pod(kubeconfig, member)["metadata"]["uid"] != previous_pod, (
                f"{member} was not restarted by the upgrade"
            )
            # Querying through the upgraded member also checks that it routes cluster queries again.
            await wait_for_topology(kubeconfig, member=member)
            version = neo4j_version(kubeconfig, member)
            assert version_key(version) == version_key(target), (
                f"{member} runs Neo4j {version} after the upgrade"
            )
            await wait_for_recovered_data(kubeconfig, member, markers)
            await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)
            seeded.append(await seed_infrahub_data(url, INFRAHUB_ADMIN_TOKEN))
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, seeded[-1])
            markers.append(str(uuid.uuid4()))
            await wait_for_marker_write(kubeconfig, markers[-1])
            remaining.remove(member)
            order.append(member)
        print(f"Upgrade order: {', '.join(order)}")

        await wait_for_topology(kubeconfig)
        for data in seeded:
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, data)
        for member in MEMBERS:
            version = neo4j_version(kubeconfig, member)
            print(f"After the upgrade, {member} runs Neo4j {version}")
            assert version_key(version) == version_key(target)
            await wait_for_recovered_data(kubeconfig, member, markers)
            assert data_claim(kubeconfig, member_pod(kubeconfig, member)) == claims[
                member
            ], f"{member} does not use the data volume it had before the upgrade"
    print(kubectl(kubeconfig, "get", "pods", "-o", "wide"))
    print(pod_summary(kubeconfig))


async def test_neo4j_writer_loss_after_the_upgrade(infrahub_ha_upgrade_k8s, request):
    upgrade = next(
        (
            item
            for item in request.session.items
            if item.module is request.module
            and item.originalname == "test_neo4j_rolling_upgrade"
        ),
        None,
    )
    report = getattr(upgrade, "rep_call", None)
    if report is None or not report.passed:
        pytest.skip(
            "The rolling upgrade did not pass in this run, so the members may not all "
            "run the pinned Neo4j version"
        )
    await check_writer_loss_and_recovery(infrahub_ha_upgrade_k8s)
