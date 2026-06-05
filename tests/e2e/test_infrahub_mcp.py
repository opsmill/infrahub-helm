"""E2E: deploy the infrahub-mcp sub-chart against a running Infrahub and verify
the MCP server is exposed under "/mcp" on the same ingress host that serves
Infrahub, and that its tools work end to end through that ingress.
"""

import re
import uuid

import pytest

from tests.e2e.conftest import loadbalancer_url
from tests.helpers.utils import mcp_result_text, mcp_session, wait_for_http

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.mcp]


async def test_mcp_tools_work_via_shared_ingress(infrahub_mcp_k8s):
    """The MCP server is reachable under "/mcp" on the Infrahub ingress host and
    its tools round-trip to Infrahub.

    Everything is driven through the shared Traefik ingress (no port-forward):
    Infrahub answers at "/", and on the same host the MCP server answers under
    "/mcp", where a tag created via the write tool is read back via the query
    tool — exercising the full MCP -> Infrahub round-trip.
    """
    kubeconfig = infrahub_mcp_k8s["kubeconfig_path"]
    namespace = infrahub_mcp_k8s["namespace"]
    host = infrahub_mcp_k8s["ingress_hostname"]
    headers = {"Host": host}

    # The ingress controller is exposed via vcluster's embedded load balancer.
    base = await loadbalancer_url(
        kubeconfig, namespace, infrahub_mcp_k8s["ingress_service"], port=80
    )

    # Infrahub is reachable at "/" on this host (proves the controller routes
    # and the shared host resolves to the Infrahub server).
    await wait_for_http(
        f"{base}/api/config", headers=headers, timeout=180.0, interval=5.0
    )

    tag_name = f"mcp-e2e-{uuid.uuid4().hex[:8]}"

    # The MCP server answers under "/mcp" on the SAME host. A completed MCP
    # session (initialize) means the request reached the MCP server — an ingress
    # mismatch would hit the default backend and the handshake would fail.
    async with mcp_session(f"{base}/mcp", headers=headers) as session:
        # Tool catalog is built from the connected Infrahub's schema.
        catalog = {tool.name for tool in (await session.list_tools()).tools}
        assert {"node_upsert", "get_session_info", "get_nodes"} <= catalog, catalog

        # Create a tag via the write tool (lands on an auto-created session branch).
        created = await session.call_tool(
            "node_upsert", {"kind": "BuiltinTag", "data": {"name": tag_name}}
        )
        assert not created.isError, mcp_result_text(created)

        # Find the session branch the write landed on.
        info = mcp_result_text(await session.call_tool("get_session_info", {}))
        match = re.search(r"mcp/session-[\w.-]+", info)
        assert match, f"no session branch reported by get_session_info: {info}"
        branch = match.group(0)

        # Read the tag back via the query tool on that branch.
        found = await session.call_tool(
            "get_nodes",
            {
                "kind": "BuiltinTag",
                "branch": branch,
                "filters": {"name__value": tag_name},
                "include_attributes": True,
            },
        )
        assert not found.isError, mcp_result_text(found)
        assert tag_name in mcp_result_text(found), (
            f"MCP get_nodes did not return seeded tag {tag_name!r}: "
            f"{mcp_result_text(found)}"
        )
