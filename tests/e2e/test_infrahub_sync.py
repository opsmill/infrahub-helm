"""E2E: install the standalone infrahub-sync chart, wait for its bootstrap Job, and check the
Sync API. Then upgrade with a changed `s3.prefix` and `settings.workPool`, which the bootstrap
reads, and check the start check (FR-007b):

- The upgrade also sets a CPU request in `bootstrap.resources` that no node can meet, so the
  new bootstrap Job stays `Pending`. Its name changes (RR-34). The bootstrap record still names
  the previous work pool. While the Job is held, the new Sync API pod must not become Ready, and
  it must log the start check's refusal that names the upgraded work pool.
- A second upgrade sets a small CPU request. The Job gets a new name again, runs and completes.
- The new Sync API pod became Ready at or after the time the bootstrap wrote its record (read
  from the Job's log). The worker has no readiness probe, so its Ready time is when its
  container started. It may precede the record by the few seconds its start check takes.
- The Sync API answers the same way.

Without the hold, an image without the start check also passed: the bootstrap finished before
that image's Sync API became ready. The record is compared instead of the Job's
`completionTime`, because the bootstrap writes the record a few seconds before Kubernetes sets
`completionTime`, and a pod can start correctly in between. No assertion counts restarts.
"""

import asyncio
import json
import subprocess
import time
from datetime import datetime

import httpx
import pytest

from tests.e2e.conftest import portforward_service

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.sync]

UPGRADED_PREFIX = "infrahub-sync-e2e-upgrade"
UPGRADED_WORK_POOL = "infrahub-sync-e2e-upgrade"
WAIT = "10m"
# A CPU request that no node can meet keeps the bootstrap Job's pod `Pending` (the hold), and a
# small one lets it run (the release). `bootstrap.resources` is part of the Job name's hash.
HOLD_CPU = "1000"
RELEASE_CPU = "10m"
HOLD_TIMEOUT_SECONDS = 300
# The worker has no readiness probe: its `Ready` time is when its container starts, and its
# start check reads the record about 2 seconds later (measured on minikube). Its `Ready` time
# may precede the record write by that much.
WORKER_CHECK_SECONDS = 5
# How long `/status` may take to report a ready worker. A worker that exited before the record
# was written starts again only after its restart back-off, which Kubernetes caps at 300 s.
WORKER_STATUS_SECONDS = 330


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


