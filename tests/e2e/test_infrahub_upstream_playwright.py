"""E2E: the upstream Infrahub pytest-playwright suite, driven against a Helm deployment.

https://github.com/opsmill/infrahub/tree/stable/tests/e2e drives the Infrahub UI
with pytest-playwright. By default it boots its own stack with
infrahub-testcontainers; this module runs the very same specs against Infrahub
Enterprise as this repo's charts deploy it — under the OpenShift overlay, so the
browser flows are exercised on the configuration OpenShift actually produces.

The suite honours ``INFRAHUB_ADDRESS``: with it set, no container is booted and
its data fixtures become no-ops, so the deployment has to arrive already loaded.
The chart's demo-data Job loads the same dataset the fixtures would (base
schema, menu, `models/infrastructure_edge.py`, the demo-edge repository), which
is what ``upstream-e2e-values.yaml`` turns on.

NOT part of CI. CI's e2e jobs only select the per-chart markers; this module
carries only the ``manual`` marker. It clones a large repository, installs a
Python environment and a browser, and drives 200+ UI specs. Run it on demand::

    uv run pytest -v -s -m manual tests/e2e/test_infrahub_upstream_playwright.py

``-s`` is worth having: the upstream run is a subprocess whose output is
forwarded with ``print``, so without it the ~20 minutes of specs stay captured
until the test ends.

Knobs:

* ``INFRAHUB_E2E_REF`` — upstream ref to test. Defaults to
  ``infrahub-v<appVersion>``, the release the chart actually deploys: the suite
  tracks the UI commit by commit, so running a ref ahead of the image tests
  specs against a frontend that image does not have. Set it to ``stable``
  deliberately to test ahead of the release.
* ``INFRAHUB_E2E_SRC`` — path to an existing, already-prepared infrahub checkout
  (skips clone + ``uv sync``). Its ref is used as-is.
* ``INFRAHUB_E2E_TESTS`` — subset to run, relative to the checkout
  (default ``tests/e2e``), e.g. ``tests/e2e/branches``.
* ``INFRAHUB_E2E_SUPPORTING_SERVICES`` — ``bundled`` (default) deploys the
  chart's own Redis, RabbitMQ and task manager PostgreSQL, all Bitnami charts.
  ``redhat`` turns those off and runs the suite against the services
  ``redhat-supporting-services.yaml`` deploys next to the release: Redis and
  PostgreSQL from registry.redhat.io, RabbitMQ from the official image. It
  needs a ``docker login registry.redhat.io`` on the machine running the test
  (a registry service account works), copied into the namespace as a pull
  secret.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import kr8s.asyncio
import pytest
import yaml

from tests.conftest import CHARTS_DIR, REPO_ROOT
from tests.e2e.conftest import (
    FIXTURES_DIR,
    _register_namespace,
    helm_install,
    loadbalancer_url,
    wait_for_workloads,
)
from tests.helpers.utils import INFRAHUB_ADMIN_TOKEN, wait_for_http, wait_for_job

pytestmark = pytest.mark.manual


def _deployed_app_version() -> str:
    """The Infrahub version the enterprise chart deploys."""
    chart = yaml.safe_load((CHARTS_DIR / "infrahub-enterprise" / "Chart.yaml").read_text())
    return str(chart["appVersion"])


UPSTREAM_URL = "https://github.com/opsmill/infrahub.git"
UPSTREAM_REF = os.environ.get("INFRAHUB_E2E_REF") or f"infrahub-v{_deployed_app_version()}"
# Where the suite lives inside the checkout. Its pytest.ini sits here, which
# makes it the rootdir: positional args are resolved from the invocation
# directory (the checkout root) while --deselect and JUnit nodeids are
# relative to the rootdir, so the two need different prefixes.
SUITE_ROOT = "tests/e2e"
UPSTREAM_TESTS = os.environ.get("INFRAHUB_E2E_TESTS", SUITE_ROOT)

# Specs that cannot pass against a Helm deployment for reasons that are not
# defects in the chart. Each entry states why; nothing else is excluded, so a
# new failure turns this test red.
#
# Paths are relative to the upstream suite's ROOTDIR, which `-c
# tests/e2e/pytest.ini` puts at tests/e2e — a repo-root-relative path here
# matches nothing and pytest deselects silently.
KNOWN_DIVERGENCES = (
    # Registers a Read-Only repository through the UI at
    # https://github.com/opsmill/infrahub-demo-edge.git. Upstream that URL is
    # free, because the demo_edge_repo fixture registers demo-edge from a local
    # path (/remote/demo-edge) served by the compose stack. The chart's
    # demo-data Job has no local remote to serve, so it registers demo-edge from
    # the public URL — and Infrahub enforces a uniqueness constraint on a
    # repository's location, so the spec's own registration is rejected
    # ("Violates uniqueness constraint 'location'"). Making it pass needs the
    # demo-edge content served from inside the cluster, which the chart cannot
    # express today (no initContainers on the task worker). Every other
    # repository-derived spec — artifacts, proposed changes, CoreGraphQLQuery,
    # breadcrumb — passes against the Job's registration.
    "repository/test_repository_objects.py",
    # test_should_open_the_creation_form_and_open_the_tag_option_creation_form
    # ends on `get_by_role("button", name="Cancel")`, which is ambiguous while
    # the inline creation form is still dismissing: strict mode sees the inline
    # form's Cancel and the device form's. Against this deployment the dismissal
    # loses that race every time — on 1.11.0 and on stable, in a full run and on
    # its own, so the retry below does not rescue it — though every functional
    # assertion in the spec (the form opens, the tag is created, "Tag created"
    # is shown) passes first. The sibling spec in the module runs.
    "objects/test_object_dropdown_creation.py::TestObjectDropdownCreation"
    "::test_should_open_the_creation_form_and_open_the_tag_option_creation_form",
)
# .cache/ is gitignored; keeping the checkout across runs turns a multi-minute
# clone + dependency sync into a fetch.
UPSTREAM_CHECKOUT = REPO_ROOT / ".cache" / "upstream-infrahub"

RELEASE = "infrahub-enterprise"
NAMESPACE = "infrahub-upstream-e2e"
# The dataset load (models/infrastructure_edge.py) is the long pole.
DEMO_DATA_TIMEOUT = 30 * 60
# Above this many failures, retrying is not triage — something is broken.
RETRY_LIMIT = 10

SUPPORTING_SERVICES = os.environ.get("INFRAHUB_E2E_SUPPORTING_SERVICES", "bundled")

REDHAT_REGISTRY = "registry.redhat.io"
REDHAT_PULL_SECRET = "redhat-registry"

VALUES_FILES = [
    FIXTURES_DIR / "infrahub-enterprise-values.yaml",
    CHARTS_DIR / "infrahub-enterprise" / "values.openshift.yaml",
    FIXTURES_DIR / "openshift-scc-simulation.yaml",
    FIXTURES_DIR / "upstream-e2e-values.yaml",
]
if SUPPORTING_SERVICES == "redhat":
    VALUES_FILES.append(FIXTURES_DIR / "redhat-supporting-services-values.yaml")


def _run(*args: str, cwd: Path, timeout: int = 1800) -> None:
    """Run a preparation command, surfacing its output on failure."""
    result = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _prepare_upstream_checkout() -> Path:
    """Return a checkout of the upstream suite with its environment installed.

    `python_sdk` is a submodule and the editable install puts it on sys.path, so
    it has to be present *before* `uv sync` — otherwise the suite imports fail
    with `No module named 'infrahub_sdk'`.
    """
    if src := os.environ.get("INFRAHUB_E2E_SRC"):
        return Path(src).resolve()

    checkout = UPSTREAM_CHECKOUT
    if not (checkout / ".git").exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "git", "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(checkout),
            cwd=checkout.parent,
        )
    _run("git", "fetch", "--filter=blob:none", "origin", UPSTREAM_REF, cwd=checkout)
    _run("git", "checkout", "--detach", "FETCH_HEAD", cwd=checkout)
    _run("git", "submodule", "update", "--init", "--filter=blob:none", "python_sdk", cwd=checkout)

    # --reinstall-package regenerates the editable .pth: a sync that ran while
    # the submodule was empty leaves python_sdk off sys.path.
    _run("uv", "sync", "--group", "dev", "--reinstall-package", "infrahub-server", cwd=checkout)
    _run("uv", "run", "playwright", "install", "chromium", cwd=checkout)
    return checkout


def _assert_divergences_were_deselected(report: Path) -> None:
    """Fail loudly when a KNOWN_DIVERGENCES entry stopped matching.

    pytest ignores a `--deselect` path it cannot resolve without a word of
    warning, so a stale or wrongly-rooted entry silently puts the spec back in
    the run.
    """
    ran = set()
    for case in ET.parse(report).getroot().iter("testcase"):
        ran.add(f"{case.get('classname')}::{case.get('name')}")

    for entry in KNOWN_DIVERGENCES:
        module, _, nodeid = entry.partition(".py")
        prefix = module.replace("/", ".")
        selector = nodeid.removeprefix("::").replace("::", ".")
        wanted = f"{prefix}.{selector}" if selector else prefix
        matches = [case for case in ran if case.replace("::", ".").startswith(wanted)]
        assert not matches, (
            f"KNOWN_DIVERGENCES entry {entry!r} deselected nothing (paths are relative to the "
            f"upstream rootdir, tests/e2e); it ran as: {matches}"
        )


def _nodeid(classname: str, name: str) -> str:
    """Rebuild a pytest nodeid from a JUnit classname/name pair.

    JUnit dots the module path and the class together
    (`branches.test_branch_selector.TestBranchSelectorLoggedInAsAdmin`); pytest
    wants `branches/test_branch_selector.py::TestBranchSelectorLoggedInAsAdmin`.
    """
    parts = classname.split(".")
    klass = parts.pop() if parts and parts[-1][:1].isupper() else None
    module = "/".join(parts) + ".py"
    return f"{module}::{klass}::{name}" if klass else f"{module}::{name}"


def _summarize_junit(report: Path) -> tuple[int, int, int, list[str]]:
    """Return (tests, failures, errors, failed nodeids) from a JUnit report."""
    root = ET.parse(report).getroot()
    suites = root.findall("testsuite") or [root]
    tests = failures = errors = 0
    failed: list[str] = []
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(_nodeid(case.get("classname", ""), case.get("name", "")))
    return tests, failures, errors, failed


def _redhat_pull_secret() -> dict:
    """A pull secret carrying the local registry.redhat.io login, and only that.

    The rest of the Docker config may hold credentials for other registries,
    which have no business in the cluster.
    """
    config_path = Path(os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker") / "config.json"
    auths = json.loads(config_path.read_text()).get("auths", {}) if config_path.exists() else {}
    auth = (auths.get(REDHAT_REGISTRY) or {}).get("auth")
    if not auth:
        pytest.fail(
            f"no {REDHAT_REGISTRY} login in {config_path} (a credential store keeps it elsewhere): "
            f"run `docker login {REDHAT_REGISTRY}` with a registry service account"
        )
    config = json.dumps({"auths": {REDHAT_REGISTRY: {"auth": auth}}})
    return {
        "metadata": {"name": REDHAT_PULL_SECRET, "namespace": NAMESPACE},
        "type": "kubernetes.io/dockerconfigjson",
        "data": {".dockerconfigjson": base64.b64encode(config.encode()).decode()},
    }


async def _deploy_redhat_supporting_services(kubeconfig: str) -> None:
    """Deploy the Red Hat-image cache, message queue and task manager database.

    The manifests carry no uid, as OpenShift wants them; each pod gets the ids
    openshift-scc-simulation.yaml gives the chart's pods, standing in for the
    SCC the same way.
    """
    from kr8s.asyncio.objects import Secret, Service, StatefulSet

    simulation = yaml.safe_load((FIXTURES_DIR / "openshift-scc-simulation.yaml").read_text())
    scc_context = simulation["infrahub"]["infrahubServer"]["podSecurityContext"]

    subprocess.run(
        ["kubectl", "create", "namespace", NAMESPACE, "--kubeconfig", kubeconfig], check=True
    )
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    await Secret(_redhat_pull_secret(), namespace=NAMESPACE, api=api).create()

    kinds = {"Secret": Secret, "Service": Service, "StatefulSet": StatefulSet}
    manifests = yaml.safe_load_all((FIXTURES_DIR / "redhat-supporting-services.yaml").read_text())
    for manifest in manifests:
        if not manifest:
            continue
        manifest["metadata"]["namespace"] = NAMESPACE
        if manifest["kind"] == "StatefulSet":
            pod = manifest["spec"]["template"]["spec"]
            pod["securityContext"] = dict(scc_context)
            pod["imagePullSecrets"] = [{"name": REDHAT_PULL_SECRET}]
        await kinds[manifest["kind"]](manifest, namespace=NAMESPACE, api=api).create()

    # Ready before the chart goes in, so a service that fails to start is not
    # mistaken for an Infrahub that cannot reach it.
    wait_for_workloads(namespace=NAMESPACE, kubeconfig=kubeconfig, timeout="10m")


@pytest.fixture(scope="session")
def upstream_checkout() -> Path:
    """The upstream infrahub checkout, cloned/updated and installed once."""
    return _prepare_upstream_checkout()


@pytest.fixture(scope="session")
async def infrahub_upstream_e2e_k8s(vcluster, staged_charts, request):
    """Deploy the enterprise chart the way the OpenShift overlay does, with data."""
    kubeconfig = vcluster["kubeconfig_path"]
    _register_namespace(request, NAMESPACE)

    if SUPPORTING_SERVICES == "redhat":
        await _deploy_redhat_supporting_services(kubeconfig)
    elif SUPPORTING_SERVICES != "bundled":
        pytest.fail(
            f"INFRAHUB_E2E_SUPPORTING_SERVICES must be bundled or redhat, not {SUPPORTING_SERVICES!r}"
        )

    helm_install(
        release=RELEASE,
        chart_path=staged_charts["infrahub-enterprise"],
        namespace=NAMESPACE,
        kubeconfig=kubeconfig,
        values_files=VALUES_FILES,
    )
    await wait_for_job(
        kubeconfig, NAMESPACE, f"{RELEASE}-infrahub-demo-data-job", timeout=DEMO_DATA_TIMEOUT
    )

    url = await loadbalancer_url(kubeconfig, NAMESPACE, f"{RELEASE}-infrahub-server", port=8000)
    await wait_for_http(f"{url}/api/config", timeout=300)

    yield {
        "namespace": NAMESPACE,
        "kubeconfig_path": kubeconfig,
        "address": url,
        "token": INFRAHUB_ADMIN_TOKEN,
    }


async def _run_upstream(checkout: Path, address: str, args: list[str], report: str) -> int:
    """Run the upstream suite, streaming its output, and return the exit code."""
    process = await asyncio.create_subprocess_exec(
        "uv", "run", "pytest",
        "-c", f"{SUITE_ROOT}/pytest.ini",
        *args,
        # The suite's own config stops at 5 failures; we want the whole picture.
        "--maxfail=0",
        # Its pytest.ini hardcodes playwright-junit.xml; a later flag wins, which
        # keeps the retry from overwriting the main report.
        "--junitxml", report,
        cwd=str(checkout),
        env={**os.environ, "INFRAHUB_ADDRESS": address, "PYTHONUNBUFFERED": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    async for line in process.stdout:
        print(line.decode(errors="replace").rstrip(), flush=True)
    return await process.wait()


async def test_upstream_playwright_suite(infrahub_upstream_e2e_k8s, upstream_checkout):
    """Every upstream UI spec passes against the Helm-deployed Infrahub."""
    checkout = upstream_checkout
    address = infrahub_upstream_e2e_k8s["address"]

    deselect: list[str] = []
    for spec in KNOWN_DIVERGENCES:
        deselect += ["--deselect", spec]

    returncode = await _run_upstream(
        checkout, address, [UPSTREAM_TESTS, *deselect], "playwright-junit.xml"
    )

    report = checkout / "playwright-junit.xml"
    if not report.exists():
        raise AssertionError(f"upstream suite produced no JUnit report (exit {returncode})")

    _assert_divergences_were_deselected(report)
    tests, _, _, failed = _summarize_junit(report)

    # Retry the failures once, on their own. These are browser specs driven
    # against a cluster, and a handful are order- and timing-sensitive: the
    # branch selector's quick-create form, for one, fails in a full run and
    # passes on its own. A spec that fails twice is a real failure; one that
    # passes on the retry is reported as flaky rather than silently dropped.
    flaky: list[str] = []
    if failed and len(failed) <= RETRY_LIMIT:
        print(f"\nretrying {len(failed)} failed spec(s) individually", flush=True)
        retry_args = [f"{SUITE_ROOT}/{spec}" for spec in failed]
        retry_code = await _run_upstream(checkout, address, retry_args, "retry-junit.xml")
        _, _, _, still_failing = _summarize_junit(checkout / "retry-junit.xml")
        flaky = [spec for spec in failed if spec not in still_failing]
        failed, returncode = still_failing, retry_code

    print(
        f"\nupstream suite ({UPSTREAM_REF}, {SUPPORTING_SERVICES} supporting services): {tests} tests, "
        f"{len(failed)} failed, {len(flaky)} flaky (passed on retry)",
        flush=True,
    )
    if flaky:
        print("flaky:\n  " + "\n  ".join(flaky), flush=True)

    assert not failed, (
        f"{len(failed)} upstream spec(s) failed twice against the Helm deployment "
        f"(ref {UPSTREAM_REF}, exit {returncode}):\n" + "\n".join(failed)
    )
    assert returncode == 0, f"upstream suite exited {returncode} with no failed testcase recorded"
