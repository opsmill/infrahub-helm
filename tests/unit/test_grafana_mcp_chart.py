"""Render tests for the Grafana MCP server of the infrahub-observability chart.

They run `helm template` on a copy of the chart whose only dependency is `grafana-mcp`,
the community chart that renders the server. They need the `helm` binary and the network
once, to download that chart. They need no vcluster. The other sub-charts are not rendered.
"""

import base64
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parents[2] / "charts" / "infrahub-observability"
# A value for the tests only. It is not a secret.
TEST_TOKEN = "unit-test-token-not-a-secret"
TOKEN_REQUIRED = "grafana-mcp.serverAuth.token or grafana-mcp.serverAuth.tokenSecret.name is required"
DIGEST = "sha256:78d208116ec52b09b44f0eca66892073b39aefcb64483c54d43255c8eab7e97a"
SERVER = "obs-grafana-mcp"
JOB = "obs-infrahub-observability-grafana-mcp-init"
GRAFANA_TOKEN_SECRET = "grafana-mcp-service-account-token"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


@pytest.fixture(scope="module")
def chart(tmp_path_factory) -> Path:
    """A copy of the chart that has only the grafana-mcp dependency, downloaded from its repository."""
    target = tmp_path_factory.mktemp("chart") / "infrahub-observability"
    shutil.copytree(CHART_DIR, target, ignore=shutil.ignore_patterns("charts", "Chart.lock"))
    chart_yaml = yaml.safe_load((target / "Chart.yaml").read_text())
    dependency = next(d for d in chart_yaml["dependencies"] if d["name"] == "grafana-mcp")
    chart_yaml["dependencies"] = [dependency]
    (target / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    (target / "charts").mkdir()
    pulled = subprocess.run(
        [
            "helm",
            "pull",
            "grafana-mcp",
            "--repo",
            dependency["repository"],
            "--version",
            dependency["version"],
            "--destination",
            str(target / "charts"),
        ],
        capture_output=True,
        text=True,
    )
    assert pulled.returncode == 0, pulled.stderr
    return target


def helm_template(
    chart: Path, *sets: str, release: str = "obs", values: dict | None = None
) -> subprocess.CompletedProcess:
    """Run `helm template`. `values` is for a value that `--set` cannot hold, such as a text with commas."""
    cmd = ["helm", "template", release, str(chart), "--namespace", "monitoring"]
    for item in sets:
        cmd.extend(["--set", item])
    if values is None:
        return subprocess.run(cmd, capture_output=True, text=True)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as values_file:
        yaml.safe_dump(values, values_file)
        values_file.flush()
        return subprocess.run([*cmd, "--values", values_file.name], capture_output=True, text=True)


def render(
    chart: Path, *sets: str, release: str = "obs", values: dict | None = None
) -> list[dict]:
    result = helm_template(chart, *sets, release=release, values=values)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def mcp_objects(docs: list[dict]) -> dict[str, dict]:
    """The objects whose name contains grafana-mcp, keyed by kind/name."""
    return {
        f"{doc['kind']}/{doc['metadata']['name']}": doc
        for doc in docs
        if "grafana-mcp" in doc["metadata"]["name"]
    }


def named(docs: list[dict], kind: str, name: str) -> dict:
    return mcp_objects(docs)[f"{kind}/{name}"]


def server_pod(docs: list[dict]) -> dict:
    return named(docs, "Deployment", SERVER)["spec"]["template"]["spec"]


def server_container(docs: list[dict]) -> dict:
    return server_pod(docs)["containers"][0]


def container_args(docs: list[dict]) -> list[str]:
    return server_container(docs)["args"]


def env_of(container: dict) -> dict[str, dict]:
    return {item["name"]: item for item in container["env"]}


ENABLED = ("grafana-mcp-setup.enabled=true", f"grafana-mcp.serverAuth.token={TEST_TOKEN}")


def tls_values() -> dict:
    """Values that serve HTTPS. A list replaces the default one, so this repeats the other arguments."""
    default = yaml.safe_load((CHART_DIR / "values.yaml").read_text())["grafana-mcp"]["extraArgs"]
    return {
        "grafana-mcp": {
            "extraArgs": [
                *default,
                "--server.tls-cert-file=/etc/grafana-mcp/tls/tls.crt",
                "--server.tls-key-file=/etc/grafana-mcp/tls/tls.key",
            ]
        }
    }


def test_no_object_when_disabled(chart):
    assert mcp_objects(render(chart)) == {}


def test_no_object_when_disabled_even_with_a_token(chart):
    docs = render(chart, f"grafana-mcp.serverAuth.token={TEST_TOKEN}")
    assert mcp_objects(docs) == {}


def test_one_flag_turns_on_the_dependency_and_the_job(chart):
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
        "ServiceAccount",
    ]


