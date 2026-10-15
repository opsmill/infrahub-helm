"""E2E for the OpenShift overlay (``charts/infrahub-enterprise/values.openshift.yaml``).

NOT part of CI. CI's e2e jobs only ever select the per-chart markers
(``-m infrahub`` / ``enterprise`` / ``backup`` / ``observability`` / ``mcp``);
this module carries only the ``manual`` marker, so no automated job collects it
(deploying a second full enterprise stack would double the enterprise job).
Run it on demand against a local Docker + vcluster setup with::

    uv run pytest -v -m manual tests/e2e/test_infrahub_enterprise_openshift.py

The overlay exists because OpenShift's ``restricted-v2`` SCC rejects a pod that
pins runAsUser/runAsGroup/fsGroup outside the namespace's allocated range, and
the charts pin 1000 (Infrahub, Prefect), 7474 (Neo4j) and 1001 (Bitnami). A
vcluster has no SCC, so the two halves are checked separately: the rendered
manifests must carry no pinned id, and the stack must still run once an
arbitrary uid is assigned — which the SCC-simulation fixture stands in for.
Deploying the overlay *without* that simulation would leave every container on
its image's own uid (root for Neo4j and the Bitnami charts), which is not a
configuration OpenShift can produce.
"""

import subprocess

import kr8s.asyncio
import pytest
import yaml
from kr8s.asyncio.objects import Pod

from tests.conftest import CHARTS_DIR
from tests.e2e.conftest import (
    FIXTURES_DIR,
    _register_namespace,
    helm_install,
    portforward_service,
)
from tests.helpers.utils import (
    INFRAHUB_ADMIN_TOKEN,
    check_infrahub_healthy,
    seed_infrahub_data,
    verify_infrahub_data,
)

pytestmark = pytest.mark.manual

# The fields restricted-v2 assigns itself and refuses to see pinned.
PINNED_ID_FIELDS = ("runAsUser", "runAsGroup", "fsGroup")

# Must match openshift-scc-simulation.yaml.
SCC_UID = 1000670000

BASE_VALUES = FIXTURES_DIR / "infrahub-enterprise-values.yaml"
OVERLAY = CHARTS_DIR / "infrahub-enterprise" / "values.openshift.yaml"
SCC_SIMULATION = FIXTURES_DIR / "openshift-scc-simulation.yaml"


def _pod_templates(manifests):
    """Yield (kind, name, podSpec) for every workload in a rendered chart."""
    for manifest in manifests:
        if not manifest:
            continue
        kind = manifest.get("kind")
        spec = manifest.get("spec") or {}
        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            template = spec.get("template")
        elif kind == "CronJob":
            template = (spec.get("jobTemplate") or {}).get("spec", {}).get("template")
        else:
            continue
        if template:
            yield kind, manifest["metadata"]["name"], template["spec"]


def _security_contexts(pod_spec):
    """Yield (where, securityContext) for the pod and each of its containers."""
    yield "pod", pod_spec.get("securityContext") or {}
    for container in pod_spec.get("initContainers", []) + pod_spec["containers"]:
        yield container["name"], container.get("securityContext") or {}


@pytest.fixture(scope="session")
async def infrahub_enterprise_openshift_k8s(vcluster, staged_charts, request):
    """Deploy the enterprise chart with the overlay and an SCC-assigned uid."""
    kubeconfig = vcluster["kubeconfig_path"]
    namespace = "infrahub-openshift"
    _register_namespace(request, namespace)

    helm_install(
        release="infrahub-enterprise",
        chart_path=staged_charts["infrahub-enterprise"],
        namespace=namespace,
        kubeconfig=kubeconfig,
        values_files=[BASE_VALUES, OVERLAY, SCC_SIMULATION],
    )

    yield {
        "namespace": namespace,
        "kubeconfig_path": kubeconfig,
        "token": INFRAHUB_ADMIN_TOKEN,
        "server_label": "service=infrahub-server",
        "worker_label": "service=infrahub-task-worker",
    }


