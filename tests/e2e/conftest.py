"""E2E fixtures: deploy each chart (from this repo) into the vcluster.

Every chart gets its own session-scoped deployment fixture so the per-chart
pytest jobs in CI only exercise the chart they care about. Charts are installed
from the local `charts/` directory (not from the OCI registry) so the test
reflects the working-tree changes.
"""

import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import kr8s.asyncio
import pytest
import yaml
from kr8s.asyncio.objects import Service as AsyncService

from tests.conftest import CHARTS_DIR, REPO_ROOT
from tests.helpers.utils import INFRAHUB_ADMIN_TOKEN, wait_for_http

FIXTURES_DIR = Path(__file__).parent.resolve() / "fixtures" / "helm"

# Charts that live in this repo. Cross-chart dependencies between them point at
# the OCI registry in Chart.yaml; for e2e we rewrite those to local file://
# paths so the tests deploy the working-tree charts (and don't depend on a
# given version being published yet). All images and charts are served
# anonymously from registry.opsmill.io, so no registry credentials are needed.
LOCAL_CHART_NAMES = {
    "infrahub",
    "infrahub-enterprise",
    "infrahub-backup",
    "infrahub-observability",
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _register_namespace(request: pytest.FixtureRequest, namespace: str) -> None:
    """Track a namespace so failure diagnostics dump its pods/logs."""
    namespaces = getattr(request.session, "_e2e_namespaces", None)
    if namespaces is None:
        namespaces = set()
        request.session._e2e_namespaces = namespaces
    namespaces.add(namespace)


def helm_install(
    *,
    release: str,
    chart_path: Path,
    namespace: str,
    kubeconfig: str,
    values_files: list[Path] | None = None,
    sets: dict[str, str] | None = None,
    timeout: str = "15m",
    dependency_update: bool = False,
) -> None:
    """Run `helm upgrade --install` for a local chart and wait for readiness."""
    cmd = [
        "helm", "upgrade", "--install", release, str(chart_path),
        "--create-namespace", "-n", namespace,
        "--kubeconfig", kubeconfig,
        "--wait", "--timeout", timeout,
    ]
    if dependency_update:
        cmd.append("--dependency-update")
    for values_file in values_files or []:
        cmd.extend(["-f", str(values_file)])
    for key, value in (sets or {}).items():
        cmd.extend(["--set", f"{key}={value}"])
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Chart staging — vendor local sibling charts via file:// and resolve deps.
# ---------------------------------------------------------------------------
def _local_chart_version(name: str) -> str:
    data = yaml.safe_load((CHARTS_DIR / name / "Chart.yaml").read_text())
    return str(data["version"])


def _stage_chart(name: str, staging: Path) -> Path:
    """Copy a chart into the staging dir, rewrite in-repo OCI deps to local
    file:// paths, resolve its dependencies, and return the staged path.

    Recurses into sibling charts so a parent packages a fully-resolved child.
    A disabled in-repo subchart (e.g. observability inside infrahub) packages
    fine without its synced provisioning — the templates tolerate empty files.
    """
    dest = staging / name
    if dest.exists():
        return dest

    shutil.copytree(
        CHARTS_DIR / name,
        dest,
        ignore=shutil.ignore_patterns("charts", "Chart.lock", "*.tgz"),
    )

    chart_yaml = dest / "Chart.yaml"
    data = yaml.safe_load(chart_yaml.read_text())
    changed = False
    for dep in data.get("dependencies") or []:
        repo = dep.get("repository") or ""
        if dep["name"] in LOCAL_CHART_NAMES and "registry.opsmill.io" in repo:
            _stage_chart(dep["name"], staging)  # resolve child first
            dep["repository"] = f"file://../{dep['name']}"
            dep["version"] = _local_chart_version(dep["name"])
            changed = True
    if changed:
        chart_yaml.write_text(yaml.safe_dump(data, sort_keys=False))

    subprocess.run(["helm", "dependency", "update", str(dest)], check=True)
    return dest


@pytest.fixture(scope="session")
def staged_charts(tmp_path_factory) -> dict[str, Path]:
    """Prepare local charts with their dependencies resolved (once per session).

    Returns a mapping of chart name -> staged chart path.
    """
    staging = tmp_path_factory.mktemp("charts")
    return {
        "infrahub": _stage_chart("infrahub", staging),
        "infrahub-enterprise": _stage_chart("infrahub-enterprise", staging),
    }


@asynccontextmanager
async def portforward_service(
    kubeconfig: str,
    namespace: str,
    remote_port: int,
    *,
    name: str | None = None,
    label_selector: str | None = None,
    ready_path: str | None = None,
    ready_auth: tuple[str, str] | None = None,
    ready_status: int = 200,
):
    """Open a fresh port-forward to a Service and yield the local URL.

    The Service is found by name or by label selector. When ready_path is set,
    the URL is polled until it returns ready_status before yielding.
    """
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    if name:
        service = await AsyncService.get(name, namespace=namespace, api=api)
    elif label_selector:
        services = [
            svc
            async for svc in AsyncService.list(
                namespace=namespace, label_selector=label_selector, api=api
            )
        ]
        if not services:
            raise AssertionError(
                f"No Service matching '{label_selector}' in namespace '{namespace}'"
            )
        service = services[0]
    else:
        raise ValueError("portforward_service requires name or label_selector")

    async with service.portforward(remote_port=remote_port, local_port="auto") as port:
        url = f"http://localhost:{port}"
        if ready_path:
            await wait_for_http(
                f"{url}{ready_path}",
                timeout=300.0,
                interval=5.0,
                expected_status=ready_status,
                auth=ready_auth,
            )
        yield url


# ---------------------------------------------------------------------------
# Fixture: infrahub_k8s (community chart)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def infrahub_k8s(
    vcluster: dict, staged_charts, request
) -> AsyncGenerator[dict, None]:
    """Deploy the community infrahub chart from charts/infrahub."""
    kubeconfig = vcluster["kubeconfig_path"]
    namespace = "infrahub"
    _register_namespace(request, namespace)

    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-values.yaml"],
    )

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector="service=infrahub-server", ready_path="/api/config",
    ):
        pass  # initial health check

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "token": INFRAHUB_ADMIN_TOKEN,
        "server_label": "service=infrahub-server",
    }


