"""E2E: install the standalone infrahub-sync chart, wait for its bootstrap Job, and check the
Sync API. Then upgrade with a changed `s3.prefix`, which the bootstrap reads, and check that
the upgrade replaced the bootstrap Job with a new one that completes, and that the Sync API
answers the same way.
"""

import asyncio
import subprocess
import time

import httpx
import pytest

from tests.e2e.conftest import portforward_service

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.sync]

UPGRADED_PREFIX = "infrahub-sync-e2e-upgrade"
WAIT = "10m"


def kubectl(release: dict, *args: str) -> str:
    """Run kubectl in the release namespace and return its output."""
    return subprocess.run(
        ["kubectl", "-n", release["namespace"], "--kubeconfig", release["kubeconfig_path"],
         *args],
        capture_output=True, text=True, check=True, timeout=900,
    ).stdout


def bootstrap_jobs(release: dict) -> list[str]:
    """Return the names of the bootstrap Jobs of the release."""
    output = kubectl(
        release, "get", "jobs", "-l", "app.kubernetes.io/component=bootstrap",
        "-o", "jsonpath={.items[*].metadata.name}",
    )
    return sorted(output.split())


def wait_for_job(release: dict, name: str) -> None:
    """Wait until this Job is complete. A Job that does not complete fails the test."""
    kubectl(release, "wait", "--for=condition=complete", f"job/{name}", f"--timeout={WAIT}")


def wait_for_rollout(release: dict) -> None:
    """Wait until the Sync API and the worker run their current pod template.

    `Available` alone is already true for the pods of the previous revision, so the
    rollout status is what shows that the new pods are ready.
    """
    for component in ("api", "worker"):
        kubectl(
            release, "rollout", "status", f"deployment/{release['fullname']}-{component}",
            f"--timeout={WAIT}",
        )


async def check_sync_api(release: dict) -> None:
    """Check `/version`, `/me` with the API token, and a ready worker in `/status`."""
    async with portforward_service(
        release["kubeconfig_path"], release["namespace"], 8000,
        name=f"{release['fullname']}-api", ready_path="/version",
    ) as url, httpx.AsyncClient(base_url=url, timeout=10) as client:
        version = (await client.get("/version")).raise_for_status().json()
        assert version["server_version"], version

        denied = await client.get("/me")
        assert denied.status_code in (401, 403), denied.text
        principal = (
            await client.get("/me", headers={"Authorization": f"Bearer {release['token']}"})
        ).raise_for_status().json()
        assert principal["actor"] == "operator", principal
        assert principal["administrator"] is True, principal

        # The worker reports its heartbeat a few seconds after it starts.
        deadline = time.monotonic() + 180
        status = {}
        while time.monotonic() < deadline:
            status = (await client.get("/status")).raise_for_status().json()
            if status["worker"]["state"] == "ready":
                break
            await asyncio.sleep(5)
        assert status["worker"]["state"] == "ready", status


async def test_sync_installs_and_upgrades(infrahub_sync_k8s):
    release = infrahub_sync_k8s

    # Install: one bootstrap Job, which completes.
    jobs = bootstrap_jobs(release)
    assert len(jobs) == 1, jobs
    first_job = jobs[0]
    wait_for_job(release, first_job)
    await check_sync_api(release)

    # Upgrade with a setting the bootstrap reads: the Job gets a new name (RR-34).
    subprocess.run(
        [
            "helm", "upgrade", release["release"], str(release["chart_path"]),
            "-n", release["namespace"], "--kubeconfig", release["kubeconfig_path"],
            "--reuse-values", "--set", f"s3.prefix={UPGRADED_PREFIX}", "--timeout", "15m",
        ],
        check=True,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        jobs = bootstrap_jobs(release)
        if first_job not in jobs:
            break
        await asyncio.sleep(3)
    assert len(jobs) == 1 and jobs[0] != first_job, (
        f"after the upgrade the bootstrap Jobs are {jobs}; expected one Job other than "
        f"{first_job}"
    )
    wait_for_job(release, jobs[0])
    wait_for_rollout(release)
    await check_sync_api(release)