def _exec(infrahub: dict, label: str, *command: str) -> subprocess.CompletedProcess:
    """Run a command in the first pod matching ``label``."""
    base = ["kubectl", "-n", infrahub["namespace"], "--kubeconfig", infrahub["kubeconfig_path"]]
    pods = subprocess.run(
        [*base, "get", "pod", "-l", label, "-o", "name"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert pods, f"no pod matching {label}"
    return subprocess.run(
        [*base, "exec", pods[0], "--", *command], capture_output=True, text=True, timeout=120
    )


def test_overlay_leaves_no_pinned_ids(staged_charts):
    """Rendered with the overlay, nothing pins a uid/gid for the SCC to reject.

    Rendering rather than reading live pods: the deployed stack carries the ids
    the simulation fixture puts back, standing in for the ones OpenShift assigns.
    """
    rendered = subprocess.run(
        [
            "helm", "template", "infrahub-enterprise",
            str(staged_charts["infrahub-enterprise"]),
            "-f", str(BASE_VALUES),
            "-f", str(OVERLAY),
        ],
        capture_output=True, text=True, check=True,
    ).stdout

    offenders = []
    workloads = 0
    for kind, name, pod_spec in _pod_templates(yaml.safe_load_all(rendered)):
        workloads += 1
        for where, context in _security_contexts(pod_spec):
            pinned = {f: context[f] for f in PINNED_ID_FIELDS if f in context}
            if pinned:
                offenders.append(f"{kind}/{name} [{where}]: {pinned}")

    assert workloads, "no workloads rendered"
    assert not offenders, "uid/gid still pinned after the OpenShift overlay:\n" + "\n".join(
        offenders
    )


async def test_every_pod_runs_as_the_assigned_uid(infrahub_enterprise_openshift_k8s):
    """Every pod took the SCC-assigned uid — no chart default survived."""
    kubeconfig = infrahub_enterprise_openshift_k8s["kubeconfig_path"]
    namespace = infrahub_enterprise_openshift_k8s["namespace"]

    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    pods = [pod async for pod in Pod.list(namespace=namespace, api=api)]
    assert pods, f"no pods in namespace {namespace!r}"

    offenders = []
    for pod in pods:
        for where, context in _security_contexts(pod.raw["spec"]):
            uid = context.get("runAsUser")
            if uid is not None and uid != SCC_UID:
                offenders.append(f"{pod.name} [{where}]: runAsUser={uid}")

    assert not offenders, "pods not running as the assigned uid:\n" + "\n".join(offenders)


async def test_infrahub_enterprise_openshift_runs(infrahub_enterprise_openshift_k8s):
    """The stack works end to end under an arbitrary uid."""
    kubeconfig = infrahub_enterprise_openshift_k8s["kubeconfig_path"]
    namespace = infrahub_enterprise_openshift_k8s["namespace"]
    token = infrahub_enterprise_openshift_k8s["token"]

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_enterprise_openshift_k8s["server_label"],
        ready_path="/api/config",
    ) as url:
        health = await check_infrahub_healthy(url, token)
        assert "main" in health["branches"]

        seed = await seed_infrahub_data(url, token)
        await verify_infrahub_data(url, token, seed)


@pytest.mark.parametrize("label", ["server_label", "worker_label"])
async def test_infrahub_pods_can_write_where_they_need_to(infrahub_enterprise_openshift_k8s, label):
    """Every location the Infrahub containers write to is writable by the assigned uid.

    The image owns these as uid 1000, and the uid has no home of its own, so
    without the overlay's volumes none of them is writable. Nothing fails
    loudly: the task worker logs that it cannot write its git configuration and
    Prefect warns that it cannot create its home, then both keep running.
    """
    infrahub = infrahub_enterprise_openshift_k8s
    result = _exec(
        infrahub, infrahub[label], "sh", "-c",
        'for d in "$HOME" /prom_shared /opt/infrahub/git; do test -w "$d" || echo "$d"; done',
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout.split(), f"not writable as the assigned uid: {result.stdout.split()}"


async def test_task_worker_writes_its_git_config(infrahub_enterprise_openshift_k8s):
    """The task worker writes its global git configuration at startup.

    That file carries `http.sslCAInfo` and `http.sslVerify` from `git.tls_ca_file`
    and `git.tls_insecure`, so a worker that cannot write it clones HTTPS remotes
    against the system certificates only. The image already ships
    /opt/infrahub/.gitconfig with the git user in it, so reading a key back
    only counts when the file sits in a directory the worker can write.
    """
    infrahub = infrahub_enterprise_openshift_k8s
    worker = infrahub["worker_label"]
    result = _exec(
        infrahub, worker, "python", "-c",
        "from infrahub import config; config.load_and_exit();"
        " print(config.SETTINGS.git.global_config_file)",
    )
    assert result.returncode == 0, f"could not resolve the git config path: {result.stderr.strip()}"
    path = result.stdout.strip()

    writable = _exec(infrahub, worker, "sh", "-c", 'test -w "$(dirname "$1")"', "sh", path)
    assert writable.returncode == 0, f"the task worker cannot write next to {path}"

    user_name = _exec(infrahub, worker, "git", "config", "--file", path, "--get", "user.name")
    assert user_name.stdout.strip() == "Infrahub", (
        f"the task worker did not write {path}: {user_name.stderr.strip()}"
    )