def test_dependency_flag_is_not_a_value_of_the_dependency(chart):
    """The values schema of grafana-mcp rejects an `enabled` key, so the flag is grafana-mcp-setup.enabled."""
    result = helm_template(chart, *ENABLED, "grafana-mcp.enabled=true")
    assert result.returncode != 0
    assert "enabled" in result.stderr


def test_render_fails_without_a_token(chart):
    result = helm_template(chart, "grafana-mcp-setup.enabled=true")
    assert result.returncode != 0
    assert TOKEN_REQUIRED in result.stderr


@pytest.mark.parametrize("value", ["grafana-mcp.serverAuth.token=null", "grafana-mcp.serverAuth.token="])
def test_render_fails_when_the_token_is_empty_or_null(chart, value):
    """The dependency generates a token for "" and turns authentication off for null."""
    result = helm_template(chart, "grafana-mcp-setup.enabled=true", value)
    assert result.returncode != 0
    assert TOKEN_REQUIRED in result.stderr


def test_the_token_value_is_only_in_the_secret(chart):
    docs = render(chart, *ENABLED)
    secret = named(docs, "Secret", SERVER)
    assert base64.b64decode(secret["data"]["server-token"]).decode() == TEST_TOKEN
    others = [d for d in docs if d["kind"] != "Secret"]
    assert TEST_TOKEN not in yaml.safe_dump(others)


def test_existing_secret_replaces_the_token_value(chart):
    docs = render(
        chart,
        "grafana-mcp-setup.enabled=true",
        "grafana-mcp.serverAuth.tokenSecret.name=my-token",
        "grafana-mcp.serverAuth.tokenSecret.key=caller",
    )
    assert f"Secret/{SERVER}" not in mcp_objects(docs)
    ref = env_of(server_container(docs))["MCP_GRAFANA_SERVER_TOKEN"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "my-token", "key": "caller"}


def test_existing_secret_needs_a_key(chart):
    result = helm_template(
        chart, "grafana-mcp-setup.enabled=true", "grafana-mcp.serverAuth.tokenSecret.name=my-token", "grafana-mcp.serverAuth.tokenSecret.key="
    )
    assert result.returncode != 0
    assert "grafana-mcp.serverAuth.tokenSecret.key is required" in result.stderr


def test_server_runs_the_same_options_as_compose(chart):
    args = container_args(render(chart, *ENABLED))
    start = args.index("--transport")
    assert args[start : start + 6] == [
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
    appended = args[args.index("--instructions-append") + 1]
    assert appended.startswith("In this stack the Grafana MCP server only reads")


def test_allowed_hosts_have_the_service_names_and_the_port_forward(chart):
    args = container_args(render(chart, *ENABLED))
    hosts = next(a for a in args if a.startswith("--allowed-hosts=")).split("=", 1)[1].split(",")
    for host in (
        "localhost:8100",
        "127.0.0.1:8100",
        "localhost:8000",
        f"{SERVER}:8000",
        f"{SERVER}.monitoring.svc:8000",
    ):
        assert host in hosts


def test_server_environment(chart):
    container = server_container(render(chart, *ENABLED))
    env = env_of(container)
    assert env["DO_NOT_TRACK"]["value"] == "1"
    assert env["GRAFANA_URL"]["value"] == "http://obs-grafana"
    assert env["GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE"]["value"] == "/var/run/grafana-mcp/token"
    assert env["MCP_GRAFANA_SERVER_TOKEN"]["valueFrom"]["secretKeyRef"] == {
        "name": SERVER,
        "key": "server-token",
    }


def test_image_is_pinned_by_tag_and_digest(chart):
    assert server_container(render(chart, *ENABLED))["image"] == (
        f"docker.io/grafana/mcp-grafana:2.0.2@{DIGEST}"
    )


def test_service_is_cluster_ip_by_default(chart):
    service = named(render(chart, *ENABLED), "Service", SERVER)
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0]["port"] == 8000


