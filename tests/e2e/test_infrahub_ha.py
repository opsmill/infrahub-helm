"""Three Neo4j primaries: branch/write smoke, loss of a writer, recovery, and an
optional rolling upgrade of the members."""

import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml

from tests.e2e.conftest import (
    FIXTURES_DIR,
    _register_namespace,
    helm_install,
    portforward_service,
    wait_for_workloads,
)
from tests.helpers.ha import (
    MEMBERS,
    NAMESPACE,
    Neo4jUpgrade,
    chart_metadata,
    data_claim,
    database_topology,
    image_overrides,
    kubectl,
    member_pod,
    neo4j_dependency,
    neo4j_release,
    neo4j_version,
    next_upgrade,
    pod_summary,
    pull_neo4j_chart,
    recovery_probe,
    topology_ready,
    upgrade_from_chart,
    upgrade_required,
    version_key,
    writer_member,
)
from tests.helpers.utils import (
    INFRAHUB_ADMIN_TOKEN,
    seed_infrahub_data,
    verify_infrahub_data,
    wait_for_infrahub_branch_ready,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.ha]


async def wait_for_topology(
    kubeconfig, *, member=MEMBERS[0], online_members=3, absent=None, timeout=300
):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = database_topology(kubeconfig, member)
            if topology_ready(last, online_members, absent):
                return last
        except subprocess.CalledProcessError as exc:
            last = exc.stderr
        await asyncio.sleep(5)
    raise AssertionError(
        f"Expected {online_members} online primaries and one writer, absent={absent}: {last}"
    )


