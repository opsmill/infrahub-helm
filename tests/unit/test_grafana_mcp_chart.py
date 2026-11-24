"""Render tests for the Grafana MCP server of the infrahub-observability chart.

They run `helm template` on a copy of the chart without its `dependencies`, so they
need the `helm` binary but no network and no vcluster. Only the objects of the
Grafana MCP server are checked: the sub-charts are not rendered.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parents[2] / "charts" / "infrahub-observability"
# A value for the tests only. It is not a secret.
TEST_TOKEN = "unit-test-token-not-a-secret"
TOKEN_REQUIRED = (
    "grafanaMcp.serverToken.value or grafanaMcp.serverToken.existingSecret is required"
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


@pytest.fixture(scope="module")
def chart(tmp_path_factory) -> Path:
    """A copy of the chart without sub-chart dependencies, so that it renders offline."""
    target = tmp_path_factory.mktemp("chart") / "infrahub-observability"
    shutil.copytree(CHART_DIR, target, ignore=shutil.ignore_patterns("charts", "Chart.lock"))
    chart_yaml = yaml.safe_load((target / "Chart.yaml").read_text())
    chart_yaml.pop("dependencies", None)
    (target / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    return target


def helm_template(chart: Path, *sets: str, release: str = "obs") -> subprocess.CompletedProcess:
    cmd = ["helm", "template", release, str(chart), "--namespace", "monitoring"]
    for item in sets:
        cmd.extend(["--set", item])
    return subprocess.run(cmd, capture_output=True, text=True)


def render(chart: Path, *sets: str, release: str = "obs") -> list[dict]:
    result = helm_template(chart, *sets, release=release)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def mcp_objects(docs: list[dict]) -> dict[str, dict]:
    """The objects whose name contains grafana-mcp, keyed by kind (kind/name when several)."""
    found: dict[str, dict] = {}
    for doc in docs:
        name = doc["metadata"]["name"]
        if "grafana-mcp" in name:
            found[f"{doc['kind']}/{name}"] = doc
    return found


def one(docs: list[dict], kind: str) -> dict:
    matches = [d for k, d in mcp_objects(docs).items() if k.startswith(f"{kind}/")]
    assert len(matches) == 1, f"expected one {kind}, got {len(matches)}"
    return matches[0]


def container_args(docs: list[dict]) -> list[str]:
    return one(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]["args"]


ENABLED = ("grafanaMcp.enabled=true", f"grafanaMcp.serverToken.value={TEST_TOKEN}")


def test_no_object_when_disabled(chart):
    assert mcp_objects(render(chart)) == {}


def test_no_object_when_disabled_even_with_a_token(chart):
    docs = render(chart, f"grafanaMcp.serverToken.value={TEST_TOKEN}")
    assert mcp_objects(docs) == {}


def test_render_fails_without_a_token(chart):
    result = helm_template(chart, "grafanaMcp.enabled=true")
    assert result.returncode != 0
    assert TOKEN_REQUIRED in result.stderr


def test_render_with_a_token_value_creates_the_objects(chart):
    kinds = sorted(key.split("/")[0] for key in mcp_objects(render(chart, *ENABLED)))
    assert kinds == [
        "ConfigMap",
        "Deployment",
        "Job",
        "Role",
        "RoleBinding",
        "Secret",
        "Service",
        "ServiceAccount",
    ]


def test_server_runs_the_same_options_as_compose(chart):
    args = container_args(render(chart, *ENABLED))
    assert args[:6] == [
        "--transport",
        "streamable-http",
        "--address",
        "0.0.0.0:8000",
        "--healthz-address",
        ":8081",
    ]
    for flag in (
        "--usage-stats=disabled",
        "--disable-write",
        "--disable-api",
        "--disable-docs",
        "--disable-plugin",
    ):
        assert flag in args
    assert args[args.index("--allowed-hosts") + 1] == "localhost:8100,127.0.0.1:8100"
    appended = args[args.index("--instructions-append") + 1]
    assert appended.startswith("In this stack the Grafana MCP server only reads")


def test_server_environment(chart):
    container = one(render(chart, *ENABLED), "Deployment")["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert env["DO_NOT_TRACK"]["value"] == "1"
    assert env["GRAFANA_URL"]["value"] == "http://obs-grafana"
    assert (
        env["GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE"]["value"]
        == "/var/run/grafana-mcp/token"
    )
    ref = env["MCP_GRAFANA_SERVER_TOKEN"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "obs-infrahub-observability-grafana-mcp", "key": "token"}


def test_the_token_value_is_only_in_the_secret(chart):
    docs = render(chart, *ENABLED)
    secret = one([d for d in docs if d["kind"] == "Secret"], "Secret")
    assert secret["stringData"]["token"] == TEST_TOKEN
    others = [d for d in docs if d["kind"] != "Secret"]
    assert TEST_TOKEN not in yaml.safe_dump(others)


def test_existing_secret_replaces_the_token_value(chart):
    docs = render(
        chart,
        "grafanaMcp.enabled=true",
        "grafanaMcp.serverToken.existingSecret=my-token",
        "grafanaMcp.serverToken.existingSecretKey=caller",
    )
    assert not [d for d in docs if d["kind"] == "Secret"]
    container = one(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    ref = env["MCP_GRAFANA_SERVER_TOKEN"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "my-token", "key": "caller"}


def test_image_is_pinned_by_tag_and_digest(chart):
    container = one(render(chart, *ENABLED), "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == (
        "grafana/mcp-grafana:2.0.2"
        "@sha256:78d208116ec52b09b44f0eca66892073b39aefcb64483c54d43255c8eab7e97a"
    )


def test_service_is_cluster_ip_by_default(chart):
    service = one(render(chart, *ENABLED), "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0]["port"] == 8000


@pytest.mark.parametrize("service_type", ["LoadBalancer", "NodePort"])
def test_render_fails_when_open_to_a_network_without_tls(chart, service_type):
    result = helm_template(chart, *ENABLED, f"grafanaMcp.service.type={service_type}")
    assert result.returncode != 0
    assert (
        f"grafanaMcp.service.type is {service_type}, which is open to a network: "
        "set grafanaMcp.tls.existingSecret"
    ) in result.stderr


@pytest.mark.parametrize("service_type", ["LoadBalancer", "NodePort"])
def test_render_works_when_open_to_a_network_with_tls(chart, service_type):
    docs = render(
        chart,
        *ENABLED,
        f"grafanaMcp.service.type={service_type}",
        "grafanaMcp.tls.existingSecret=mcp-tls",
    )
    assert one(docs, "Service")["spec"]["type"] == service_type


def test_no_tls_flag_without_a_tls_secret(chart):
    docs = render(chart, *ENABLED)
    args = container_args(docs)
    assert not [a for a in args if a.startswith("--server.tls")]
    pod = one(docs, "Deployment")["spec"]["template"]["spec"]
    assert "tls" not in [v["name"] for v in pod["volumes"]]


def test_tls_flags_and_mount_with_a_tls_secret(chart):
    docs = render(chart, *ENABLED, "grafanaMcp.tls.existingSecret=mcp-tls")
    args = container_args(docs)
    assert args[args.index("--server.tls-cert-file") + 1] == "/etc/grafana-mcp/tls/tls.crt"
    assert args[args.index("--server.tls-key-file") + 1] == "/etc/grafana-mcp/tls/tls.key"
    pod = one(docs, "Deployment")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "tls")
    assert volume["secret"]["secretName"] == "mcp-tls"
    mount = next(m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "tls")
    assert mount["readOnly"] is True
    assert mount["mountPath"] == "/etc/grafana-mcp/tls"
    # The server runs as user 1000, group 999. The key must be readable by the group.
    assert pod["securityContext"]["fsGroup"] == 999
    assert volume["secret"]["defaultMode"] == 0o440


def test_probes_use_the_side_listener_over_http(chart):
    for extra in ((), ("grafanaMcp.tls.existingSecret=mcp-tls",)):
        container = one(render(chart, *ENABLED, *extra), "Deployment")["spec"]["template"]["spec"]["containers"][0]
        for name in ("startupProbe", "readinessProbe", "livenessProbe"):
            probe = container[name]["httpGet"]
            assert probe["path"] == "/healthz"
            assert probe["port"] == "health"
            assert probe.get("scheme", "HTTP") == "HTTP"
        ports = {p["name"]: p["containerPort"] for p in container["ports"]}
        assert ports == {"http": 8000, "health": 8081}


def test_grafana_token_secret_is_optional_in_the_pod(chart):
    """A missing Secret must not block the pod, or `helm install --wait` never reaches the hook."""
    pod = one(render(chart, *ENABLED), "Deployment")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "grafana-token")
    assert volume["secret"]["secretName"] == "obs-infrahub-observability-grafana-mcp-grafana-token"
    assert volume["secret"]["optional"] is True
    mount = next(m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "grafana-token")
    assert mount["readOnly"] is True


def test_job_is_a_post_install_and_post_upgrade_hook(chart):
    job = one(render(chart, *ENABLED), "Job")
    annotations = job["metadata"]["annotations"]
    assert annotations["helm.sh/hook"] == "post-install,post-upgrade"
    assert annotations["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"


def test_role_is_limited_to_the_token_secret(chart):
    role = one(render(chart, *ENABLED), "Role")
    by_verb = {}
    for rule in role["rules"]:
        assert rule["apiGroups"] == [""]
        assert rule["resources"] == ["secrets"]
        for verb in rule["verbs"]:
            by_verb[verb] = rule.get("resourceNames")
    assert sorted(by_verb) == ["create", "get", "update"]
    # Kubernetes cannot limit `create` by name; `get` and `update` are limited.
    assert by_verb["create"] is None
    name = "obs-infrahub-observability-grafana-mcp-grafana-token"
    assert by_verb["get"] == [name]
    assert by_verb["update"] == [name]


def test_job_reads_the_grafana_admin_secret(chart):
    job = one(render(chart, *ENABLED), "Job")
    container = job["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert env["GRAFANA_URL"]["value"] == "http://obs-grafana"
    assert env["GRAFANA_ADMIN_USER"]["valueFrom"]["secretKeyRef"] == {
        "name": "obs-grafana",
        "key": "admin-user",
    }
    assert env["GRAFANA_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "obs-grafana",
        "key": "admin-password",
    }
    assert env["GRAFANA_MCP_ROLE"]["value"] == "Viewer"
    assert env["GRAFANA_MCP_TOKEN_FILE"]["value"].endswith("/token")


def test_grafana_url_and_admin_secret_can_be_set(chart):
    docs = render(
        chart,
        *ENABLED,
        "grafanaMcp.grafana.url=https://grafana.example.com",
        "grafanaMcp.grafana.adminSecret=my-admin",
    )
    container = one(docs, "Job")["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert env["GRAFANA_URL"]["value"] == "https://grafana.example.com"
    assert env["GRAFANA_ADMIN_USER"]["valueFrom"]["secretKeyRef"]["name"] == "my-admin"


def test_script_is_the_copy_in_the_chart(chart):
    configmap = one(render(chart, *ENABLED), "ConfigMap")
    script = (CHART_DIR / "files" / "grafana-mcp" / "create-service-account.sh").read_text()
    assert configmap["data"]["create-service-account.sh"].strip() == script.strip()
    assert "run.sh" in configmap["data"]


def test_the_job_script_never_prints_a_token():
    run = (CHART_DIR / "files" / "grafana-mcp" / "run.sh").read_text()
    for line in run.splitlines():
        if line.lstrip().startswith("echo") or line.lstrip().startswith("printf"):
            assert "$token" not in line and "${token" not in line
