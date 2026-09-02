"""E2E fixtures: deploy each chart (from this repo) into the vcluster.

Every chart gets its own session-scoped deployment fixture so the per-chart
pytest jobs in CI only exercise the chart they care about. Charts are installed
from the local `charts/` directory (not from the OCI registry) so the test
reflects the working-tree changes.
"""

import asyncio
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from string import Template
from typing import AsyncGenerator

import kr8s.asyncio
import pytest
import yaml
from kr8s.asyncio.objects import Service as AsyncService

from tests.conftest import CHARTS_DIR, REPO_ROOT
from tests.helpers.tls import (
    create_certificate_authority,
    issue_server_certificate,
    service_dns_names,
)
from tests.helpers.utils import (
    INFRAHUB_ADMIN_TOKEN,
    wait_for_http,
    wait_for_infrahub_branch_ready,
)

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
    "infrahub-mcp",
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
    """Run `helm upgrade --install` for a local chart and wait for readiness.

    We deliberately do *not* use helm's own ``--wait``. Helm (v4, via kstatus)
    treats a Deployment that trips its ``progressDeadlineSeconds`` — the
    Kubernetes default is 600s — as a *terminal failure* and aborts, even though
    the rollout is still making progress and our ``--timeout`` is far larger. On
    a cold/loaded CI runner the Infrahub stack (neo4j, prefect + postgres,
    rabbitmq, redis, then the server + task-worker) routinely needs more than
    600s just to pull images and start, so ``helm --wait`` fails spuriously and
    the whole test errors out during setup. Instead we let helm apply the chart
    and then wait for readiness ourselves with ``wait_for_workloads``, which
    honors the intended ``timeout`` and tolerates a slow-but-progressing
    rollout. See https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#failed-deployment
    """
    cmd = [
        "helm", "upgrade", "--install", release, str(chart_path),
        "--create-namespace", "-n", namespace,
        "--kubeconfig", kubeconfig,
        "--timeout", timeout,
    ]
    if dependency_update:
        cmd.append("--dependency-update")
    for values_file in values_files or []:
        cmd.extend(["-f", str(values_file)])
    for key, value in (sets or {}).items():
        cmd.extend(["--set", f"{key}={value}"])
    subprocess.run(cmd, check=True)
    wait_for_workloads(namespace=namespace, kubeconfig=kubeconfig, timeout=timeout)


def wait_for_workloads(*, namespace: str, kubeconfig: str, timeout: str = "15m") -> None:
    """Block until every workload in a namespace is ready, up to ``timeout``.

    This replaces helm's ``--wait`` (see ``helm_install``). For Deployments we
    wait on the ``Available`` condition: unlike helm's kstatus waiter and
    ``kubectl rollout status``, ``Available`` is *not* invalidated when a
    Deployment briefly exceeds its progress deadline, so a rollout that is slow
    but still progressing is tolerated for the full ``timeout``. StatefulSets and
    DaemonSets have no progress-deadline concept, so ``rollout status`` is safe
    for them (and covers per-node DaemonSet readiness). ``timeout`` is a Go
    duration string (e.g. "15m"), which both ``kubectl`` subcommands accept.
    """
    base = ["kubectl", "-n", namespace, "--kubeconfig", kubeconfig]

    def names(kind: str) -> list[str]:
        result = subprocess.run(
            [*base, "get", kind, "-o", "name"], capture_output=True, text=True, check=True
        )
        return result.stdout.split()

    deployments = names("deployment")
    if deployments:
        subprocess.run(
            [*base, "wait", "--for=condition=Available", f"--timeout={timeout}", *deployments],
            check=True,
        )
    # StatefulSets/DaemonSets: rollout status waits without a progress deadline.
    for kind in ("statefulset", "daemonset"):
        for obj in names(kind):
            subprocess.run([*base, "rollout", "status", obj, f"--timeout={timeout}"], check=True)