def parse_time(value: str) -> datetime:
    """Parse a Kubernetes timestamp such as `2026-11-16T15:39:43Z`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def job_completion_time(release: dict, name: str) -> datetime:
    """Return the `status.completionTime` of a complete Job."""
    return parse_time(
        kubectl(release, "get", "job", name, "-o", "jsonpath={.status.completionTime}")
    )


def record_written(release: dict, job: str) -> tuple[datetime, str]:
    """Return when the bootstrap wrote its record, truncated to the second, and the evidence.

    The bootstrap logs `bootstrap recorded for ...` right after it writes the record, a few
    seconds before Kubernetes sets the Job's `completionTime`. The start check reads the record,
    not the Job status, so a pod can start correctly between the two. The time is truncated to
    the second because a pod condition's `lastTransitionTime` has a resolution of one second.
    When the log holds no such line (an image without the bootstrap record), the time is when
    the bootstrap container finished, which comes after any record it could have written.
    """
    logs = kubectl(release, "logs", f"job/{job}", "-c", "bootstrap", "--timestamps")
    lines = [line for line in logs.splitlines() if "bootstrap recorded for" in line]
    if lines:
        return parse_time(lines[-1][:19] + "Z"), lines[-1]
    finished = kubectl(
        release, "get", "pods", "-l", f"job-name={job}", "-o",
        'jsonpath={.items[*].status.containerStatuses[?(@.name=="bootstrap")]'
        ".state.terminated.finishedAt}",
    ).split()
    assert finished, f"the bootstrap container of {job} has not finished"
    return parse_time(max(finished)), (
        f"no 'bootstrap recorded' line in the log of {job}; its bootstrap container finished "
        f"at {max(finished)}"
    )


def helm_upgrade(release: dict, *sets: str) -> None:
    """Run `helm upgrade --reuse-values` with these `--set` values, without waiting."""
    command = [
        "helm", "upgrade", release["release"], str(release["chart_path"]),
        "-n", release["namespace"], "--kubeconfig", release["kubeconfig_path"],
        "--reuse-values", "--timeout", "15m",
    ]
    for value in sets:
        command += ["--set", value]
    subprocess.run(command, check=True)


async def replacing_job(release: dict, previous: str) -> str:
    """Wait until one bootstrap Job other than `previous` exists, and return its name."""
    deadline = time.monotonic() + 120
    jobs = bootstrap_jobs(release)
    while time.monotonic() < deadline:
        jobs = bootstrap_jobs(release)
        if previous not in jobs:
            break
        await asyncio.sleep(3)
    assert len(jobs) == 1 and jobs[0] != previous, (
        f"after the upgrade the bootstrap Jobs are {jobs}; expected one Job other than "
        f"{previous}"
    )
    return jobs[0]


def upgraded_pods(release: dict, component: str) -> list[dict]:
    """Return the pods of this component that run with the upgraded work pool.

    Pods of the previous revision can still be listed while they stop, so a pod counts only
    when it is not being deleted and its pod template names the upgraded work pool.
    """
    pods = json.loads(kubectl(
        release, "get", "pods", "-l", f"app.kubernetes.io/component={component}", "-o", "json",
    ))["items"]
    return [
        pod for pod in pods
        if not pod["metadata"].get("deletionTimestamp")
        and UPGRADED_WORK_POOL in json.dumps(pod["spec"]["containers"])
    ]


def current_pod(release: dict, component: str) -> dict:
    """Return the one pod of this component that runs with the upgraded work pool."""
    current = upgraded_pods(release, component)
    assert len(current) == 1, (
        f"expected one {component} pod with work pool {UPGRADED_WORK_POOL}, found "
        f"{[pod['metadata']['name'] for pod in current]}"
    )
    return current[0]


def is_ready(pod: dict) -> bool:
    """Whether the pod's `Ready` condition is true."""
    return any(
        condition["type"] == "Ready" and condition["status"] == "True"
        for condition in pod["status"].get("conditions", [])
    )


def ready_since(pod: dict) -> datetime:
    """Return when the pod's `Ready` condition last became true."""
    for condition in pod["status"].get("conditions", []):
        if condition["type"] == "Ready":
            assert condition["status"] == "True", (pod["metadata"]["name"], condition)
            return parse_time(condition["lastTransitionTime"])
    raise AssertionError(f"pod {pod['metadata']['name']} has no Ready condition")


def refusal(release: dict, pod: dict, container: str) -> tuple[str, str] | None:
    """Return when the container's previous run ended and its start check refusal, or None.

    The refusal is the line that names the upgraded work pool as the expected one. Only an
    image with the start check logs it.
    """
    statuses = pod["status"].get("containerStatuses", [])
    status = next((entry for entry in statuses if entry["name"] == container), None)
    previous = (status or {}).get("lastState", {}).get("terminated")
    if not previous:
        return None
    logs = kubectl(release, "logs", pod["metadata"]["name"], "-c", container, "--previous")
    lines = [
        line for line in logs.splitlines()
        if "the bootstrap record names" in line and f"work pool {UPGRADED_WORK_POOL}" in line
    ]
    return (previous["finishedAt"], lines[-1]) if lines else None


def held_job_state(release: dict, job: str) -> str:
    """Return the state of the held Job's pods: `waiting`, `pending` or `scheduled`.

    `waiting`: no pod is marked unschedulable yet, because the Job controller has not created
    the pod or the scheduler has not tried it yet. `pending`: every pod is `Pending` because it
    cannot be scheduled, so the hold applies. `scheduled`: a pod was given a node, so the hold
    did not apply.
    """
    pods = json.loads(
        kubectl(release, "get", "pods", "-l", f"job-name={job}", "-o", "json")
    )["items"]

    def scheduled(pod: dict, status: str) -> bool:
        return any(
            condition["type"] == "PodScheduled" and condition["status"] == status
            for condition in pod["status"].get("conditions", [])
        )

    if any(
        pod["status"].get("phase", "Pending") != "Pending" or scheduled(pod, "True")
        for pod in pods
    ):
        return "scheduled"
    if pods and all(scheduled(pod, "False") for pod in pods):
        return "pending"
    return "waiting"


