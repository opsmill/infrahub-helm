"""Special e2e test: importing a git repository served behind a private CA.

NOT part of CI. It needs an Infrahub image built from opsmill/infrahub#10487
("global TLS CA bundle for outbound components"), which no released chart
appVersion points at, so the module carries only the ``manual`` marker and no
automated job collects it. CI's e2e jobs only ever select the per-chart markers.

Run it on demand against a local Docker + vcluster setup with::

    uv run pytest -v -m manual tests/e2e/test_git_custom_ca.py

The session fixture builds the image (``scripts/build-infrahub-image.sh``, which
overlays the pull request's backend on the released image), imports it into the
vcluster, and deploys Infrahub with a private CA bundle mounted through
``extraVolumes``/``extraVolumeMounts`` and ``INFRAHUB_TLS_CA_BUNDLE`` — the Helm
recipe from the "Trust a private CA" guide. Set ``INFRAHUB_SOURCE_DIR`` to a
local infrahub checkout to skip the clone, or ``INFRAHUB_CUSTOM_IMAGE`` to a
reference to skip the build entirely.

What it proves, in three parts:

- the task worker's global git config carries the bundle, so every HTTPS remote
  is verified against it (this is the part the pull request adds; before it, git
  saw only the system trust store);
- a repository on a server whose certificate that CA signed is added and imported;
- a repository on a server signed by a *different* private CA is rejected. That
  control is what makes the first result mean something: verification is still
  on, and the bundle — not a disabled check and not the system store — is what
  let the first repository through.
"""

import asyncio
import subprocess
import time
import uuid

import pytest
from infrahub_sdk.exceptions import GraphQLError

from tests.e2e.conftest import portforward_service
from tests.helpers.utils import add_read_only_repository, wait_for_repository_imported

pytestmark = pytest.mark.manual


def _task_worker_exec(infrahub: dict, *command: str) -> subprocess.CompletedProcess:
    """Run a command in the task worker container, whichever pod is serving."""
    base = ["kubectl", "-n", infrahub["namespace"], "--kubeconfig", infrahub["kubeconfig_path"]]
    pods = subprocess.run(
        [*base, "get", "pod", "-l", infrahub["worker_label"], "-o", "name"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert pods, f"no task-worker pod matching {infrahub['worker_label']}"
    return subprocess.run(
        [*base, "exec", pods[0], "--", *command], capture_output=True, text=True, timeout=120
    )


def _worker_gitconfig_path(infrahub: dict) -> str:
    """Ask Infrahub which file it treats as git's global configuration.

    The worker exports `GIT_CONFIG_GLOBAL` (from `git.global_config_file`,
    `/opt/infrahub/.gitconfig` by default) before writing any git setting, so its
    "global" configuration is *not* the `~/.gitconfig` an interactive `kubectl
    exec` reads — that one still holds only what the image baked in at build
    time. Reading the wrong file makes every setting the worker wrote look absent.
    """
    result = _task_worker_exec(
        infrahub,
        "python",
        "-c",
        "from infrahub import config; config.load_and_exit();"
        " print(config.SETTINGS.git.global_config_file)",
    )
    assert result.returncode == 0, f"could not resolve the git config path: {result.stderr.strip()}"
    return result.stdout.strip()


def _git_config(infrahub: dict, path: str, key: str) -> str:
    """Read one key from the worker's git configuration, "" when it is unset."""
    return _task_worker_exec(infrahub, "git", "config", "--file", path, "--get", key).stdout.strip()


async def _wait_for_git_config(
    infrahub: dict,
    path: str,
    key: str,
    expected: str,
    timeout: float = 180.0,
    interval: float = 5.0,
) -> None:
    """Poll a git config key until it holds ``expected``.

    The worker writes these during its own startup and rewrites them after every
    container restart, which the stack does a couple of times while its backends
    come up — so this is a poll, not a single read.
    """
    start = time.time()
    while time.time() - start < timeout:
        if _git_config(infrahub, path, key) == expected:
            return
        await asyncio.sleep(interval)
    listing = _task_worker_exec(infrahub, "git", "config", "--file", path, "--list")
    raise AssertionError(
        f"git {key} never became '{expected}' within {timeout}s.\n"
        f"{path} in the task worker:\n{listing.stdout.strip() or listing.stderr.strip()}"
    )


async def test_task_worker_git_trusts_the_ca_bundle(infrahub_custom_ca_k8s):
    """The task worker writes the bundle into the global git config at startup.

    This is the verification step of the "Trust a private CA" guide: git reads
    `http.sslCAInfo` on every HTTPS clone, so the value being there is what makes
    the remaining tests possible.
    """
    path = _worker_gitconfig_path(infrahub_custom_ca_k8s)
    await _wait_for_git_config(
        infrahub_custom_ca_k8s, path, "http.sslCAInfo", infrahub_custom_ca_k8s["ca_bundle_path"]
    )

    # Verification must stay on, or the tests below would pass for the wrong
    # reason; an unset http.sslVerify means git verifies.
    ssl_verify = _git_config(infrahub_custom_ca_k8s, path, "http.sslVerify")
    assert ssl_verify in ("", "true"), (
        f"git certificate verification is disabled: http.sslVerify={ssl_verify}"
    )


async def test_repository_behind_private_ca_is_imported(infrahub_custom_ca_k8s):
    """A repository on an HTTPS remote signed by the trusted CA clones and imports."""
    kubeconfig = infrahub_custom_ca_k8s["kubeconfig_path"]
    namespace = infrahub_custom_ca_k8s["namespace"]
    token = infrahub_custom_ca_k8s["token"]
    name = f"trusted-{uuid.uuid4().hex[:8]}"

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_custom_ca_k8s["server_label"], ready_path="/api/config",
    ) as url:
        await add_read_only_repository(
            url,
            token,
            name=name,
            location=infrahub_custom_ca_k8s["trusted_repository_url"],
        )
        state = await wait_for_repository_imported(url, token, name=name)

    assert state["operational_status"] == "online", state
    assert state["commit"], f"repository '{name}' has no commit, the clone did not land: {state}"


async def test_repository_behind_an_untrusted_ca_is_rejected(infrahub_custom_ca_k8s):
    """The same setup against a CA that is *not* in the bundle fails to connect.

    Infrahub checks connectivity before it keeps the repository, so a failed TLS
    handshake surfaces as an error on the create mutation.
    """
    kubeconfig = infrahub_custom_ca_k8s["kubeconfig_path"]
    namespace = infrahub_custom_ca_k8s["namespace"]
    token = infrahub_custom_ca_k8s["token"]
    name = f"untrusted-{uuid.uuid4().hex[:8]}"

    async with portforward_service(
        kubeconfig, namespace, 8000,
        label_selector=infrahub_custom_ca_k8s["server_label"], ready_path="/api/config",
    ) as url:
        with pytest.raises(GraphQLError) as exc_info:
            await add_read_only_repository(
                url,
                token,
                name=name,
                location=infrahub_custom_ca_k8s["untrusted_repository_url"],
            )

    # The wording depends on which TLS backend git was built against — Infrahub
    # rewrites the OpenSSL phrasing ("SSL certificate problem") into "SSL
    # verification failed", and passes the GnuTLS one ("server verification
    # failed: certificate signer not trusted") through as-is. Both say the same
    # thing, so match the part they share rather than one build's message.
    assert "verification failed" in str(exc_info.value).lower(), (
        f"expected a certificate verification failure, got: {exc_info.value}"
    )
