"""E2E: deploy infrahub-backup against a running Infrahub and prove a backup
restores correctly.

Flow: seed a tag -> run the backup Job (S3/MinIO) -> delete the tag ->
run the restore Job -> assert the tag is back.
"""

import asyncio

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
)

pytestmark = [pytest.mark.e2e, pytest.mark.k8s, pytest.mark.backup]


def _latest_backup_key(minio_url: str, bucket: str) -> str:
    """List the backup bucket (blocking boto3) and return the newest artifact.

    Run via asyncio.to_thread so it does not block the event loop that drives
    the kr8s port-forward to MinIO.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=minio_url,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
        region_name="us-east-1",
    )
    objects = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
    keys = sorted(obj["Key"] for obj in objects if obj["Key"].endswith(".tar.gz"))
    if not keys:
        raise AssertionError(f"No backup artifact found in s3://{bucket}")
    return keys[-1]


async def test_backup_restore(infrahub_k8s, minio_k8s):
    """A backup taken via the chart restores the seeded data."""
    kubeconfig = infrahub_k8s["kubeconfig_path"]
    namespace = infrahub_k8s["namespace"]
    token = infrahub_k8s["token"]
    bucket = minio_k8s["bucket"]
    chart = CHARTS_DIR / "infrahub-backup"

    common_s3 = {"image.pullPolicy": "IfNotPresent"}

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
        sets={
            **common_s3,
            "backup.enabled": "true",
            "backup.mode": "job",
            "backup.options.force": "true",
            "backup.storage.type": "s3",
            "backup.storage.s3.bucket": bucket,
            "backup.storage.s3.endpoint": minio_k8s["endpoint"],
            "backup.storage.s3.region": "us-east-1",
            "backup.storage.s3.secretName": minio_k8s["secret_name"],
        },
        timeout="10m",
    )
    await wait_for_job(kubeconfig, namespace, "ihb-backup-infrahub-backup")

    # 3. Locate the artifact written to MinIO (boto3 is blocking, so run it off
    # the event loop that's pumping the port-forward).
    async with portforward_service(
        kubeconfig, namespace, 9000, name=minio_k8s["service_name"]
    ) as minio_url:
        backup_key = await asyncio.to_thread(_latest_backup_key, minio_url, bucket)

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
        sets={
            **common_s3,
            "restore.enabled": "true",
            "restore.storage.type": "s3",
            "restore.storage.s3.bucket": bucket,
            "restore.storage.s3.key": backup_key,
            "restore.storage.s3.endpoint": minio_k8s["endpoint"],
            "restore.storage.s3.region": "us-east-1",
            "restore.storage.s3.secretName": minio_k8s["secret_name"],
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
