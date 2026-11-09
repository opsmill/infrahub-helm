"""Special e2e test: back up and restore, through the chart, an Infrahub whose Neo4j
database runs in another namespace.

NOT part of CI. It needs an infrahub-backup image built from
opsmill/infrahub-backup#172 ("back up and restore external databases on
Kubernetes"), which no released chart appVersion points at, so the module
carries only the ``manual`` marker. Run it on demand with::

    uv run pytest -v -m manual tests/e2e/test_infrahub_backup_external_neo4j.py

The session fixture builds the image from the pull request (or from
``INFRAHUB_BACKUP_SOURCE_DIR``, or takes ``INFRAHUB_BACKUP_IMAGE`` as is),
imports it into the vcluster, installs a Neo4j Enterprise server in its own
namespace and deploys Infrahub with ``neo4j.enabled=false`` pointed at it.

What it proves:

- the backup Job captures the external Neo4j database with the tools in its
  own container: it logs the direct mode line, and creates no Job and no
  Secret, under the Role the chart creates;
- the restore Job, with ``externalDatabase.allowRestore``, copies the archive
  under ``seed/`` in the restore bucket, the Neo4j server downloads it from
  there, and the data from before the backup is back.
"""

import asyncio
import subprocess

import pytest

from tests.conftest import CHARTS_DIR
from tests.e2e.conftest import helm_install, portforward_service
from tests.e2e.test_infrahub_backup import _latest_backup_key
from tests.helpers.utils import (
    modify_infrahub_data,
    seed_infrahub_data,
    verify_infrahub_data,
    wait_for_job,
)

pytestmark = pytest.mark.manual

# The line infrahub-backup logs when it runs the database tools in its own
# container instead of creating a transient Job (src/internal/app/external_local.go).
DIRECT_MODE_LINE = "Running the external database tools in this process, with no transient Job"
# infrahub-backup labels every transient Job, Pod and Secret it creates with this key.
TRANSIENT_LABEL = "infrahub-backup/transient"
# Neo4j 2025 reports no store size, so a capture of an external server needs one.
SCRATCH_SIZE = "2Gi"
JOB_TIMEOUT = 1200


def _kubectl(deployment: dict, *args: str) -> str:
    return subprocess.run(
        [
            "kubectl", "-n", deployment["namespace"],
            "--kubeconfig", deployment["kubeconfig_path"], *args,
        ],
        capture_output=True, text=True, check=True,
    ).stdout


def _common_sets(deployment: dict) -> dict[str, str]:
    """Values both Jobs share: the image under test, and the external database
    settings the topology needs.

    The Neo4j server serves no TLS, which infrahub-backup accepts only with
    ``insecureTLS``. ``--external-db-image`` names the image under test, which
    a build that is not a release requires; the Job runs in direct mode, so no
    pod runs it.
    """
    return {
        "image.repository": deployment["backup_image_repository"],
        "image.tag": deployment["backup_image_tag"],
        "image.pullPolicy": "IfNotPresent",
        "externalDatabase.insecureTLS": "true",
        "externalDatabase.scratchSize": SCRATCH_SIZE,
    }


def _assert_direct_mode(deployment: dict, job: str) -> None:
    logs = _kubectl(deployment, "logs", f"job/{job}")
    assert DIRECT_MODE_LINE in logs, f"Job '{job}' did not run the tools in its own container:\n{logs}"
    transient = _kubectl(deployment, "get", "jobs,pods,secrets", "-l", TRANSIENT_LABEL, "-o", "name")
    assert not transient.split(), f"Job '{job}' created transient objects: {transient}"


async def test_backup_restore_external_neo4j(infrahub_external_neo4j_k8s):
    deployment = infrahub_external_neo4j_k8s
    kubeconfig = deployment["kubeconfig_path"]
    namespace = deployment["namespace"]
    token = deployment["token"]
    s3 = deployment["s3"]
    chart = CHARTS_DIR / "infrahub-backup"
    common = _common_sets(deployment)
    image_arg = f"--external-db-image={deployment['backup_image']}"
    s3_sets = {
        "storage.type": "s3",
        "storage.s3.bucket": s3["bucket"],
        "storage.s3.endpoint": s3["endpoint"],
        "storage.s3.region": "us-east-1",
        "storage.s3.secretName": s3["secret_name"],
    }

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=deployment["server_label"], ready_path="/api/config",
    ) as url:
        seed = await seed_infrahub_data(url, token)

    helm_install(
        release="ihb-backup",
        chart_path=chart,
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[s3["ca_values"]],
        sets={
            **common,
            **{f"backup.{key}": value for key, value in s3_sets.items()},
            "backup.enabled": "true",
            "backup.options.force": "true",
            "backup.options.extraArgs[0]": image_arg,
        },
        timeout="20m",
    )
    await wait_for_job(kubeconfig, namespace, "ihb-backup-infrahub-backup", timeout=JOB_TIMEOUT)
    _assert_direct_mode(deployment, "ihb-backup-infrahub-backup")

    async with portforward_service(
        kubeconfig, namespace, s3["port"], name=s3["service_name"]
    ) as s3_url:
        backup_key = await asyncio.to_thread(_latest_backup_key, s3_url, s3)

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=deployment["server_label"], ready_path="/api/config",
    ) as url:
        await modify_infrahub_data(url, token, seed)

    helm_install(
        release="ihb-restore",
        chart_path=chart,
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[s3["ca_values"]],
        sets={
            **common,
            **{f"restore.{key}": value for key, value in s3_sets.items()},
            "restore.enabled": "true",
            "restore.storage.s3.key": backup_key,
            "restore.options.extraArgs[0]": image_arg,
            "externalDatabase.allowRestore": "true",
        },
        timeout="20m",
    )
    await wait_for_job(kubeconfig, namespace, "ihb-restore-infrahub-backup-restore", timeout=JOB_TIMEOUT)
    _assert_direct_mode(deployment, "ihb-restore-infrahub-backup-restore")

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=deployment["server_label"], ready_path="/api/config",
    ) as url:
        await verify_infrahub_data(url, token, seed)