async def wait_for_refusal(release: dict, held_job: str) -> tuple[str, str]:
    """While the Job is held, wait for the new Sync API pod's refusal; fail if it gets Ready.

    The record names the previous work pool for as long as the Job is held, so a Sync API
    pod that becomes Ready then did not check the record. The Job's pod can be created and
    marked unschedulable a moment after the Job exists, so the hold is confirmed before the
    refusal is returned, and a scheduled pod fails the test at once.
    """
    deadline = time.monotonic() + HOLD_TIMEOUT_SECONDS
    found = None
    state = "waiting"
    while time.monotonic() < deadline:
        state = held_job_state(release, held_job)
        assert state != "scheduled", (
            f"a pod of the held bootstrap Job {held_job} was scheduled, so the hold did not apply"
        )
        for pod in upgraded_pods(release, "api"):
            assert not is_ready(pod), (
                f"the Sync API pod {pod['metadata']['name']} became Ready while the bootstrap "
                f"Job {held_job} was held and the record named the previous work pool"
            )
            found = found or refusal(release, pod, "api")
        if found and state == "pending":
            return found
        await asyncio.sleep(3)
    if found:
        raise AssertionError(
            f"the held bootstrap Job {held_job} had no unschedulable pod within "
            f"{HOLD_TIMEOUT_SECONDS} s (last state: {state}), so the hold did not apply"
        )
    raise AssertionError(
        f"no Sync API pod with work pool {UPGRADED_WORK_POOL} logged the start check's refusal "
        f"within {HOLD_TIMEOUT_SECONDS} s while the bootstrap Job {held_job} was held"
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

        # The worker reports its heartbeat a few seconds after it starts. A worker that exited
        # just before the bootstrap wrote its record starts again only after its restart
        # back-off, which Kubernetes caps at 300 s, so the wait is longer than that cap.
        deadline = time.monotonic() + WORKER_STATUS_SECONDS
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

    # Upgrade with settings the bootstrap reads: the Job gets a new name (RR-34). The work pool
    # is part of the bootstrap record, so the record no longer matches the new pods (FR-007b).
    # The Job is held, so the new pods start while the record names the previous work pool.
    helm_upgrade(
        release,
        f"s3.prefix={UPGRADED_PREFIX}",
        f"settings.workPool={UPGRADED_WORK_POOL}",
        f"bootstrap.resources.requests.cpu={HOLD_CPU}",
    )
    held_job = await replacing_job(release, first_job)
    refused_at, refused_line = await wait_for_refusal(release, held_job)
    print(f"held Job {held_job}; Sync API refused run ended at {refused_at}: {refused_line}")

    # Release the hold: the Job gets a new name again, runs and writes the record.
    helm_upgrade(release, f"bootstrap.resources.requests.cpu={RELEASE_CPU}")
    new_job = await replacing_job(release, held_job)
    wait_for_job(release, new_job)
    wait_for_rollout(release)

    # The new pods became ready only after the new Job wrote the bootstrap record. The exact
    # number of restarts is not checked.
    completed = job_completion_time(release, new_job)
    written, evidence = record_written(release, new_job)
    for component, allowance in (("api", 0), ("worker", WORKER_CHECK_SECONDS)):
        pod = current_pod(release, component)
        ready = ready_since(pod)
        restarts = [entry["restartCount"] for entry in pod["status"]["containerStatuses"]]
        timeline = (
            f"{component} pod {pod['metadata']['name']} (restarts {restarts}) Ready at "
            f"{ready.isoformat()}; record written at {written.isoformat()} ({evidence}); "
            f"Job {new_job} completed at {completed.isoformat()}"
        )
        print(timeline)
        assert (ready - written).total_seconds() >= -allowance, (
            f"the pod became Ready before the bootstrap record: {timeline}"
        )

    await check_sync_api(release)
