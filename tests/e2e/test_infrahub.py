"""E2E: deploy the community infrahub chart and check it runs via the SDK."""

import pytest

from tests.e2e.conftest import portforward_service
from tests.helpers.utils import (
    check_infrahub_healthy,
    seed_infrahub_data,
    verify_infrahub_data,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.infrahub]


async def test_infrahub_runs(infrahub_k8s):
    """Infrahub is reachable and a BuiltinTag round-trips through the SDK."""
    kubeconfig = infrahub_k8s["kubeconfig_path"]
    namespace = infrahub_k8s["namespace"]
    token = infrahub_k8s["token"]

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        # API + schema reachable
        health = await check_infrahub_healthy(url, token)
        assert "main" in health["branches"]

        # Write + read back through the SDK
        seed = await seed_infrahub_data(url, token)
        await verify_infrahub_data(url, token, seed)
