"""Checks that the HA test modules run on their own deployment."""

import uuid

from tests.e2e.conftest import portforward_service, wait_for_workloads
from tests.helpers.ha import (
    MEMBERS,
    NAMESPACE,
    data_claim,
    kubectl,
    member_pod,
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


async def check_writer_loss_and_recovery(kubeconfig: str) -> None:
    """Stop the writer of the neo4j database, use Infrahub while it is absent, then restart it."""
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
        original_probe, outage_probe = str(uuid.uuid4()), str(uuid.uuid4())
        await wait_for_marker_write(kubeconfig, original_probe)
        pods = {member: member_pod(kubeconfig, member) for member in MEMBERS}
        claims = {member: data_claim(kubeconfig, pods[member]) for member in MEMBERS}
        # Read the writer right before the scale, since leadership can move at any time.
        writer = writer_member(await wait_for_topology(kubeconfig))
        survivor = next(member for member in MEMBERS if member != writer)
        original_pod, original_claim = pods[writer], claims[writer]
        try:
            kubectl(kubeconfig, "scale", "statefulset", writer, "--replicas=0")
            kubectl(
                kubeconfig, "wait", "--for=delete", f"pod/{writer}-0", "--timeout=180s"
            )
            surviving_topology = await wait_for_topology(
                kubeconfig, member=survivor, online_members=2, absent=writer
            )
            print(
                f"Removed the writer {writer}; "
                f"the new writer is {writer_member(surviving_topology)}"
            )
            # The writer stays absent for these operations; its automatic pod restart
            # cannot hide an inability to elect a replacement and serve writes.
            await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, original)
            during_outage = await seed_infrahub_data(url, INFRAHUB_ADMIN_TOKEN)
            await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, during_outage)
            await wait_for_marker_write(
                kubeconfig, outage_probe, member=survivor, online_members=2, absent=writer
            )
            assert not kubectl(
                kubeconfig,
                "get",
                "pod",
                f"{writer}-0",
                "--ignore-not-found",
                "-o",
                "name",
            ).strip(), f"{writer} came back before the checks without it ended"
        finally:
            kubectl(kubeconfig, "scale", "statefulset", writer, "--replicas=1")
        wait_for_workloads(namespace=NAMESPACE, kubeconfig=kubeconfig)
        await wait_for_topology(kubeconfig)
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, original)
        await verify_infrahub_data(url, INFRAHUB_ADMIN_TOKEN, during_outage)
        recovered_pod = member_pod(kubeconfig, writer)
        assert recovered_pod["metadata"]["uid"] != original_pod["metadata"]["uid"], (
            f"{writer} was not restarted"
        )
        assert data_claim(kubeconfig, recovered_pod) == original_claim, (
            f"{writer} does not use the data volume it had before it stopped"
        )
        await wait_for_recovered_data(
            kubeconfig, writer, [original_probe, outage_probe]
        )