@pytest.mark.parametrize("service_type", ["LoadBalancer", "NodePort"])
def test_render_fails_when_open_to_a_network_without_tls(chart, service_type):
    result = helm_template(chart, *ENABLED, f"grafana-mcp.service.type={service_type}")
    assert result.returncode != 0
    assert (
        f"grafana-mcp.service.type is {service_type}, which is open to a network: "
        "serve HTTPS with --server.tls-cert-file and --server.tls-key-file in grafana-mcp.extraArgs"
    ) in result.stderr


@pytest.mark.parametrize("service_type", ["LoadBalancer", "NodePort"])
def test_render_works_when_open_to_a_network_with_tls(chart, service_type):
    docs = render(chart, *ENABLED, f"grafana-mcp.service.type={service_type}", values=tls_values())
    assert named(docs, "Service", SERVER)["spec"]["type"] == service_type


def test_no_tls_flag_by_default(chart):
    docs = render(chart, *ENABLED)
    assert not [a for a in container_args(docs) if a.startswith("--server.tls")]


def test_tls_flags_are_arguments_of_the_server(chart):
    args = container_args(render(chart, *ENABLED, values=tls_values()))
    assert "--server.tls-cert-file=/etc/grafana-mcp/tls/tls.crt" in args
    assert "--server.tls-key-file=/etc/grafana-mcp/tls/tls.key" in args


def test_pod_can_read_a_tls_key_of_group_999(chart):
    """The server runs as user 1000, group 999. A mounted key must be readable by the group."""
    pod = server_pod(render(chart, *ENABLED))
    assert pod["securityContext"]["fsGroup"] == 999
    assert pod["securityContext"]["runAsUser"] == 1000
    assert pod["securityContext"]["runAsGroup"] == 999
    container_context = pod["containers"][0]["securityContext"]
    assert container_context["readOnlyRootFilesystem"] is True
    assert container_context["allowPrivilegeEscalation"] is False
    assert container_context["capabilities"] == {"drop": ["ALL"]}


def test_probes_have_one_handler_and_the_right_ports(chart):
    container = server_container(render(chart, *ENABLED))
    for name in ("startupProbe", "readinessProbe", "livenessProbe"):
        handlers = {"httpGet", "tcpSocket", "exec", "grpc"} & set(container[name])
        assert len(handlers) == 1, f"{name} has {sorted(handlers)}"
    for name in ("startupProbe", "livenessProbe"):
        http_get = container[name]["httpGet"]
        assert http_get["path"] == "/healthz"
        assert http_get["port"] == 8081
        assert http_get.get("scheme", "HTTP") == "HTTP"
    # The readiness check is a TCP check on the main port, so it works with TLS too.
    assert container["readinessProbe"]["tcpSocket"]["port"] == "mcp-http"
    assert "--healthz-address" in container["args"]


