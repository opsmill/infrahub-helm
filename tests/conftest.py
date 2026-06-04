"""Shared pytest fixtures and hooks for the infrahub-helm e2e suite.

The suite spins up a fresh `vcluster` per test session and deploys the chart
under test into it with Helm. Each chart has its own test module/marker so the
CI can run only the jobs whose chart changed.
"""

import os
import subprocess
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio import config as kubeconfig
from pytest_asyncio import is_async_test

REPO_ROOT = Path(__file__).resolve().parents[1]
CHARTS_DIR = REPO_ROOT / "charts"


def pytest_collection_modifyitems(items):
    """Force all async tests to use the session-scoped event loop.

    Session-scoped async fixtures (vcluster, the chart deployments) and the
    tests that depend on them must share one event loop.
    """
    pytest_asyncio_tests = (item for item in items if is_async_test(item))
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")
    for async_test in pytest_asyncio_tests:
        async_test.add_marker(session_scope_marker, append=False)


# ---------------------------------------------------------------------------
# Fixture: vcluster
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def vcluster(tmp_path_factory) -> AsyncGenerator[dict, None]:
    """Create a vCluster (docker driver) and yield connection details."""
    kubeconfig_path = str(tmp_path_factory.mktemp("vcluster") / "kubeconfig")
    cluster_name = f"pytest-{uuid.uuid4().hex[:12]}"

    # On self-hosted runners the vcluster CLI config lives in a runner-scoped
    # temp dir; CI exports VCLUSTER_DIR pointing at it.
    vcluster_dir = os.environ.get("VCLUSTER_DIR")

    create_cmd = ["vcluster", "create", cluster_name, "--connect=false", "--driver=docker"]
    if vcluster_dir:
        create_cmd.extend(["--config", vcluster_dir])
    subprocess.run(create_cmd, check=True)

    connect_cmd = ["vcluster", "connect", cluster_name, "--print", "--driver=docker"]
    if vcluster_dir:
        connect_cmd.extend(["--config", vcluster_dir])
    result = subprocess.run(connect_cmd, capture_output=True, text=True, check=True)
    Path(kubeconfig_path).write_text(result.stdout)

    await kubeconfig.load_kube_config(config_file=kubeconfig_path)
    async with kubeclient.ApiClient() as api:
        yield {
            "api": api,
            "cluster_name": cluster_name,
            "kubeconfig_path": kubeconfig_path,
        }

    # Teardown happens after all dependent (chart) fixtures have torn down.
    delete_cmd = ["vcluster", "delete", cluster_name, "--driver=docker"]
    if vcluster_dir:
        delete_cmd.extend(["--config", vcluster_dir])
    subprocess.run(delete_cmd, check=False)


# ---------------------------------------------------------------------------
# Hooks: capture per-phase reports + dump namespace logs on failure
# ---------------------------------------------------------------------------
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(autouse=True)
async def _dump_logs_on_failure(request):
    """Dump pod state and recent container logs for the test namespaces on failure."""
    yield
    rep_call = getattr(request.node, "rep_call", None)
    if rep_call is None or not rep_call.failed:
        return

    vcluster = (
        request.getfixturevalue("vcluster") if "vcluster" in request.fixturenames else None
    )
    if not vcluster:
        return

    # Dump every namespace a deployment fixture registered on the session.
    namespaces = getattr(request.session, "_e2e_namespaces", None) or set()
    for namespace in sorted(namespaces):
        await _dump_namespace_logs(vcluster["kubeconfig_path"], namespace)


async def _dump_namespace_logs(kubeconfig: str, namespace: str) -> None:
    """Print pod statuses and recent container logs for a namespace (kr8s)."""
    import kr8s.asyncio
    from kr8s.asyncio.objects import Event, Pod

    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    print(f"\n{'=' * 70}\nDiagnostics for namespace '{namespace}'\n{'=' * 70}")

    print("\n--- pods ---")
    pods = [pod async for pod in Pod.list(namespace=namespace, api=api)]
    for pod in pods:
        status = pod.raw.get("status", {})
        statuses = status.get("containerStatuses", []) or []
        ready = sum(1 for c in statuses if c.get("ready"))
        restarts = sum(c.get("restartCount", 0) for c in statuses)
        print(f"{pod.name}\t{ready}/{len(statuses)}\t{status.get('phase')}\trestarts={restarts}")

    print("\n--- events ---")
    async for event in Event.list(namespace=namespace, api=api):
        raw = event.raw
        print(f"{raw.get('type')}\t{raw.get('reason')}\t{raw.get('message')}")

    for pod in pods:
        print(f"\n--- logs {namespace}/{pod.name} ---")
        try:
            lines = [line async for line in pod.logs(tail_lines=100)]
            print("\n".join(lines) or "(no logs)")
        except Exception as exc:  # pod may be pending / not started
            print(f"(could not fetch logs: {exc})")
