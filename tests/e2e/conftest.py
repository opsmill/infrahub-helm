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

import httpx
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
# Fixture: s3_k8s (in-cluster S3 backend for the backup test, served by Garage
# behind an HTTPS front whose certificate a private CA issued)
# ---------------------------------------------------------------------------
GARAGE_ADMIN_TOKEN = "infrahub-helm-e2e-admin-token"
GARAGE_RPC_SECRET = "a0b1c2d3e4f5061728394a5b6c7d8e9fa0b1c2d3e4f5061728394a5b6c7d8e9f"
GARAGE_S3_PORT = 3900
GARAGE_ADMIN_PORT = 3903
# Garage only imports keys shaped like the ones it generates: "GK" and 24 hex
# characters, with a 64-character hex secret. Fixed test values, not secrets.
S3_ACCESS_KEY = "GKdeadbeefdeadbeefdeadbeef"
S3_SECRET_KEY = "deadbeef" * 8
# garage-tls.yaml names its Service and TLS Secret after S3_TLS_SERVICE, which is
# also the hostname in the S3 endpoint and in the certificate, and
# infrahub-backup-s3-ca-values.yaml mounts S3_CA_CONFIGMAP, so the files have to
# change together with these names.
S3_TLS_SERVICE = "garage-tls"
S3_CA_CONFIGMAP = "s3-ca"


async def _create_from_manifests(api, namespace: str, text: str):
    """Create every ConfigMap, Deployment and Service in a manifest file, and
    return the Deployment."""
    from kr8s.asyncio.objects import ConfigMap, Deployment, Service

    kinds = {"ConfigMap": ConfigMap, "Deployment": Deployment, "Service": Service}
    deployment = None
    for manifest in yaml.safe_load_all(text):
        if not manifest:
            continue
        manifest.setdefault("metadata", {})["namespace"] = namespace
        obj = kinds[manifest["kind"]](manifest, namespace=namespace, api=api)
        await obj.create()
        if manifest["kind"] == "Deployment":
            deployment = obj
    if deployment is None:
        raise AssertionError("the manifests declare no Deployment")
    return deployment


async def _bootstrap_garage(admin_url: str, bucket: str) -> None:
    """Make a fresh Garage node serve the backup bucket.

    A new node stores nothing until a storage layout is applied, and the access
    key and the bucket have to be created through the admin API.
    """
    async with httpx.AsyncClient(
        base_url=f"{admin_url}/v2",
        headers={"Authorization": f"Bearer {GARAGE_ADMIN_TOKEN}"},
        timeout=10.0,
    ) as client:

        async def call(method: str, endpoint: str, payload: dict | None = None) -> dict:
            resp = await client.request(method, endpoint, json=payload)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

        status = await call("GET", "/GetClusterStatus")
        node_id = status["nodes"][0]["id"]
        await call(
            "POST",
            "/UpdateClusterLayout",
            {"roles": [{"id": node_id, "zone": "e2e", "capacity": 10**9, "tags": []}]},
        )
        await call("POST", "/ApplyClusterLayout", {"version": status["layoutVersion"] + 1})

        await call(
            "POST",
            "/ImportKey",
            {"accessKeyId": S3_ACCESS_KEY, "secretAccessKey": S3_SECRET_KEY, "name": "e2e"},
        )
        created = await call("POST", "/CreateBucket", {"globalAlias": bucket})
        await call(
            "POST",
            "/AllowBucketKey",
            {
                "bucketId": created["id"],
                "accessKeyId": S3_ACCESS_KEY,
                "permissions": {"read": True, "write": True, "owner": True},
            },
        )

    # The admin API reports healthy only once the layout is applied.
    await wait_for_http(f"{admin_url}/health", timeout=60.0, interval=1.0)