async def wait_for_recovered_data(kubeconfig, member, ids, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = recovery_probe(kubeconfig, member, ids)
            if last == [{"count": str(len(ids))}]:
                return
        except subprocess.CalledProcessError as exc:
            last = exc.stderr
        await asyncio.sleep(5)
    raise AssertionError(f"Recovered member {member} did not catch up: {last}")


async def wait_for_marker_write(kubeconfig, probe, timeout=180):
    """Write through the member that is the writer now, since leadership can move."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        writer = writer_member(await wait_for_topology(kubeconfig))
        try:
            recovery_probe(kubeconfig, writer, [probe], write=True)
            return
        except subprocess.CalledProcessError as exc:
            last = exc.stderr
        await asyncio.sleep(5)
    raise AssertionError(f"Could not write marker {probe}: {last}")


@pytest.fixture(scope="session")
def neo4j_values(tmp_path_factory) -> list[Path]:
    """Values files of every member release, reused unchanged by the rolling upgrade."""
    neo4j_overrides, _ = image_overrides()
    override_file = tmp_path_factory.mktemp("neo4j-values") / "neo4j.yaml"
    override_file.write_text(yaml.safe_dump(neo4j_overrides))
    return [FIXTURES_DIR / "neo4j-ha-values.yaml", override_file]


@pytest.fixture(scope="session")
def neo4j_upgrade(staged_charts, tmp_path_factory) -> Neo4jUpgrade | None:
    """Charts and Neo4j versions before and after the rolling upgrade, if one is requested."""
    source = upgrade_from_chart()
    if source is None:
        return None
    target_chart = neo4j_dependency(staged_charts["infrahub"])
    source_chart = pull_neo4j_chart(
        staged_charts["infrahub"], source, tmp_path_factory.mktemp("neo4j-from")
    )
    return Neo4jUpgrade(
        source_chart=source_chart,
        target_chart=target_chart,
        source_version=str(chart_metadata(source_chart)["appVersion"]),
        target_version=str(chart_metadata(target_chart)["appVersion"]),
    )


@pytest.fixture(scope="session")
async def infrahub_ha_k8s(
    vcluster, staged_charts, neo4j_values, neo4j_upgrade, request, tmp_path_factory
):
    kubeconfig = vcluster["kubeconfig_path"]
    _register_namespace(request, NAMESPACE)
    _, enterprise_overrides = image_overrides()
    enterprise_override_file = tmp_path_factory.mktemp("ha-values") / "enterprise.yaml"
    enterprise_override_file.write_text(yaml.safe_dump(enterprise_overrides))

    kubectl(
        kubeconfig, "wait", "node", "--all", "--for=condition=Ready", "--timeout=180s"
    )
    nodes = json.loads(kubectl(kubeconfig, "get", "nodes", "-o", "json"))["items"]
    assert len(nodes) == 3, f"Expected three Kubernetes nodes, got {len(nodes)}"
    kubectl(kubeconfig, "create", "namespace", NAMESPACE)
    kubectl(
        kubeconfig,
        "apply",
        "-f",
        "-",
        input=yaml.safe_dump_all(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "ha-neo4j-auth"},
                    "stringData": {"NEO4J_AUTH": "neo4j/admin"},
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "infrahub-ha-headless"},
                    "spec": {
                        "clusterIP": "None",
                        "selector": {
                            "app": "infrahub-ha",
                            "helm.neo4j.com/pod_category": "neo4j-instance",
                        },
                        "ports": [{"name": "bolt", "port": 7687, "targetPort": 7687}],
                    },
                },
            ]
        ),
    )

    chart = neo4j_dependency(staged_charts["infrahub"])
    if neo4j_upgrade and upgrade_required(
        neo4j_upgrade.source_version, neo4j_upgrade.target_version
    ):
        chart = neo4j_upgrade.source_chart
    print(f"Installing the Neo4j members from {chart.name}")
    # All members must be installed before waiting: each needs a quorum to start.
    for member in MEMBERS:
        neo4j_release(kubeconfig, member, chart, neo4j_values)
    wait_for_workloads(namespace=NAMESPACE, kubeconfig=kubeconfig)
    await wait_for_topology(kubeconfig)

    pods = json.loads(
        kubectl(kubeconfig, "get", "pods", "-l", "app=infrahub-ha", "-o", "json")
    )["items"]
    assert len(pods) == 3
    assert (
        len({pod["spec"]["nodeName"] for pod in pods}) == 3
    ), "Neo4j members must occupy distinct nodes"

    helm_install(
        release="infrahub-ha",
        chart_path=staged_charts["infrahub-enterprise"],
        namespace=NAMESPACE,
        kubeconfig=kubeconfig,
        values_files=[
            FIXTURES_DIR / "infrahub-enterprise-values.yaml",
            FIXTURES_DIR / "infrahub-ha-values.yaml",
            enterprise_override_file,
        ],
    )
    for selector in (
        "service=infrahub-server",
        "service=infrahub-task-worker",
        "infrahub/service=task-manager",
    ):
        kubectl(
            kubeconfig,
            "wait",
            "pod",
            "-l",
            selector,
            "--for=condition=Ready",
            "--timeout=300s",
        )
        pods = json.loads(
            kubectl(kubeconfig, "get", "pods", "-l", selector, "-o", "json")
        )["items"]
        assert len(pods) == 2, f"Expected two replicas for {selector}"
        assert len({pod["spec"]["nodeName"] for pod in pods}) == 2
    print(kubectl(kubeconfig, "get", "pods", "-o", "wide"))
    print(kubectl(kubeconfig, "get", "pods", "-o", "jsonpath={..image}"))
    return kubeconfig


@pytest.mark.skipif(
    not os.environ.get("NEO4J_UPGRADE_FROM_CHART", "").strip(),
    reason="NEO4J_UPGRADE_FROM_CHART is not set",
)
async def test_neo4j_rolling_upgrade(neo4j_upgrade, neo4j_values, infrahub_ha_k8s):
    kubeconfig = infrahub_ha_k8s
    source, target = neo4j_upgrade.source_version, neo4j_upgrade.target_version
    if not upgrade_required(source, target):
        pytest.skip(
            f"{neo4j_upgrade.source_chart.name} and {neo4j_upgrade.target_chart.name} "
            f"both run Neo4j {target}"
        )
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


async def test_neo4j_writer_loss_and_recovery(infrahub_ha_k8s):
    kubeconfig = infrahub_ha_k8s
    async with portforward_service(
        kubeconfig,
        NAMESPACE,
        8000,
        label_selector="service=infrahub-server",
        ready_path="/api/config",
    ) as url:
        # Branch creation exercises a registered Prefect deployment, not just HTTP readiness.
        await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)
        original = await seed_infrahub_data(url, INFRAHUB_ADMIN_TOKEN)
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, original)
        topology = await wait_for_topology(kubeconfig)
        writer = writer_member(topology)
        survivor = next(member for member in MEMBERS if member != writer)
        original_probe, outage_probe = str(uuid.uuid4()), str(uuid.uuid4())
        recovery_probe(kubeconfig, writer, [original_probe], write=True)
        original_pod = member_pod(kubeconfig, writer)
        original_claim = data_claim(kubeconfig, original_pod)
        try:
            kubectl(kubeconfig, "scale", "statefulset", writer, "--replicas=0")
            kubectl(
                kubeconfig, "wait", "--for=delete", f"pod/{writer}-0", "--timeout=180s"
            )
            surviving_topology = await wait_for_topology(
                kubeconfig, member=survivor, online_members=2, absent=writer
            )
            replacement = writer_member(surviving_topology)
            assert replacement != writer
            # The writer stays absent for these operations; its automatic pod restart
            # cannot hide an inability to elect a replacement and serve writes.
            await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, original)
            during_outage = await seed_infrahub_data(url, INFRAHUB_ADMIN_TOKEN)
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, during_outage)
            recovery_probe(kubeconfig, replacement, [outage_probe], write=True)
            assert not kubectl(
                kubeconfig,
                "get",
                "pod",
                f"{writer}-0",
                "--ignore-not-found",
                "-o",
                "name",
            ).strip()
        finally:
            kubectl(kubeconfig, "scale", "statefulset", writer, "--replicas=1")
        wait_for_workloads(namespace=NAMESPACE, kubeconfig=kubeconfig)
        await wait_for_topology(kubeconfig)
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, original)
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, during_outage)
        recovered_pod = member_pod(kubeconfig, writer)
        assert recovered_pod["metadata"]["uid"] != original_pod["metadata"]["uid"]
        assert data_claim(kubeconfig, recovered_pod) == original_claim
        await wait_for_recovered_data(
            kubeconfig, writer, [original_probe, outage_probe]
        )