def install_traefik(
    *,
    namespace: str,
    kubeconfig: str,
    release: str = "traefik",
    version: str = "40.2.0",
) -> None:
    """Install Traefik as the ingress controller and wait for it.

    Traefik watches Ingress resources inside the vcluster and routes by Host
    header. Its Service is type LoadBalancer: vcluster ships an embedded load
    balancer that assigns it a node address reachable from the test runner, so
    tests hit the ``web`` entrypoint (port 80) directly with the Infrahub
    hostname — no port-forward needed. The chart registers a default
    IngressClass named after the release ("traefik").
    """
    subprocess.run(
        [
            "helm", "upgrade", "--install", release, "traefik",
            "--repo", "https://traefik.github.io/charts",
            "--version", version,
            "--create-namespace", "-n", namespace,
            "--kubeconfig", kubeconfig,
            "--set", "service.type=LoadBalancer",
            "--set", "deployment.replicas=1",
            "--wait", "--timeout", "5m",
        ],
        check=True,
    )


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


async def loadbalancer_url(
    kubeconfig: str,
    namespace: str,
    name: str,
    *,
    port: int = 80,
    timeout: float = 180.0,
) -> str:
    """Return the base URL of a LoadBalancer Service once it has an address.

    vcluster's embedded load balancer assigns the Service a node address that
    is reachable from the test runner, so the caller can hit it directly (with
    a Host header for name-based routing) instead of port-forwarding.
    """
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    service = await AsyncService.get(name, namespace=namespace, api=api)
    start = time.time()
    while time.time() - start < timeout:
        await service.refresh()
        ingress = (
            service.raw.get("status", {}).get("loadBalancer", {}) or {}
        ).get("ingress") or []
        for entry in ingress:
            address = entry.get("ip") or entry.get("hostname")
            if address:
                return f"http://{address}:{port}"
        await asyncio.sleep(3)
    raise AssertionError(
        f"Service '{name}' in '{namespace}' got no LoadBalancer address after {timeout}s"
    )


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
# Fixture: infrahub_mcp_k8s (infrahub + the infrahub-mcp sub-chart)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def infrahub_mcp_k8s(
    vcluster: dict, staged_charts, request
) -> AsyncGenerator[dict, None]:
    """Deploy Infrahub with the infrahub-mcp sub-chart enabled, behind a shared
    ingress.

    Traefik is installed into the namespace as the ingress controller, then
    Infrahub is deployed with the MCP sub-chart on. Both the Infrahub server
    (path "/") and the MCP
    server (path "/mcp") publish Ingress objects for the same host, so the
    controller serves them as a single virtual host — the MCP server is reached
    under "/mcp" on the very host that serves Infrahub. The MCP server is wired
    to the in-cluster Infrahub API with the admin token.
    """
    kubeconfig = vcluster["kubeconfig_path"]
    namespace = "infrahub-mcp"
    hostname = "infrahub-cluster.local"
    _register_namespace(request, namespace)

    install_traefik(namespace=namespace, kubeconfig=kubeconfig)

    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-values.yaml"],
        sets={
            "infrahubServer.ingress.enabled": "true",
            "infrahubServer.ingress.hostname": hostname,
            "infrahubServer.ingress.ingressClassName": "traefik",
            "infrahub-mcp.enabled": "true",
            "infrahub-mcp.image.pullPolicy": "IfNotPresent",
            "infrahub-mcp.infrahub.address": "http://infrahub-infrahub-server:8000",
            "infrahub-mcp.infrahub.apiToken.value": INFRAHUB_ADMIN_TOKEN,
            "infrahub-mcp.ingress.enabled": "true",
            "infrahub-mcp.ingress.hostname": hostname,
            "infrahub-mcp.ingress.ingressClassName": "traefik",
            "infrahub-mcp.ingress.path": "/mcp",
        },
    )

    # helm_install already gated on the server and MCP deployments being ready;
    # the test reaches both through the Traefik ingress (no port-forward).
    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "ingress_hostname": hostname,
        "ingress_service": "traefik",
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