# ---------------------------------------------------------------------------
# Fixture: infrahub_enterprise_k8s (enterprise chart)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def infrahub_enterprise_k8s(
    vcluster: dict, staged_charts, request
) -> AsyncGenerator[dict, None]:
    """Deploy the enterprise chart from charts/infrahub-enterprise."""
    kubeconfig = vcluster["kubeconfig_path"]
    namespace = "infrahub-enterprise"
    _register_namespace(request, namespace)

    helm_install(
        release="infrahub-enterprise",
        chart_path=staged_charts["infrahub-enterprise"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-enterprise-values.yaml"],
    )

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector="service=infrahub-server", ready_path="/api/config",
    ):
        pass

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "token": INFRAHUB_ADMIN_TOKEN,
        "server_label": "service=infrahub-server",
    }


# ---------------------------------------------------------------------------
# Fixture: observability_k8s (observability chart)
# ---------------------------------------------------------------------------
def _ensure_observability_provisioning() -> None:
    """Sync Grafana provisioning from upstream if not already present.

    The dashboards/datasources are fetched at package time and are not
    committed; render them now so the chart deploys with datasources.
    """
    datasources = CHARTS_DIR / "infrahub-observability" / "files" / "datasources.yaml"
    if datasources.exists():
        return
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "sync-upstream.sh")],
        cwd=str(REPO_ROOT),
        check=True,
    )


@pytest.fixture(scope="session")
async def observability_k8s(
    vcluster: dict, staged_charts, request
) -> AsyncGenerator[dict, None]:
    """Deploy Infrahub + the observability stack together in one namespace.

    Infrahub is wired to send OTLP traces to the observability release's Tempo
    (`obs-tempo:4317`), and Alloy scrapes the Infrahub server, so the test can
    assert that Infrahub's own metrics and traces are queryable through Grafana.
    Both live in the same namespace so the chart's short-name service URLs
    (e.g. `infrahub-infrahub-server:8000`, `obs-tempo:4317`) resolve.
    """
    kubeconfig = vcluster["kubeconfig_path"]
    namespace = "observability"
    obs_release = "obs"
    _register_namespace(request, namespace)

    _ensure_observability_provisioning()

    # Deploy Infrahub first with tracing pointed at the (soon-to-exist) Tempo;
    # the OTLP exporter retries, so spans flow once Tempo is up. Readiness does
    # not depend on the collector being reachable.
    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-values.yaml"],
        sets={
            "global.tracing.enabled": "true",
            "global.tracing.endpoint": f"{obs_release}-tempo:4317",
            "global.tracing.protocol": "grpc",
            "global.tracing.insecure": "true",
        },
    )

    # Deploy the observability stack. Alloy scrapes `infrahub-infrahub-server`
    # (global.infrahubReleaseName defaults to "infrahub") in this namespace.
    helm_install(
        release=obs_release,
        chart_path=CHARTS_DIR / "infrahub-observability",
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-observability-values.yaml"],
        timeout="12m",
        dependency_update=True,
    )

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "release": obs_release,
        "grafana_label": "app.kubernetes.io/name=grafana",
        "grafana_auth": ("admin", "admin"),
        "server_label": "service=infrahub-server",
        "token": INFRAHUB_ADMIN_TOKEN,
    }


# ---------------------------------------------------------------------------
# Fixture: minio_k8s (in-cluster S3 backend for the backup test)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def minio_k8s(infrahub_k8s: dict) -> AsyncGenerator[dict, None]:
    """Deploy MinIO (with the backup bucket pre-created) into the namespace.

    The bucket is created by the MinIO container command, and the credentials
    Secret consumed by the backup/restore Jobs is created here via kr8s.
    """
    from kr8s.asyncio.objects import Deployment, Secret, Service

    kubeconfig = infrahub_k8s["kubeconfig_path"]
    namespace = infrahub_k8s["namespace"]
    bucket = "infrahub-backups"

    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    # MinIO Deployment + Service from the manifest fixture.
    manifests = list(yaml.safe_load_all((FIXTURES_DIR / "minio.yaml").read_text()))
    objects = {"Deployment": Deployment, "Service": Service}
    deployment = None
    for manifest in manifests:
        manifest.setdefault("metadata", {})["namespace"] = namespace
        obj = objects[manifest["kind"]](manifest, namespace=namespace, api=api)
        await obj.create()
        if manifest["kind"] == "Deployment":
            deployment = obj

    # Credentials Secret consumed by the backup/restore Jobs.
    secret = Secret(
        {
            "metadata": {"name": "minio-creds", "namespace": namespace},
            "stringData": {
                "AWS_ACCESS_KEY_ID": "minioadmin",
                "AWS_SECRET_ACCESS_KEY": "minioadmin",
            },
        },
        namespace=namespace,
        api=api,
    )
    await secret.create()

    await deployment.wait("condition=Available", timeout=300)

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "bucket": bucket,
        "endpoint": "http://minio:9000",
        "secret_name": "minio-creds",
        "service_name": "minio",
    }
