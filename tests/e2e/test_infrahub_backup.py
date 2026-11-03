"""E2E: deploy infrahub-backup against a running Infrahub and prove a backup
restores correctly.

Flow: seed a tag -> run the backup Job (S3, served by Garage) -> delete the tag ->
run the restore Job -> assert the tag is back -> delete the tag again ->
trigger the restore CronJob -> assert the tag is back again.

The Jobs reach Garage over HTTPS, with a certificate issued by a private CA that
the test generates. They trust it through the chart's `extraEnv`,
`extraVolumes` and `extraVolumeMounts` values, which mount the CA from a
ConfigMap and point `SSL_CERT_FILE` at it. A restore without these values must
be rejected, which shows that certificate verification is on and that the CA,
not the system trust store, let the other Jobs through.
"""

import asyncio
import subprocess

import boto3
import pytest

from tests.conftest import CHARTS_DIR
from tests.e2e.conftest import (
    helm_install,
    portforward_service,
)
from tests.helpers.utils import (
    modify_infrahub_data,
    seed_infrahub_data,
    verify_infrahub_data,
    wait_for_job,
    wait_for_job_failure,
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.backup]


def _latest_backup_key(s3_url: str, s3: dict) -> str:
    """List the backup bucket (blocking boto3) and return the newest artifact.

    Run via asyncio.to_thread so it does not block the event loop that drives
    the kr8s port-forward to the S3 server.
    """
    bucket = s3["bucket"]
    client = boto3.client(
        "s3",
        endpoint_url=s3_url,
        aws_access_key_id=s3["access_key"],
        aws_secret_access_key=s3["secret_key"],
        region_name="us-east-1",
    )
    objects = client.list_objects_v2(Bucket=bucket).get("Contents", [])
    keys = sorted(obj["Key"] for obj in objects if obj["Key"].endswith(".tar.gz"))
    if not keys:
        raise AssertionError(f"No backup artifact found in s3://{bucket}")
    return keys[-1]


async def test_backup_restore(infrahub_k8s, s3_k8s):
    """A backup taken via the chart restores the seeded data."""
    kubeconfig = infrahub_k8s["kubeconfig_path"]
    namespace = infrahub_k8s["namespace"]
    token = infrahub_k8s["token"]
    bucket = s3_k8s["bucket"]
    chart = CHARTS_DIR / "infrahub-backup"

    common_s3 = {"image.pullPolicy": "IfNotPresent"}
    ca_values = [s3_k8s["ca_values"]]

    # 1. Seed a tag.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        seed = await seed_infrahub_data(url, token)

    # 2. Run the backup Job (post-install hook; helm --wait blocks on it).
    helm_install(
        release="ihb-backup",
        chart_path=chart,
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=ca_values,
        sets={
            **common_s3,
            "backup.enabled": "true",
            "backup.mode": "job",
            "backup.options.force": "true",
            "backup.storage.type": "s3",
            "backup.storage.s3.bucket": bucket,
            "backup.storage.s3.endpoint": s3_k8s["endpoint"],
            "backup.storage.s3.region": "us-east-1",
            "backup.storage.s3.secretName": s3_k8s["secret_name"],
        },
        timeout="10m",
    )
    await wait_for_job(kubeconfig, namespace, "ihb-backup-infrahub-backup")

    # 3. Locate the artifact written to the bucket (boto3 is blocking, so run it
    # off the event loop that's pumping the port-forward).
    async with portforward_service(
        kubeconfig, namespace, s3_k8s["port"], name=s3_k8s["service_name"]
    ) as s3_url:
        backup_key = await asyncio.to_thread(_latest_backup_key, s3_url, s3_k8s)

    # 4. Delete the tag so the restore has something to prove.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        await modify_infrahub_data(url, token, seed)

    # 5. Run the restore Job from the same artifact.
    helm_install(
        release="ihb-restore",
        chart_path=chart,
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=ca_values,
        sets={
            **common_s3,
            "restore.enabled": "true",
            "restore.storage.type": "s3",
            "restore.storage.s3.bucket": bucket,
            "restore.storage.s3.key": backup_key,
            "restore.storage.s3.endpoint": s3_k8s["endpoint"],
            "restore.storage.s3.region": "us-east-1",
            "restore.storage.s3.secretName": s3_k8s["secret_name"],
        },
        timeout="10m",
    )
    await wait_for_job(kubeconfig, namespace, "ihb-restore-infrahub-backup-restore")

    # 6. Verify the tag is back (fresh port-forward; restore may bounce pods).
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        await verify_infrahub_data(url, token, seed)

    # 7. Delete the tag again so the scheduled restore has something to prove.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        await modify_infrahub_data(url, token, seed)

    # 8. Deploy the restore CronJob in latest-selection mode and fire it
    # manually rather than waiting out the schedule. `--latest --s3` picks the
    # newest archive in the bucket — the one the backup Job just wrote.
    helm_install(
        release="ihb-restore-cron",
        chart_path=chart,
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=ca_values,
        sets={
            **common_s3,
            "restore.enabled": "true",
            "restore.mode": "cronjob",
            "restore.storage.type": "s3",
            "restore.storage.s3.bucket": bucket,
            "restore.storage.s3.latest": "true",
            "restore.storage.s3.endpoint": s3_k8s["endpoint"],
            "restore.storage.s3.region": "us-east-1",
            "restore.storage.s3.secretName": s3_k8s["secret_name"],
        },
        timeout="10m",
    )
    subprocess.run(
        [
            "kubectl", "-n", namespace, "--kubeconfig", kubeconfig,
            "create", "job", "ihb-restore-cron-manual",
            "--from=cronjob/ihb-restore-cron-infrahub-backup-restore",
        ],
        check=True,
    )
    await wait_for_job(kubeconfig, namespace, "ihb-restore-cron-manual")

    # 9. Verify the scheduled restore brought the tag back.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_k8s["server_label"], ready_path="/api/config",
    ) as url:
        await verify_infrahub_data(url, token, seed)


async def test_restore_without_the_ca_is_rejected(infrahub_k8s, s3_k8s):
    """A restore without the CA values fails on the S3 certificate.

    `--latest` lists the bucket before it touches a database, so the run fails
    at the TLS handshake and leaves Infrahub as it was.
    """
    kubeconfig = infrahub_k8s["kubeconfig_path"]
    namespace = infrahub_k8s["namespace"]

    helm_install(
        release="ihb-restore-untrusted",
        chart_path=CHARTS_DIR / "infrahub-backup",
        namespace=namespace,
        kubeconfig=kubeconfig,
        sets={
            "image.pullPolicy": "IfNotPresent",
            "restore.enabled": "true",
            "restore.mode": "cronjob",
            "restore.storage.type": "s3",
            "restore.storage.s3.bucket": s3_k8s["bucket"],
            "restore.storage.s3.latest": "true",
            "restore.storage.s3.endpoint": s3_k8s["endpoint"],
            "restore.storage.s3.region": "us-east-1",
            "restore.storage.s3.secretName": s3_k8s["secret_name"],
        },
        timeout="10m",
    )
    subprocess.run(
        [
            "kubectl", "-n", namespace, "--kubeconfig", kubeconfig,
            "create", "job", "ihb-restore-untrusted-manual",
            "--from=cronjob/ihb-restore-untrusted-infrahub-backup-restore",
        ],
        check=True,
    )
    logs = await wait_for_job_failure(kubeconfig, namespace, "ihb-restore-untrusted-manual")

    assert "certificate signed by unknown authority" in logs, (
        f"expected a certificate verification failure, got:\n{logs}"
    )