# ---------------------------------------------------------------------------
# Fixture: infrahub_custom_ca_k8s (Infrahub trusting a private CA, plus two
# git servers behind HTTPS — one signed by that CA, one that is not)
# ---------------------------------------------------------------------------
# The custom-CA behaviour is not in a released Infrahub image yet, so the test
# runs against an image built from the pull request that adds it. Override the
# whole reference with INFRAHUB_CUSTOM_IMAGE to test another build; point
# INFRAHUB_SOURCE_DIR at a local infrahub checkout to skip the clone.
INFRAHUB_CUSTOM_CA_PR = "10487"

CUSTOM_CA_NAMESPACE = "infrahub-custom-ca"
# The Service name is also the hostname in the repository URL and in the SAN of
# the certificate, so these three cannot drift apart.
TRUSTED_GIT_SERVER = "git-https"
UNTRUSTED_GIT_SERVER = "git-https-untrusted"
CA_BUNDLE_CONFIGMAP = "infrahub-ca-bundle"
CA_BUNDLE_PATH = "/opt/infrahub/tls/ca-bundle.pem"


def build_custom_infrahub_image() -> str:
    """Build the Infrahub image carrying the pull request under test, and return
    its full reference.

    Progress goes to the console; only the reference comes back on stdout.
    """
    command = [
        str(REPO_ROOT / "scripts" / "build-infrahub-image.sh"),
        "--pr",
        INFRAHUB_CUSTOM_CA_PR,
    ]
    source_dir = os.environ.get("INFRAHUB_SOURCE_DIR")
    if source_dir:
        command.extend(["--source", source_dir])
    result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=True)
    image = result.stdout.strip()
    if not image:
        raise AssertionError(f"{' '.join(command)} printed no image reference")
    return image


def import_image_into_vcluster(image: str, cluster_name: str) -> None:
    """Hand a locally-built image to the vcluster node's containerd.

    The docker driver runs the node as a container with its own image store, and
    nothing can pull this image from a registry, so it has to be shipped in over
    `docker save`. Pods must then use a pull policy that tolerates a missing
    registry (the e2e values set IfNotPresent).
    """
    container = f"vcluster.cp.{cluster_name}"
    save = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    try:
        subprocess.run(
            ["docker", "exec", "-i", container, "ctr", "-n", "k8s.io", "images", "import", "-"],
            stdin=save.stdout,
            check=True,
        )
    finally:
        if save.stdout:
            save.stdout.close()
        save.wait()
    if save.returncode != 0:
        raise AssertionError(f"docker save {image} failed with {save.returncode}")


def split_image_reference(image: str) -> tuple[str, str, str]:
    """Split ``registry/repository:tag`` into its three parts.

    The chart composes the image from a registry, a repository and a tag held in
    separate values, so an arbitrary reference has to be taken apart to override
    them.
    """
    reference, _, tag = image.rpartition(":")
    if not reference or "/" in tag:
        raise AssertionError(f"image reference '{image}' has no tag")
    registry, _, repository = reference.partition("/")
    if not repository:
        raise AssertionError(f"image reference '{image}' has no registry")
    return registry, repository, tag


async def deploy_git_https_server(
    *,
    api,
    namespace: str,
    name: str,
    image: str,
    certificate,
) -> None:
    """Create one HTTPS git server: its TLS Secret, then the templated manifests."""
    from kr8s.asyncio.objects import ConfigMap, Deployment, Secret, Service

    tls_secret = Secret(
        {
            "metadata": {"name": f"{name}-tls", "namespace": namespace},
            "type": "kubernetes.io/tls",
            "stringData": {
                "tls.crt": certificate.certificate_pem,
                "tls.key": certificate.private_key_pem,
            },
        },
        namespace=namespace,
        api=api,
    )
    await tls_secret.create()

    template = Template((FIXTURES_DIR / "git-https-server.yaml").read_text())
    manifests = yaml.safe_load_all(template.substitute(name=name, image=image))
    kinds = {"ConfigMap": ConfigMap, "Deployment": Deployment, "Service": Service}
    deployment = None
    for manifest in manifests:
        if not manifest:
            continue
        manifest.setdefault("metadata", {})["namespace"] = namespace
        obj = kinds[manifest["kind"]](manifest, namespace=namespace, api=api)
        await obj.create()
        if manifest["kind"] == "Deployment":
            deployment = obj

    assert deployment is not None, "git-https-server.yaml declares no Deployment"
    await deployment.wait("condition=Available", timeout=300)


