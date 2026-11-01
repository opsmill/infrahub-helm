"""Three Neo4j primaries: branch/write smoke, loss of a writer, and recovery."""

import asyncio
import json
import subprocess
import time
import uuid

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
    database_topology,
    image_overrides,
    kubectl,
    neo4j_dependency,
    recovery_probe,
    topology_ready,
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


@pytest.fixture(scope="session")
async def infrahub_ha_k8s(vcluster, staged_charts, request, tmp_path_factory):
    kubeconfig = vcluster["kubeconfig_path"]
    _register_namespace(request, NAMESPACE)
    overrides_dir = tmp_path_factory.mktemp("ha-values")
    neo4j_overrides, enterprise_overrides = image_overrides()
    neo4j_override_file = overrides_dir / "neo4j.yaml"
    enterprise_override_file = overrides_dir / "enterprise.yaml"
    neo4j_override_file.write_text(yaml.safe_dump(neo4j_overrides))
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

    # All members must be installed before waiting: each needs a quorum to start.
    chart = neo4j_dependency(staged_charts["infrahub"])
    for member in MEMBERS:
        subprocess.run(
            [
                "helm",
                "upgrade",
                "--install",
                member,
                str(chart),
                "-n",
                NAMESPACE,
                "--kubeconfig",
                kubeconfig,
                "-f",
                str(FIXTURES_DIR / "neo4j-ha-values.yaml"),
                "-f",
                str(neo4j_override_file),
                "--timeout",
                "15m",
            ],
            check=True,
        )
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
        original_pod = json.loads(
            kubectl(kubeconfig, "get", "pod", f"{writer}-0", "-o", "json")
        )
        claim = next(
            volume["persistentVolumeClaim"]["claimName"]
            for volume in original_pod["spec"]["volumes"]
            if volume["name"] == "data"
        )
        original_claim_uid = json.loads(
            kubectl(kubeconfig, "get", "pvc", claim, "-o", "json")
        )["metadata"]["uid"]
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
        recovered_pod = json.loads(
            kubectl(kubeconfig, "get", "pod", f"{writer}-0", "-o", "json")
        )
        assert recovered_pod["metadata"]["uid"] != original_pod["metadata"]["uid"]
        recovered_claim = next(
            volume["persistentVolumeClaim"]["claimName"]
            for volume in recovered_pod["spec"]["volumes"]
            if volume["name"] == "data"
        )
        assert recovered_claim == claim
        assert (
            json.loads(kubectl(kubeconfig, "get", "pvc", claim, "-o", "json"))[
                "metadata"
            ]["uid"]
            == original_claim_uid
        )
        await wait_for_recovered_data(
            kubeconfig, writer, [original_probe, outage_probe]
        )