def merge_keeping_defaults(default: dict, override: dict) -> dict:
    """Merge two maps. A null in `override` does not remove the key of `default`."""
    merged = dict(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_keeping_defaults(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


def test_probes_keep_one_handler_when_values_are_reused(chart):
    """`helm upgrade --reuse-values` renders from the stored values of the release.

    Those hold the defaults of the grafana-mcp dependency again, because a null in
    values.yaml does not remove them there. So the probes must not depend on a null:
    each key of a default probe that the chart overrides must give one handler.
    """
    with tarfile.open(next((chart / "charts").glob("grafana-mcp-*.tgz"))) as archive:
        defaults = yaml.safe_load(archive.extractfile("grafana-mcp/values.yaml").read())
    ours = yaml.safe_load((CHART_DIR / "values.yaml").read_text())["grafana-mcp"]
    stored = merge_keeping_defaults(defaults, ours)
    docs = render(chart, *ENABLED, values={"grafana-mcp": stored})
    container = server_container(docs)
    for name in ("startupProbe", "readinessProbe", "livenessProbe"):
        handlers = {"httpGet", "tcpSocket", "exec", "grpc"} & set(container[name])
        assert len(handlers) == 1, f"{name} has {sorted(handlers)}"


def test_values_do_not_set_null_for_the_dependency():
    """A null removes a default only in a fresh render. `--reuse-values` brings the default back."""

    def nulls(node: object, path: str = "") -> list[str]:
        if not isinstance(node, dict):
            return []
        found = []
        for key, value in node.items():
            if value is None:
                found.append(f"{path}.{key}")
            found.extend(nulls(value, f"{path}.{key}"))
        return found

    ours = yaml.safe_load((CHART_DIR / "values.yaml").read_text())["grafana-mcp"]
    assert nulls(ours, "grafana-mcp") == []


def test_grafana_token_secret_is_optional_in_the_pod(chart):
    """A missing Secret must not block the pod, or `helm install --wait` never reaches the hook."""
    pod = server_pod(render(chart, *ENABLED))
    volume = next(v for v in pod["volumes"] if v["name"] == "grafana-token")
    assert volume["secret"]["secretName"] == GRAFANA_TOKEN_SECRET
    assert volume["secret"]["optional"] is True
    assert volume["secret"]["defaultMode"] == 0o440
    mount = next(m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "grafana-token")
    assert mount["readOnly"] is True
    assert mount["mountPath"] == "/var/run/grafana-mcp"


def test_job_writes_the_secret_that_the_pod_mounts(chart):
    docs = render(chart, *ENABLED)
    volume = next(v for v in server_pod(docs)["volumes"] if v["name"] == "grafana-token")
    job = named(docs, "Job", JOB)
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert env_of(container)["GRAFANA_MCP_TOKEN_SECRET"]["value"] == volume["secret"]["secretName"]
    role = named(docs, "Role", JOB)
    names = [n for rule in role["rules"] for n in rule.get("resourceNames", [])]
    assert names == [volume["secret"]["secretName"]]


def test_render_follows_a_renamed_token_volume_secret(chart):
    docs = render(
        chart,
        *ENABLED,
        "grafana-mcp.volumes[0].name=grafana-token",
        "grafana-mcp.volumes[0].secret.secretName=other-token",
        "grafana-mcp.volumes[0].secret.optional=true",
    )
    job = named(docs, "Job", JOB)
    env = env_of(job["spec"]["template"]["spec"]["containers"][0])
    assert env["GRAFANA_MCP_TOKEN_SECRET"]["value"] == "other-token"


def test_render_fails_without_the_token_volume(chart):
    result = helm_template(chart, *ENABLED, "grafana-mcp.volumes[0].name=other", "grafana-mcp.volumes[0].emptyDir=true")
    assert result.returncode != 0
    assert "must have a volume named grafana-token" in result.stderr


def test_job_is_a_post_install_and_post_upgrade_hook(chart):
    annotations = named(render(chart, *ENABLED), "Job", JOB)["metadata"]["annotations"]
    assert annotations["helm.sh/hook"] == "post-install,post-upgrade"
    assert annotations["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"


def test_role_is_limited_to_the_token_secret(chart):
    role = named(render(chart, *ENABLED), "Role", JOB)
    by_verb = {}
    for rule in role["rules"]:
        assert rule["apiGroups"] == [""]
        assert rule["resources"] == ["secrets"]
        for verb in rule["verbs"]:
            by_verb[verb] = rule.get("resourceNames")
    assert sorted(by_verb) == ["create", "get", "update"]
    # Kubernetes cannot limit `create` by name; `get` and `update` are limited.
    assert by_verb["create"] is None
    assert by_verb["get"] == [GRAFANA_TOKEN_SECRET]
    assert by_verb["update"] == [GRAFANA_TOKEN_SECRET]


def test_job_reads_the_grafana_admin_secret(chart):
    job = named(render(chart, *ENABLED), "Job", JOB)
    env = env_of(job["spec"]["template"]["spec"]["containers"][0])
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
        "grafana-mcp.grafana.url=https://grafana.example.com",
        "grafana-mcp-setup.grafanaAdminSecret=my-admin",
    )
    env = env_of(named(docs, "Job", JOB)["spec"]["template"]["spec"]["containers"][0])
    assert env["GRAFANA_URL"]["value"] == "https://grafana.example.com"
    assert env["GRAFANA_ADMIN_USER"]["valueFrom"]["secretKeyRef"]["name"] == "my-admin"
    assert env_of(server_container(docs))["GRAFANA_URL"]["value"] == "https://grafana.example.com"


def test_render_fails_with_the_default_url_and_another_release_name(chart):
    result = helm_template(chart, *ENABLED, release="monitoring")
    assert result.returncode != 0
    assert (
        "grafana-mcp.grafana.url is the default for a release named obs, and this release is named monitoring: "
        "set it to http://monitoring-grafana"
    ) in result.stderr


def test_render_works_with_another_release_name_and_its_url(chart):
    docs = render(chart, *ENABLED, "grafana-mcp.grafana.url=http://monitoring-grafana", release="monitoring")
    container = named(docs, "Deployment", "monitoring-grafana-mcp")["spec"]["template"]["spec"]["containers"][0]
    assert env_of(container)["GRAFANA_URL"]["value"] == "http://monitoring-grafana"


def test_render_fails_without_grafana_and_without_a_url(chart):
    result = helm_template(chart, *ENABLED, "grafana.enabled=false")
    assert result.returncode != 0
    assert "grafana-mcp.grafana.url is required when grafana.enabled is false" in result.stderr


def test_two_releases_have_their_own_server_and_job(chart):
    first = mcp_objects(render(chart, *ENABLED, release="obs"))
    second = mcp_objects(
        render(chart, *ENABLED, "grafana-mcp.grafana.url=http://two-grafana", release="two")
    )
    assert "Deployment/obs-grafana-mcp" in first
    assert "Deployment/two-grafana-mcp" in second
    assert first.keys().isdisjoint(second.keys())


@pytest.mark.parametrize(
    "overrides, flag",
    [
        (("grafana-mcp.disableWrite=false",), "--disable-write"),
        (("grafana-mcp.disabledCategories={docs,plugin}",), "--disable-api"),
        (("grafana-mcp.disabledCategories={api,plugin}",), "--disable-docs"),
        (("grafana-mcp.disabledCategories={api,docs}",), "--disable-plugin"),
        (("grafana-mcp.disabledCategories=null",), "--disable-api"),
    ],
)
def test_render_fails_when_a_read_only_flag_is_removed(chart, overrides, flag):
    result = helm_template(chart, *ENABLED, *overrides)
    assert result.returncode != 0
    assert f"grafana-mcp must pass {flag}" in result.stderr


def test_render_fails_when_extra_args_turn_a_read_only_flag_off(chart):
    result = helm_template(chart, *ENABLED, "grafana-mcp.extraArgs[0]=--disable-write=false")
    assert result.returncode != 0
    assert "turns a read-only flag off" in result.stderr


def test_read_only_flags_in_extra_args_are_enough(chart):
    docs = render(
        chart,
        *ENABLED,
        "grafana-mcp.disableWrite=false",
        "grafana-mcp.disabledCategories=null",
        "grafana-mcp.extraArgs={--disable-write,--disable-api,--disable-docs,--disable-plugin}",
    )
    assert "--disable-write" in container_args(docs)


def test_script_is_the_copy_in_the_chart(chart):
    configmap = named(render(chart, *ENABLED), "ConfigMap", JOB)
    script = (CHART_DIR / "files" / "grafana-mcp" / "create-service-account.sh").read_text()
    assert configmap["data"]["create-service-account.sh"].strip() == script.strip()
    assert "run.sh" in configmap["data"]


def test_the_job_script_never_prints_a_token():
    run = (CHART_DIR / "files" / "grafana-mcp" / "run.sh").read_text()
    for line in run.splitlines():
        if line.lstrip().startswith("echo") or line.lstrip().startswith("printf"):
            assert "$token" not in line and "${token" not in line


def notes(chart: Path, *sets: str, release: str = "obs") -> str:
    """The install notes. `helm template` does not print them, so use a client-side dry run."""
    cmd = ["helm", "install", release, str(chart), "--namespace", "monitoring", "--dry-run=client"]
    for item in sets:
        cmd.extend(["--set", item])
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "\nNOTES:\n" in result.stdout
    return result.stdout.split("\nNOTES:\n", 1)[1]


def test_install_notes_name_the_grafana_mcp_server_when_it_is_on(chart):
    text = notes(chart, *ENABLED, release="obs")
    assert "port-forward svc/obs-grafana-mcp 8100:8000" in text
    assert "http://localhost:8100/mcp" in text
    assert "Authorization: Bearer" in text
    assert "read-only" in text
    assert "up to about three minutes" in text
    assert "--namespace monitoring" in text


def test_install_notes_have_no_grafana_mcp_section_when_it_is_off(chart):
    assert "grafana-mcp" not in notes(chart, "grafana.enabled=true")