@pytest.fixture(scope="session")
async def infrahub_custom_ca_k8s(
    vcluster: dict, staged_charts, request
) -> AsyncGenerator[dict, None]:
    """Deploy Infrahub with a private CA bundle mounted, next to two git servers.

    Both git servers speak HTTPS with a certificate no public trust store knows;
    only one of the two CAs is in the bundle Infrahub is given. That pairing is
    what makes the test conclusive — the repository that clones is trusted
    through the mounted bundle and nothing else, and the one that fails shows
    verification is still on.
    """
    from kr8s.asyncio.objects import ConfigMap

    kubeconfig = vcluster["kubeconfig_path"]
    namespace = CUSTOM_CA_NAMESPACE
    _register_namespace(request, namespace)

    image = os.environ.get("INFRAHUB_CUSTOM_IMAGE") or build_custom_infrahub_image()
    import_image_into_vcluster(image, vcluster["cluster_name"])
    registry, repository, tag = split_image_reference(image)

    trusted_ca = create_certificate_authority("Infrahub e2e trusted CA")
    untrusted_ca = create_certificate_authority("Infrahub e2e untrusted CA")

    subprocess.run(
        ["kubectl", "create", "namespace", namespace, "--kubeconfig", kubeconfig],
        check=True,
    )
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    for server, authority in ((TRUSTED_GIT_SERVER, trusted_ca), (UNTRUSTED_GIT_SERVER, untrusted_ca)):
        await deploy_git_https_server(
            api=api,
            namespace=namespace,
            name=server,
            image=image,
            certificate=issue_server_certificate(
                authority=authority,
                common_name=server,
                dns_names=service_dns_names(server, namespace),
            ),
        )

    # Only the trusted CA goes into the bundle; the untrusted one exists solely
    # to be rejected.
    ca_bundle = ConfigMap(
        {
            "metadata": {"name": CA_BUNDLE_CONFIGMAP, "namespace": namespace},
            "data": {"ca-bundle.pem": trusted_ca.pem},
        },
        namespace=namespace,
        api=api,
    )
    await ca_bundle.create()

    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[
            FIXTURES_DIR / "infrahub-values.yaml",
            FIXTURES_DIR / "infrahub-custom-ca-values.yaml",
        ],
        sets={
            "global.infrahubRepository": repository,
            "global.infrahubTag": tag,
            "infrahubServer.infrahubServer.imageRegistry": registry,
            "infrahubTaskWorker.infrahubTaskWorker.imageRegistry": registry,
        },
    )

    # A healthy /api/config only means the web app is up. The task worker writes
    # the git TLS configuration and registers its Prefect deployments during its
    # own startup, and both the git-config check and the repository import depend
    # on that having happened — so gate on the branch API, which needs a
    # registered deployment to answer.
    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector="service=infrahub-server", ready_path="/api/config",
    ) as url:
        await wait_for_infrahub_branch_ready(url, INFRAHUB_ADMIN_TOKEN)

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "token": INFRAHUB_ADMIN_TOKEN,
        "server_label": "service=infrahub-server",
        "worker_label": "service=infrahub-task-worker",
        "image": image,
        "ca_bundle_path": CA_BUNDLE_PATH,
        "trusted_repository_url": f"https://{TRUSTED_GIT_SERVER}/demo.git",
        "untrusted_repository_url": f"https://{UNTRUSTED_GIT_SERVER}/demo.git",
    }
