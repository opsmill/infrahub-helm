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
async def vcluster(tmp_path_factory, request) -> AsyncGenerator[dict, None]:
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

    # Stash the kubeconfig on the session so the failure-diagnostics hook can
    # dump namespaces even when a *chart* fixture fails during setup (that
    # session-scoped fixture never runs its own teardown, so a fixture-based
    # dump would be skipped entirely — which is exactly why a failed helm
    # install in CI produced no pod/event/log output).
    request.session._e2e_kubeconfig = kubeconfig_path

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
# Hooks: dump namespace diagnostics on failure (setup *or* call phase)
# ---------------------------------------------------------------------------
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)

    # Dump diagnostics for any failed phase. Crucially this includes the *setup*
    # phase: the chart deployments are session-scoped fixtures, so when one fails
    # to become ready the failure surfaces during setup and no fixture teardown
    # runs — a fixture-based dump would be silently skipped (this is why the
    # flaky "helm install" failures in CI came with zero pod/event/log output).
    # Running from the report hook is independent of fixture setup ordering, and
    # the dump is best-effort: it must never mask the real failure.
    if report.failed:
        try:
            _dump_e2e_diagnostics(item.session)
        except Exception as exc:  # pragma: no cover - diagnostics are best-effort
            print(f"\n(failed to dump e2e diagnostics: {exc})", flush=True)


def _dump_e2e_diagnostics(session) -> None:
    """Print pod state, events, and recent container logs for every namespace a
    deployment fixture registered on the session."""
    kubeconfig = getattr(session, "_e2e_kubeconfig", None)
    namespaces = getattr(session, "_e2e_namespaces", None) or set()
    if not kubeconfig or not namespaces:
        return
    for namespace in sorted(namespaces):
        _dump_namespace_diagnostics(kubeconfig, namespace)


def _dump_namespace_diagnostics(kubeconfig: str, namespace: str) -> None:
    """Shell out to kubectl to dump a namespace's state and recent logs.

    Uses kubectl (not kr8s) so it works from this synchronous hook without an
    event loop, and surfaces exactly what a human would run to triage a stuck
    rollout: pod/workload status, events, and the tail of each container's logs
    (including the previous container when a pod has been restarting).
    """
    base = ["kubectl", "-n", namespace, "--kubeconfig", kubeconfig]
    print(f"\n{'=' * 70}\nDiagnostics for namespace '{namespace}'\n{'=' * 70}", flush=True)

    def run(title: str, args: list[str]) -> str:
        print(f"\n--- {title} ---", flush=True)
        try:
            proc = subprocess.run([*base, *args], capture_output=True, text=True, timeout=60)
        except Exception as exc:  # kubectl missing / cluster unreachable
            print(f"(kubectl {' '.join(args)} failed: {exc})", flush=True)
            return ""
        print((proc.stdout or proc.stderr).strip() or "(no output)", flush=True)
        return proc.stdout

    run("workloads", ["get", "deployment,statefulset,daemonset,pod", "-o", "wide"])
    run("events", ["get", "events", "--sort-by=.lastTimestamp"])

    # Enumerate pods (quietly) and dump each one's recent logs below.
    try:
        listing = subprocess.run(
            [*base, "get", "pods", "-o", "name"], capture_output=True, text=True, timeout=60
        )
        pods = listing.stdout.split()
    except Exception:  # cluster unreachable — already surfaced above
        pods = []
    for pod in pods:
        print(f"\n--- logs {namespace}/{pod} ---", flush=True)
        for extra in ([], ["--previous"]):  # current, then last-terminated
            try:
                proc = subprocess.run(
                    [*base, "logs", pod, "--all-containers", "--tail=100", "--prefix", *extra],
                    capture_output=True, text=True, timeout=60,
                )
            except Exception as exc:
                print(f"(could not fetch logs{' (previous)' if extra else ''}: {exc})", flush=True)
                continue
            output = proc.stdout.strip()
            if output:
                print(f"{'[previous] ' if extra else ''}{output}", flush=True)