async def deploy_garage(kubeconfig: str, namespace: str) -> dict:
    """Deploy a single-node Garage that serves the backup bucket into the namespace,
    and an HTTPS front for it whose certificate a private CA issued.

    Garage creates the bucket and the access key through its admin API. The
    credentials Secret consumed by the backup/restore Jobs, the TLS Secret of the
    HTTPS front and the ConfigMap that holds the CA are created here via kr8s.
    The Jobs reach the bucket through the HTTPS front only; the test itself lists
    the bucket over a port-forward to Garage's plain HTTP port.
    """
    from kr8s.asyncio.objects import ConfigMap, Secret

    bucket = "infrahub-backups"

    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    # Garage ConfigMap + Deployment + Service from the manifest fixture.
    template = Template((FIXTURES_DIR / "garage.yaml").read_text())
    deployment = await _create_from_manifests(
        api,
        namespace,
        template.substitute(rpc_secret=GARAGE_RPC_SECRET, admin_token=GARAGE_ADMIN_TOKEN),
    )

    # A CA generated per session is in no trust store, so only the ConfigMap the
    # Jobs mount can make them trust it.
    authority = create_certificate_authority("Infrahub e2e S3 CA")
    certificate = issue_server_certificate(
        authority=authority,
        common_name=S3_TLS_SERVICE,
        dns_names=service_dns_names(S3_TLS_SERVICE, namespace),
    )
    tls_secret = Secret(
        {
            "metadata": {"name": S3_TLS_SERVICE, "namespace": namespace},
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
    ca_configmap = ConfigMap(
        {
            "metadata": {"name": S3_CA_CONFIGMAP, "namespace": namespace},
            "data": {"ca.crt": authority.pem},
        },
        namespace=namespace,
        api=api,
    )
    await ca_configmap.create()

    # HAProxy resolves the Garage Service when it starts, so the front comes after it.
    tls_deployment = await _create_from_manifests(
        api, namespace, (FIXTURES_DIR / "garage-tls.yaml").read_text()
    )

    # Credentials Secret consumed by the backup/restore Jobs.
    secret = Secret(
        {
            "metadata": {"name": "garage-credentials", "namespace": namespace},
            "stringData": {
                "AWS_ACCESS_KEY_ID": S3_ACCESS_KEY,
                "AWS_SECRET_ACCESS_KEY": S3_SECRET_KEY,
            },
        },
        namespace=namespace,
        api=api,
    )
    await secret.create()

    await deployment.wait("condition=Available", timeout=300)
    await tls_deployment.wait("condition=Available", timeout=300)

    async with portforward_service(
        kubeconfig, namespace, GARAGE_ADMIN_PORT, name="garage"
    ) as admin_url:
        await _bootstrap_garage(admin_url, bucket)

    return {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "bucket": bucket,
        "endpoint": f"https://{S3_TLS_SERVICE}",
        # infrahub-backup values that make the Jobs trust the CA.
        "ca_values": FIXTURES_DIR / "infrahub-backup-s3-ca-values.yaml",
        "port": GARAGE_S3_PORT,
        "access_key": S3_ACCESS_KEY,
        "secret_key": S3_SECRET_KEY,
        "secret_name": "garage-credentials",
        "service_name": "garage",
    }


@pytest.fixture(scope="session")
async def s3_k8s(infrahub_k8s: dict) -> AsyncGenerator[dict, None]:
    """Garage in the namespace of the community Infrahub deployment; see `deploy_garage`."""
    yield await deploy_garage(infrahub_k8s["kubeconfig_path"], infrahub_k8s["namespace"])


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

    values_files = [
        FIXTURES_DIR / "infrahub-values.yaml",
        FIXTURES_DIR / "infrahub-custom-ca-values.yaml",
    ]
    sets = {
        "global.infrahubRepository": repository,
        "global.infrahubTag": tag,
        "infrahubServer.infrahubServer.imageRegistry": registry,
        "infrahubTaskWorker.infrahubTaskWorker.imageRegistry": registry,
    }
    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=values_files,
        sets=sets,
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
        # How the release was installed, so a test can upgrade it in place.
        "release": "infrahub",
        "chart_path": staged_charts["infrahub"],
        "values_files": values_files,
        "sets": sets,
    }


# ---------------------------------------------------------------------------
# Fixture: infrahub_external_neo4j_k8s (Infrahub whose Neo4j runs in another
# namespace, with the infrahub-backup image that can back it up)
# ---------------------------------------------------------------------------
# Backup and restore of a database outside the Infrahub namespace is not in a
# released infrahub-backup image yet, so the test runs against an image built
# from the pull request that adds it. INFRAHUB_BACKUP_IMAGE names an image that
# already exists locally; INFRAHUB_BACKUP_SOURCE_DIR builds from a local
# infrahub-backup checkout, as it is, instead of cloning the pull request.
INFRAHUB_BACKUP_EXTERNAL_DB_PR = "172"

EXTERNAL_DB_NAMESPACE = "infrahub-external-db"
EXTERNAL_NEO4J_NAMESPACE = "neo4j-external"
# The Neo4j version is the one the infrahub-backup image takes `neo4j-admin`
# from (`FROM neo4j:...` in its Dockerfile). infrahub-backup refuses a server
# newer than its tools, so a newer server would test that refusal instead.
EXTERNAL_NEO4J_CHART_VERSION = "2025.10.1"
# `neo4j.name`: the headless Service is named after it.
EXTERNAL_NEO4J_NAME = "infrahub-ext"
EXTERNAL_NEO4J_USERNAME = "neo4j"
EXTERNAL_NEO4J_PASSWORD = "admin12345"
EXTERNAL_NEO4J_AUTH_SECRET = "neo4j-auth"


def build_infrahub_backup_image(workdir: Path) -> str:
    """Build the infrahub-backup image of the pull request under test and return its tag.

    The tag is local and is not `latest`, so a pod with `imagePullPolicy:
    IfNotPresent` starts from the imported image instead of pulling.
    """
    source = os.environ.get("INFRAHUB_BACKUP_SOURCE_DIR")
    if not source:
        ref = subprocess.run(
            [
                "gh", "pr", "view", INFRAHUB_BACKUP_EXTERNAL_DB_PR,
                "--repo", "opsmill/infrahub-backup",
                "--json", "headRefName", "-q", ".headRefName",
            ],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source = str(workdir / "infrahub-backup")
        subprocess.run(
            [
                "git", "clone", "--quiet", "--depth", "1", "--single-branch", "--branch", ref,
                "https://github.com/opsmill/infrahub-backup.git", source,
            ],
            check=True,
        )
    image = f"infrahub-backup:e2e-pr-{INFRAHUB_BACKUP_EXTERNAL_DB_PR}"
    subprocess.run(["docker", "build", "-t", image, source], check=True)
    return image


def install_external_neo4j(kubeconfig: str, namespace: str, s3_env: dict[str, str], workdir: Path) -> str:
    """Install a standalone Neo4j Enterprise server and return the address Infrahub uses.

    The server binds its backup service to every interface, so that
    infrahub-backup can run `neo4j-admin database backup --from=<host>:6362`
    from the Infrahub namespace. It gets the S3 settings in `s3_env`, because
    a restore makes the server download the backup from the object store
    itself. Infrahub connects through the headless Service, which resolves to
    the pod, so the backup port is reachable at the same host name.
    """
    base = ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace]
    subprocess.run(["kubectl", "--kubeconfig", kubeconfig, "create", "namespace", namespace], check=True)
    subprocess.run(
        [
            *base, "create", "secret", "generic", EXTERNAL_NEO4J_AUTH_SECRET,
            f"--from-literal=NEO4J_AUTH={EXTERNAL_NEO4J_USERNAME}/{EXTERNAL_NEO4J_PASSWORD}",
        ],
        check=True,
    )
    values = {
        "neo4j": {
            "name": EXTERNAL_NEO4J_NAME,
            "edition": "enterprise",
            "acceptLicenseAgreement": "yes",
            "passwordFromSecret": EXTERNAL_NEO4J_AUTH_SECRET,
            "resources": {"cpu": "500m", "memory": "2Gi"},
        },
        "config": {
            "server.memory.heap.initial_size": "512m",
            "server.memory.heap.max_size": "512m",
            "server.memory.pagecache.size": "256m",
            "server.backup.enabled": "true",
            "server.backup.listen_address": "0.0.0.0:6362",
            "dbms.security.auth_minimum_password_length": "4",
        },
        "env": s3_env,
        "logInitialPassword": False,
        "volumes": {"data": {"mode": "volume", "volume": {"emptyDir": {}}}},
        "services": {"neo4j": {"enabled": False}},
    }
    values_path = workdir / "neo4j-external.yaml"
    values_path.write_text(yaml.dump(values))
    repo = ["--repo", "https://helm.neo4j.com/neo4j", "--version", EXTERNAL_NEO4J_CHART_VERSION]
    subprocess.run(
        [
            "helm", "upgrade", "--install", "neo4j", "neo4j", *repo,
            "-n", namespace, "-f", str(values_path), "--kubeconfig", kubeconfig,
        ],
        check=True,
    )
    subprocess.run(
        [
            "helm", "upgrade", "--install", "neo4j-headless", "neo4j-headless-service", *repo,
            "-n", namespace, "--set", f"neo4j.name={EXTERNAL_NEO4J_NAME}", "--kubeconfig", kubeconfig,
        ],
        check=True,
    )
    subprocess.run([*base, "rollout", "status", "statefulset/neo4j", "--timeout=10m"], check=True)
    return f"{EXTERNAL_NEO4J_NAME}-headless.{namespace}.svc.cluster.local"


@pytest.fixture(scope="session")
async def infrahub_external_neo4j_k8s(
    vcluster: dict, staged_charts, request, tmp_path_factory
) -> AsyncGenerator[dict, None]:
    """Deploy Infrahub without its own Neo4j, pointed at a Neo4j server in another
    namespace, next to a Garage that serves the backup bucket.

    The task-manager PostgreSQL database stays in the Infrahub namespace, so a
    backup covers one external and one internal database.
    """
    from kr8s.asyncio.objects import Service

    kubeconfig = vcluster["kubeconfig_path"]
    namespace = EXTERNAL_DB_NAMESPACE
    _register_namespace(request, namespace)
    _register_namespace(request, EXTERNAL_NEO4J_NAMESPACE)
    workdir = tmp_path_factory.mktemp("external-db")

    image = os.environ.get("INFRAHUB_BACKUP_IMAGE") or build_infrahub_backup_image(workdir)
    import_image_into_vcluster(image, vcluster["cluster_name"])
    repository, _, tag = image.rpartition(":")

    subprocess.run(["kubectl", "--kubeconfig", kubeconfig, "create", "namespace", namespace], check=True)
    s3 = await deploy_garage(kubeconfig, namespace)

    # The Neo4j server reaches Garage through the Service IP: with an IP
    # address, the AWS SDK puts the bucket in the path instead of the host
    # name, and this Garage serves path-style requests only.
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    garage = await Service.get(s3["service_name"], namespace=namespace, api=api)
    neo4j_host = install_external_neo4j(
        kubeconfig,
        EXTERNAL_NEO4J_NAMESPACE,
        {
            "AWS_ACCESS_KEY_ID": s3["access_key"],
            "AWS_SECRET_ACCESS_KEY": s3["secret_key"],
            "AWS_REGION": "us-east-1",
            "AWS_ENDPOINT_URL_S3": f"http://{garage.spec.clusterIP}:{s3['port']}",
        },
        workdir,
    )

    db_env = {
        "INFRAHUB_DB_ADDRESS": neo4j_host,
        "INFRAHUB_DB_PORT": "7687",
        "INFRAHUB_DB_USERNAME": EXTERNAL_NEO4J_USERNAME,
        "INFRAHUB_DB_PASSWORD": EXTERNAL_NEO4J_PASSWORD,
    }
    sets = {"neo4j.enabled": "false"}
    for component in ("infrahubServer", "infrahubTaskWorker"):
        for key, value in db_env.items():
            sets[f"{component}.{component}.env.{key}"] = value
    helm_install(
        release="infrahub",
        chart_path=staged_charts["infrahub"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[FIXTURES_DIR / "infrahub-values.yaml"],
        sets=sets,
    )

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
        "s3": s3,
        "backup_image_repository": repository,
        "backup_image_tag": tag,
    }
