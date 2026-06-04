"""E2E: deploy the infrahub-enterprise chart and check it runs via the SDK."""

import pytest

from tests.e2e.conftest import portforward_service
from tests.helpers.utils import (
    check_infrahub_healthy,
    seed_infrahub_data,
    verify_infrahub_data,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.enterprise]


async def test_infrahub_enterprise_runs(infrahub_enterprise_k8s):
    """Infrahub Enterprise is reachable and a BuiltinTag round-trips via the SDK."""
    kubeconfig = infrahub_enterprise_k8s["kubeconfig_path"]
    namespace = infrahub_enterprise_k8s["namespace"]
    token = infrahub_enterprise_k8s["token"]

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_enterprise_k8s["server_label"],
        ready_path="/api/config",
    ) as url:
        health = await check_infrahub_healthy(url, token)
        assert "main" in health["branches"]

        seed = await seed_infrahub_data(url, token)
        await verify_infrahub_data(url, token, seed)
