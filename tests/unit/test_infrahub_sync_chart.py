"""Render tests of the infrahub-sync chart.

Each test runs `helm template` on the local chart, with no cluster, and checks the rendered
manifests against the properties of the chart's contract.
"""

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "charts" / "infrahub-sync"

# Placeholder credentials for render tests. They are never used against a service.
TEST_CREDENTIAL = "test-" * 4


def render(
    values: dict, *, expect_failure: bool = False, extra_args: tuple[str, ...] = ()
) -> list[dict] | str:
    """Render the chart with `values`, adding `extra_args` to `helm template`.

    Returns the parsed documents, empty ones left out. With `expect_failure`, the render must
    fail and the error text is returned instead.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(values, handle)
        values_file = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "helm",
                "template",
                "sync",
                str(CHART),
                "-f",
                str(values_file),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        values_file.unlink()
    if expect_failure:
        assert result.returncode != 0, "the render succeeded but a failure was expected"
        return result.stderr
    assert result.returncode == 0, result.stderr
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def find(documents: list[dict], kind: str, name: str) -> dict | None:
    """Return the document of this kind and name, or None."""
    for document in documents:
        if document["kind"] == kind and document["metadata"]["name"] == name:
            return document
    return None


@pytest.fixture
def valid_values() -> dict:
    """Minimal valid values: the chart creates the Secret from test credentials."""
    return {
        "credentials": {
            "bearerTokens": json.dumps(
                {"operator": {"token": TEST_CREDENTIAL, "administrator": True}}
            ),
            "prefectAuthString": f"prefect:{TEST_CREDENTIAL}",
            "s3AccessKey": TEST_CREDENTIAL,
            "s3SecretKey": TEST_CREDENTIAL,
            "postgresAdminPassword": TEST_CREDENTIAL,
            "productPassword": TEST_CREDENTIAL,
            "prefectPassword": TEST_CREDENTIAL,
        }
    }


@pytest.fixture
def existing_secret_values() -> dict:
    """Valid values that name an existing Secret instead of setting credentials."""
    return {"credentials": {"existingSecret": "infrahub-sync"}}


# Harness self-tests


def test_lint_values_render():
    values = yaml.safe_load((CHART / "ci" / "lint-values.yaml").read_text())
    documents = render(values)
    assert find(documents, "ServiceAccount", "sync-infrahub-sync") is not None
    assert find(documents, "Secret", "sync-infrahub-sync") is None


def test_valid_values_create_the_secret_with_set_keys_only(valid_values):
    documents = render(valid_values)
    secret = find(documents, "Secret", "sync-infrahub-sync")
    assert secret is not None
    assert set(secret["data"]) == {
        "INFRAHUB_SYNC_SERVICE_BEARER_TOKENS",
        "INFRAHUB_SYNC_PREFECT_AUTH_STRING",
        "INFRAHUB_SYNC_S3_ACCESS_KEY",
        "INFRAHUB_SYNC_S3_SECRET_KEY",
        "INFRAHUB_SYNC_POSTGRES_ADMIN_PASSWORD",
        "INFRAHUB_SYNC_PRODUCT_PASSWORD",
        "INFRAHUB_SYNC_PREFECT_PASSWORD",
    }


def test_service_account_does_not_mount_its_token(existing_secret_values):
    documents = render(existing_secret_values)
    account = find(documents, "ServiceAccount", "sync-infrahub-sync")
    assert account["automountServiceAccountToken"] is False


# Refusals (part of RR-40 to RR-45)


@pytest.mark.parametrize(
    "value",
    [
        "bearerTokens",
        "prefectAuthString",
        "s3AccessKey",
        "s3SecretKey",
        "postgresAdminPassword",
        "productPassword",
        "prefectPassword",
    ],
)
def test_missing_required_credential_is_refused(valid_values, value):
    del valid_values["credentials"][value]
    error = render(valid_values, expect_failure=True)
    assert f"credentials.{value}" in error


def test_bad_worker_credential_key_is_refused(existing_secret_values):
    existing_secret_values["worker"] = {"credentials": {"NETBOX_TOKEN": "x"}}
    error = render(existing_secret_values, expect_failure=True)
    assert "NETBOX_TOKEN" in error


def test_bad_addressing_style_is_refused(existing_secret_values):
    existing_secret_values["objectStore"] = {"enabled": False}
    existing_secret_values["s3"] = {
        "endpointUrl": "https://s3.example.com",
        "addressingStyle": "dns",
    }
    error = render(existing_secret_values, expect_failure=True)
    assert "s3.addressingStyle" in error


def test_rr41_endpoint_with_bundled_object_store_is_refused(existing_secret_values):
    existing_secret_values["s3"] = {"endpointUrl": "https://s3.example.com"}
    error = render(existing_secret_values, expect_failure=True)
    assert "s3.endpointUrl" in error
    assert "objectStore.enabled" in error


# Helpers for the properties of a rendered release

FULLNAME = "sync-infrahub-sync"
WORKLOAD_KINDS = {
    "Deployment",
    "StatefulSet",
    "Job",
    "DaemonSet",
    "CronJob",
    "Pod",
    "ReplicaSet",
}
SYNC_COMPONENTS = ["api", "worker", "prefect-server", "bootstrap"]
ALL_COMPONENTS = [*SYNC_COMPONENTS, "postgresql", "object-store"]
SCRATCH_PATHS = {
    "/var/lib/infrahub-sync",
    "/var/lib/infrahub-sync/prefect",
    "/tmp/infrahub-sync",
}
REFERENCE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")


def workloads(documents: list[dict]) -> list[dict]:
    """Return the documents that run pods."""
    return [document for document in documents if document["kind"] in WORKLOAD_KINDS]


def component_of(document: dict) -> str:
    """Return the `app.kubernetes.io/component` label of a document."""
    return document["metadata"]["labels"]["app.kubernetes.io/component"]


def workload(documents: list[dict], component: str) -> dict:
    """Return the one workload of this component."""
    matches = [
        document
        for document in workloads(documents)
        if component_of(document) == component
    ]
    assert len(matches) == 1, f"{len(matches)} workloads of component {component}"
    return matches[0]


def pod_spec(document: dict) -> dict:
    """Return the pod spec of a workload."""
    return document["spec"]["template"]["spec"]


def containers(document: dict) -> list[dict]:
    """Return the init containers and containers of a workload."""
    spec = pod_spec(document)
    return [*spec.get("initContainers", []), *spec["containers"]]


def main_container(document: dict) -> dict:
    """Return the first (main) container of a workload."""
    return pod_spec(document)["containers"][0]


def env_value(container: dict, name: str) -> dict | None:
    """Return the env entry of this name, or None."""
    for entry in container.get("env", []):
        if entry["name"] == name:
            return entry
    return None


def secret_keys(document: dict) -> set[str]:
    """Return every Secret key that a container of the workload reads with secretKeyRef."""
    keys = set()
    for container in containers(document):
        for entry in container.get("env", []):
            reference = entry.get("valueFrom", {}).get("secretKeyRef")
            if reference:
                keys.add(reference["key"])
    return keys


def env_from_secrets(document: dict) -> set[str]:
    """Return the Secrets that a container of the workload reads with envFrom."""
    names = set()
    for container in containers(document):
        for source in container.get("envFrom", []):
            if "secretRef" in source:
                names.add(source["secretRef"]["name"])
    return names


def components_reading(documents: list[dict], key: str) -> set[str]:
    """Return the components whose pods read this key of a Secret."""
    return {
        component_of(document)
        for document in workloads(documents)
        if key in secret_keys(document)
    }


def resolve_port(container: dict, port: int | str) -> int:
    """Resolve a named container port to its number."""
    if isinstance(port, int):
        return port
    for entry in container.get("ports", []):
        if entry["name"] == port:
            return entry["containerPort"]
    raise AssertionError(f"no container port named {port}")


@pytest.fixture
def ca_values(valid_values) -> dict:
    """Valid values with one CA certificate."""
    valid_values["caCertificates"] = {
        "certificates": {
            "private-ca.pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
        }
    }
    return valid_values


# Default release (RR-01 to RR-26)


def test_rr01_release_holds_exactly_these_workloads(valid_values):
    documents = render(valid_values)
    found = {
        (document["kind"], document["metadata"]["name"])
        for document in workloads(documents)
    }
    jobs = {name for kind, name in found if kind == "Job"}
    assert found - {("Job", name) for name in jobs} == {
        ("Deployment", f"{FULLNAME}-api"),
        ("Deployment", f"{FULLNAME}-worker"),
        ("Deployment", f"{FULLNAME}-prefect-server"),
        ("StatefulSet", f"{FULLNAME}-postgresql"),
        ("StatefulSet", f"{FULLNAME}-object-store"),
    }
    assert len(jobs) == 1
    assert re.fullmatch(rf"{FULLNAME}-bootstrap-[0-9a-f]{{8}}", jobs.pop())


@pytest.mark.parametrize(("tag", "expected_tag"), [("", "3.0.0a5"), ("3.1.0", "3.1.0")])
def test_rr02_sync_containers_use_the_sync_image(valid_values, tag, expected_tag):
    valid_values["image"] = {"repository": "registry.example.com/sync", "tag": tag}
    documents = render(valid_values)
    repositories = set()
    for document in workloads(documents):
        for container in containers(document):
            image = container["image"]
            repositories.add(image.split("@")[0].rsplit(":", 1)[0])
            assert "prefecthq" not in image
            # The Prefect server pod's PostgreSQL wait runs `pg_isready` from the PostgreSQL image.
            if (
                component_of(document) in SYNC_COMPONENTS
                and container["name"] != "wait-for-postgresql"
            ):
                assert image == f"registry.example.com/sync:{expected_tag}", container[
                    "name"
                ]
    assert repositories == {"registry.example.com/sync", "postgres", "pgsty/silo"}


@pytest.mark.parametrize("component", ["postgresql", "object-store"])
def test_rr03_bundled_images_are_pinned_by_digest(valid_values, component):
    documents = render(valid_values)
    image = main_container(workload(documents, component))["image"]
    assert re.search(r"@sha256:[0-9a-f]{64}$", image)


@pytest.mark.parametrize("pull_secrets", [[], [{"name": "registry-credentials"}]])
def test_rr04_image_pull_secrets_in_every_pod(valid_values, pull_secrets):
    valid_values["imagePullSecrets"] = pull_secrets
    documents = render(valid_values)
    for document in workloads(documents):
        assert pod_spec(document).get("imagePullSecrets", []) == pull_secrets, (
            component_of(document)
        )


@pytest.mark.parametrize("component", SYNC_COMPONENTS)
def test_rr05_sync_containers_are_locked_down(valid_values, component):
    document = workload(render(valid_values), component)
    pod_context = pod_spec(document)["securityContext"]
    assert pod_context["runAsNonRoot"] is True
    assert pod_context["runAsUser"] == 10001
    assert pod_context["runAsGroup"] == 10001
    for container in containers(document):
        context = container["securityContext"]
        assert context["readOnlyRootFilesystem"] is True, container["name"]
        assert context["allowPrivilegeEscalation"] is False, container["name"]
        assert context["capabilities"]["drop"] == ["ALL"], container["name"]


@pytest.mark.parametrize("with_ca", [False, True])
@pytest.mark.parametrize("component", SYNC_COMPONENTS)
def test_rr06_sync_pods_mount_only_scratch_and_ca(ca_values, component, with_ca):
    if not with_ca:
        del ca_values["caCertificates"]
    document = workload(render(ca_values), component)
    volumes = pod_spec(document)["volumes"]
    scratch = [volume for volume in volumes if "emptyDir" in volume]
    others = [volume for volume in volumes if "emptyDir" not in volume]
    assert len(scratch) == 3
    assert all(volume["emptyDir"] == {"medium": "Memory"} for volume in scratch)
    if with_ca and component != "prefect-server":
        assert others == [
            {"name": "ca-certificates", "configMap": {"name": f"{FULLNAME}-ca"}}
        ]
    else:
        assert others == []
    scratch_names = {volume["name"] for volume in scratch}
    mounted = {
        mount["mountPath"]
        for container in containers(document)
        for mount in container.get("volumeMounts", [])
        if mount["name"] in scratch_names
    }
    assert mounted == SCRATCH_PATHS


def test_rr07_api_and_worker_share_no_volume_source(valid_values):
    documents = render(valid_values)

    def sources(component: str) -> list[str]:
        volumes = pod_spec(workload(documents, component))["volumes"]
        return [
            json.dumps({k: v for k, v in volume.items() if k != "name"}, sort_keys=True)
            for volume in volumes
            if "emptyDir" not in volume
        ]

    assert not set(sources("api")) & set(sources("worker"))


def test_rr08_only_the_stateful_sets_claim_volumes(valid_values):
    documents = render(valid_values)
    claiming = {
        component_of(document)
        for document in workloads(documents)
        if document["spec"].get("volumeClaimTemplates")
    }
    assert claiming == {"postgresql", "object-store"}
    for document in workloads(documents):
        for volume in pod_spec(document).get("volumes", []):
            assert "persistentVolumeClaim" not in volume
            assert "hostPath" not in volume


def test_rr09_no_pod_mounts_a_service_account_token(valid_values):
    for document in workloads(render(valid_values)):
        assert pod_spec(document)["automountServiceAccountToken"] is False, (
            component_of(document)
        )


def test_rr10_no_credential_value_with_an_existing_secret(valid_values):
    valid_values["credentials"]["existingSecret"] = "infrahub-sync"
    valid_values["credentials"]["infrahubApiToken"] = TEST_CREDENTIAL
    documents = render(valid_values)
    text = yaml.safe_dump_all(documents)
    assert TEST_CREDENTIAL not in text
    assert base64.b64encode(TEST_CREDENTIAL.encode()).decode() not in text
    assert all(document["kind"] != "Secret" for document in documents)


def test_rr10_credentials_never_in_a_config_map_or_env_value(valid_values):
    valid_values["worker"] = {
        "credentials": {"INFRAHUB_SYNC_CREDENTIAL_NETBOX_TOKEN": TEST_CREDENTIAL}
    }
    documents = render(valid_values)
    for document in documents:
        if document["kind"] == "ConfigMap":
            assert TEST_CREDENTIAL not in json.dumps(document)
    for document in workloads(documents):
        for container in containers(document):
            for entry in container.get("env", []):
                assert TEST_CREDENTIAL not in str(entry.get("value", "")), entry["name"]
            assert TEST_CREDENTIAL not in json.dumps(container.get("command", []))
            assert TEST_CREDENTIAL not in json.dumps(container.get("args", []))


def test_rr11_prefect_api_credential_reaches_only_its_clients(valid_values):
    documents = render(valid_values)
    assert components_reading(documents, "INFRAHUB_SYNC_PREFECT_AUTH_STRING") == set(
        SYNC_COMPONENTS
    )


@pytest.mark.parametrize(
    ("postgresql", "key", "expected"),
    [
        (True, "INFRAHUB_SYNC_PREFECT_PASSWORD", {"postgresql", "prefect-server"}),
        (False, "INFRAHUB_SYNC_PREFECT_DATABASE_URL", {"prefect-server"}),
    ],
)
def test_rr12_prefect_database_credential_reaches_only_postgresql_and_prefect(
    existing_secret_values, postgresql, key, expected
):
    existing_secret_values["postgresql"] = {"enabled": postgresql}
    documents = render(existing_secret_values)
    assert components_reading(documents, key) == expected


def test_rr13_api_principals_reach_only_the_api(valid_values):
    documents = render(valid_values)
    assert components_reading(documents, "INFRAHUB_SYNC_SERVICE_BEARER_TOKENS") == {
        "api"
    }


def test_rr14_worker_credentials_reach_only_the_worker(valid_values):
    valid_values["worker"] = {
        "credentials": {"INFRAHUB_SYNC_CREDENTIAL_NETBOX_TOKEN": TEST_CREDENTIAL},
        "credentialsExistingSecrets": ["netbox-credentials"],
    }
    documents = render(valid_values)
    readers = {
        component_of(document): env_from_secrets(document)
        for document in workloads(documents)
    }
    assert readers.pop("worker") == {
        f"{FULLNAME}-worker-credentials",
        "netbox-credentials",
    }
    assert all(not names for names in readers.values())


def test_rr14_destination_credential_is_optional_and_reaches_api_and_worker(
    valid_values,
):
    documents = render(valid_values)
    key = "INFRAHUB_SYNC_CREDENTIAL_INFRAHUB_API_TOKEN"
    assert components_reading(documents, key) == {"api", "worker"}
    for component in ("api", "worker"):
        entry = env_value(main_container(workload(documents, component)), key)
        assert entry["valueFrom"]["secretKeyRef"]["optional"] is True


def test_worker_reads_no_credentials_secret_by_default(valid_values):
    worker = main_container(workload(render(valid_values), "worker"))
    assert "envFrom" not in worker


def test_rr15_prefect_server_command_and_settings(valid_values):
    container = main_container(workload(render(valid_values), "prefect-server"))
    assert [*container.get("command", []), *container.get("args", [])] == [
        "uvicorn",
        "--host",
        "0.0.0.0",
        "--port",
        "4200",
        "--factory",
        "infrahub_sync.service.prefect_server:create_prefect_app",
    ]
    assert env_value(container, "PREFECT_UI_ENABLED")["value"] == "false"
    assert env_value(container, "PREFECT_SERVER_ANALYTICS_ENABLED")["value"] == "false"
    auth = env_value(container, "PREFECT_SERVER_API_AUTH_STRING")
    assert (
        auth["valueFrom"]["secretKeyRef"]["key"] == "INFRAHUB_SYNC_PREFECT_AUTH_STRING"
    )


def test_rr16_one_pool_name_for_api_worker_and_bootstrap(valid_values):
    valid_values["settings"] = {"workPool": "custom-pool"}
    documents = render(valid_values)
    worker = main_container(workload(documents, "worker"))
    assert [*worker.get("command", []), *worker.get("args", [])] == [
        "python",
        "-m",
        "infrahub_sync.service.worker",
        "--pool",
        "custom-pool",
    ]
    for component in ("api", "worker", "bootstrap"):
        container = main_container(workload(documents, component))
        assert (
            env_value(container, "INFRAHUB_SYNC_SERVICE_WORK_POOL")["value"]
            == "custom-pool"
        )
    for component in ("api", "worker"):
        gate = pod_spec(workload(documents, component))["initContainers"][0]
        assert "custom-pool" in gate["command"]


@pytest.mark.parametrize(
    ("component", "path", "port"),
    [("api", "/version", 8000), ("prefect-server", "/api/health", 4200)],
)
def test_rr17_probes(valid_values, component, path, port):
    container = main_container(workload(render(valid_values), component))
    for probe in ("readinessProbe", "livenessProbe"):
        http = container[probe]["httpGet"]
        assert http["path"] == path
        assert resolve_port(container, http["port"]) == port


@pytest.mark.parametrize("component", ["api", "worker"])
def test_rr19_api_and_worker_wait_for_the_bootstrap(valid_values, component):
    init = pod_spec(workload(render(valid_values), component))["initContainers"]
    assert [container["name"] for container in init] == ["wait-for-bootstrap"]


def test_rr19_bootstrap_is_a_plain_job_and_no_init_container(valid_values):
    documents = render(valid_values)
    for document in workloads(documents):
        for container in pod_spec(document).get("initContainers", []):
            assert "infrahub_sync.service.bootstrap" not in json.dumps(container), (
                component_of(document)
            )
    job = workload(documents, "bootstrap")
    assert job["kind"] == "Job"
    assert not any(
        key.startswith("helm.sh/hook")
        for key in job["metadata"].get("annotations", {}) or {}
    )
    assert pod_spec(job)["restartPolicy"] == "OnFailure"
    assert job["spec"]["backoffLimit"] == 6
    assert main_container(job)["command"] == [
        "python",
        "-m",
        "infrahub_sync.service.bootstrap",
    ]
    assert [container["name"] for container in pod_spec(job)["initContainers"]] == [
        "wait-for-prefect"
    ]


@pytest.mark.parametrize("fullname_override", ["", "object"])
def test_rr20_endpoint_is_the_release_object_store(valid_values, fullname_override):
    valid_values["fullnameOverride"] = fullname_override
    fullname = fullname_override or FULLNAME
    documents = render(valid_values)
    for component in ("api", "worker", "bootstrap"):
        container = main_container(workload(documents, component))
        endpoint = env_value(container, "INFRAHUB_SYNC_S3_ENDPOINT_URL")["value"]
        assert endpoint == f"http://{fullname}-object-store:9000"
        assert urlparse(endpoint).hostname != "object-store"
    assert find(documents, "Service", f"{fullname}-object-store") is not None


@pytest.mark.parametrize("ca_source", ["", "certificates", "existingConfigMap"])
def test_rr21_ca_only_in_api_worker_and_bootstrap(ca_values, ca_source):
    with_ca = bool(ca_source)
    if not with_ca:
        del ca_values["caCertificates"]
    elif ca_source == "existingConfigMap":
        ca_values["caCertificates"] = {"existingConfigMap": "private-ca"}
    documents = render(ca_values)
    for document in workloads(documents):
        expected = with_ca and component_of(document) in {"api", "worker", "bootstrap"}
        container = main_container(document)
        assert (
            env_value(container, "INFRAHUB_SYNC_CA_DIRECTORY") is not None
        ) == expected
        mounts = {mount["mountPath"] for mount in container.get("volumeMounts", [])}
        assert ("/etc/infrahub-sync/ca" in mounts) == expected


def test_rr22_unset_optional_settings_are_absent(valid_values):
    valid_values["s3"] = {"prefix": "", "region": ""}
    documents = render(valid_values)
    for document in workloads(documents):
        for container in containers(document):
            names = {entry["name"] for entry in container.get("env", [])}
            assert not names & {
                "INFRAHUB_SYNC_PREFECT_UI_URL",
                "INFRAHUB_SYNC_S3_PREFIX",
                "INFRAHUB_SYNC_S3_REGION",
            }
            for entry in container.get("env", []):
                if "value" in entry:
                    assert entry["value"] != "", entry["name"]


def test_rr22_prefect_ui_url_is_passed_when_set(valid_values):
    valid_values["settings"] = {"prefectUiUrl": "https://prefect.example.com"}
    container = main_container(workload(render(valid_values), "api"))
    assert (
        env_value(container, "INFRAHUB_SYNC_PREFECT_UI_URL")["value"]
        == "https://prefect.example.com"
    )


@pytest.mark.parametrize("component", ALL_COMPONENTS)
def test_rr23_no_service_links(valid_values, component):
    assert (
        pod_spec(workload(render(valid_values), component))["enableServiceLinks"]
        is False
    )


@pytest.mark.parametrize(
    ("component", "strategy"),
    [("api", "RollingUpdate"), ("worker", "Recreate"), ("prefect-server", "Recreate")],
)
def test_rr24_update_strategies(valid_values, component, strategy):
    assert (
        workload(render(valid_values), component)["spec"]["strategy"]["type"]
        == strategy
    )


def test_rr25_postgresql_init_script(valid_values):
    documents = render(valid_values)
    statefulset = workload(documents, "postgresql")
    container = main_container(statefulset)
    mount = next(
        mount
        for mount in container["volumeMounts"]
        if mount["mountPath"] == "/docker-entrypoint-initdb.d"
    )
    volume = next(
        volume
        for volume in pod_spec(statefulset)["volumes"]
        if volume["name"] == mount["name"]
    )
    assert volume["configMap"]["defaultMode"] == 0o555
    script = find(documents, "ConfigMap", volume["configMap"]["name"])["data"][
        "databases.sh"
    ]
    assert "$$" not in script
    assert '"${INFRAHUB_SYNC_PRODUCT_ROLE}"' in script
    assert env_value(container, "PGUSER")["value"] == "postgres"
    assert env_value(container, "PGDATABASE")["value"] == "postgres"
    assert env_value(container, "PGHOST") is None
    assert env_value(container, "PGDATA")["value"].startswith(
        "/var/lib/postgresql/data/"
    )


@pytest.mark.parametrize("postgresql", [True, False])
def test_rr26_referenced_variables_are_defined_earlier(
    existing_secret_values, postgresql
):
    existing_secret_values["postgresql"] = {"enabled": postgresql}
    references = 0
    for document in workloads(render(existing_secret_values)):
        for container in containers(document):
            defined: set[str] = set()
            for entry in container.get("env", []):
                for name in REFERENCE.findall(str(entry.get("value", ""))):
                    references += 1
                    assert name in defined, (
                        f"{component_of(document)}/{container['name']}: {entry['name']} uses {name}"
                    )
                defined.add(entry["name"])
    assert references > 0 or not postgresql


# External PostgreSQL and object store (RR-30 to RR-32)

EXTERNAL_ENDPOINT = "https://s3.example.com"
DATABASE_URL_KEYS = {
    "INFRAHUB_SYNC_DATABASE_URL",
    "INFRAHUB_SYNC_PREFECT_DATABASE_URL",
}
POSTGRESQL_PASSWORD_KEYS = {
    "INFRAHUB_SYNC_POSTGRES_ADMIN_PASSWORD",
    "INFRAHUB_SYNC_PRODUCT_PASSWORD",
    "INFRAHUB_SYNC_PREFECT_PASSWORD",
}


@pytest.fixture
def external_postgresql_values(valid_values) -> dict:
    """Valid values for an external PostgreSQL: the two connection strings, no passwords."""
    credentials = valid_values["credentials"]
    for key in ("postgresAdminPassword", "productPassword", "prefectPassword"):
        del credentials[key]
    credentials["databaseUrl"] = (
        f"postgresql://sync:{TEST_CREDENTIAL}@db.example.com/sync"
    )
    credentials["prefectDatabaseUrl"] = (
        f"postgresql+asyncpg://prefect:{TEST_CREDENTIAL}@db.example.com/prefect"
    )
    valid_values["postgresql"] = {"enabled": False}
    return valid_values


def documents_of(documents: list[dict], component: str) -> list[dict]:
    """Return every document labelled with this component."""
    return [
        document
        for document in documents
        if document["metadata"].get("labels", {}).get("app.kubernetes.io/component")
        == component
    ]


def test_rr30_external_postgresql_renders_no_postgresql(external_postgresql_values):
    documents = render(external_postgresql_values)
    assert documents_of(documents, "postgresql") == []
    assert not any(
        "postgresql" in document["metadata"]["name"] for document in documents
    )
    secret = find(documents, "Secret", FULLNAME)
    assert DATABASE_URL_KEYS <= set(secret["data"])
    assert not POSTGRESQL_PASSWORD_KEYS & set(secret["data"])


@pytest.mark.parametrize("existing_secret", [False, True])
def test_rr30_connection_strings_come_from_the_secret(
    external_postgresql_values, existing_secret
):
    if existing_secret:
        external_postgresql_values["credentials"] = {"existingSecret": "infrahub-sync"}
    documents = render(external_postgresql_values)
    secret_name = "infrahub-sync" if existing_secret else FULLNAME
    for component in ("api", "worker", "bootstrap"):
        container = main_container(workload(documents, component))
        reference = env_value(container, "INFRAHUB_SYNC_DATABASE_URL")["valueFrom"][
            "secretKeyRef"
        ]
        assert reference == {"name": secret_name, "key": "INFRAHUB_SYNC_DATABASE_URL"}
    prefect = main_container(workload(documents, "prefect-server"))
    reference = env_value(prefect, "PREFECT_SERVER_DATABASE_CONNECTION_URL")[
        "valueFrom"
    ]["secretKeyRef"]
    assert reference == {
        "name": secret_name,
        "key": "INFRAHUB_SYNC_PREFECT_DATABASE_URL",
    }
    for document in workloads(documents):
        assert not secret_keys(document) & POSTGRESQL_PASSWORD_KEYS, component_of(
            document
        )
        assert "wait-for-postgresql" not in json.dumps(pod_spec(document))


@pytest.mark.parametrize(
    ("addressing_style", "expected"),
    [("", None), ("path", "path"), ("virtual", "virtual")],
)
def test_rr31_external_object_store_uses_the_values_given(
    existing_secret_values, addressing_style, expected
):
    existing_secret_values["objectStore"] = {"enabled": False}
    existing_secret_values["s3"] = {
        "endpointUrl": EXTERNAL_ENDPOINT,
        "addressingStyle": addressing_style,
    }
    documents = render(existing_secret_values)
    assert documents_of(documents, "object-store") == []
    assert not any(
        "object-store" in document["metadata"]["name"] for document in documents
    )
    for component in ("api", "worker", "bootstrap"):
        container = main_container(workload(documents, component))
        assert env_value(container, "INFRAHUB_SYNC_S3_ENDPOINT_URL")["value"] == (
            EXTERNAL_ENDPOINT
        )
        style = env_value(container, "INFRAHUB_SYNC_S3_ADDRESSING_STYLE")
        assert (style and style["value"]) == expected


def test_rr32_both_external_claim_no_volume(existing_secret_values):
    existing_secret_values["postgresql"] = {"enabled": False}
    existing_secret_values["objectStore"] = {"enabled": False}
    existing_secret_values["s3"] = {"endpointUrl": EXTERNAL_ENDPOINT}
    documents = render(existing_secret_values)
    assert {component_of(document) for document in workloads(documents)} == set(
        SYNC_COMPONENTS
    )
    for document in workloads(documents):
        assert not document["spec"].get("volumeClaimTemplates"), component_of(document)
    assert all(document["kind"] != "PersistentVolumeClaim" for document in documents)


def test_rr42_external_object_store_without_endpoint_is_refused(existing_secret_values):
    existing_secret_values["objectStore"] = {"enabled": False}
    error = render(existing_secret_values, expect_failure=True)
    assert "s3.endpointUrl" in error
    assert "objectStore.enabled" in error


@pytest.mark.parametrize("value", ["databaseUrl", "prefectDatabaseUrl"])
def test_rr44_external_postgresql_without_connection_string_is_refused(
    external_postgresql_values, value
):
    del external_postgresql_values["credentials"][value]
    error = render(external_postgresql_values, expect_failure=True)
    assert f"credentials.{value}" in error
    assert "postgresql.enabled" in error


def test_manifest_field_types(valid_values):
    """Stand-in for a schema check: env values are strings and ports are integers."""
    documents = render(valid_values)
    for document in workloads(documents):
        for container in containers(document):
            for entry in container.get("env", []):
                assert isinstance(entry.get("value", ""), str), entry["name"]
            for port in container.get("ports", []):
                assert isinstance(port["containerPort"], int)
    for document in documents:
        if document["kind"] == "Service":
            for port in document["spec"]["ports"]:
                assert isinstance(port["port"], int)


def test_notes_hold_no_credential(valid_values):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(valid_values, handle)
        values_file = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "helm",
                "install",
                "sync",
                str(CHART),
                "-f",
                str(values_file),
                "--dry-run=client",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        values_file.unlink()
    assert result.returncode == 0, result.stderr
    notes = result.stdout.split("NOTES:", 1)[1]
    assert "port-forward service/sync-infrahub-sync-api" in notes
    assert "infrahub-sync whoami" in notes
    assert "kubectl" in notes and "wait --for=condition=complete" in notes
    assert TEST_CREDENTIAL not in notes
    assert '"enableServiceLinks":false' in notes
    assert base64.b64encode(TEST_CREDENTIAL.encode()).decode() not in notes


def test_postgresql_wait_names_a_role(valid_values):
    """The Sync pod's uid has no passwd entry in the PostgreSQL image, so pg_isready needs -U."""
    prefect = workload(render(valid_values), "prefect-server")
    wait = next(
        container
        for container in pod_spec(prefect)["initContainers"]
        if container["name"] == "wait-for-postgresql"
    )
    assert '-U "$role"' in wait["command"][2]
    assert wait["command"][-1] == "postgres"


# Bootstrap Job name (RR-34)


def bootstrap_job_name(values: dict, extra_args: tuple[str, ...] = ()) -> str:
    """Return the name of the bootstrap Job that the chart renders for `values`."""
    return workload(render(values, extra_args=extra_args), "bootstrap")["metadata"][
        "name"
    ]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("image", "tag"), "9.9.9"),
        (("s3", "prefix"), "another-prefix"),
        (("credentials", "s3SecretKey"), "another-" * 3),
    ],
    ids=["image.tag", "s3.prefix", "credentials.s3SecretKey"],
)
def test_rr34_job_name_changes_with_what_the_bootstrap_reads(valid_values, path, value):
    before = bootstrap_job_name(valid_values)
    changed = json.loads(json.dumps(valid_values))
    changed.setdefault(path[0], {})[path[1]] = value
    after = bootstrap_job_name(changed)
    assert re.fullmatch(rf"{FULLNAME}-bootstrap-[0-9a-f]{{8}}", after)
    assert after != before


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("api", "resources"), {"requests": {"cpu": "250m", "memory": "256Mi"}}),
        (("settings", "runAdmissionTtlSeconds"), 301),
    ],
    ids=["api.resources", "settings.runAdmissionTtlSeconds"],
)
def test_rr34_job_name_ignores_what_the_bootstrap_does_not_read(
    valid_values, path, value
):
    before = bootstrap_job_name(valid_values)
    changed = json.loads(json.dumps(valid_values))
    changed.setdefault(path[0], {})[path[1]] = value
    assert bootstrap_job_name(changed) == before


def test_rr34_job_name_ignores_the_release_revision(valid_values):
    """`helm template` has no flag that sets the revision, so the test checks both halves.

    No template reads `.Release.Revision`, and a render as an upgrade (`--is-upgrade`, which
    is what a later revision is) gives the same name as a render as an install.
    """
    for template in (CHART / "templates").iterdir():
        assert ".Release.Revision" not in template.read_text(), template.name
    assert bootstrap_job_name(valid_values, ("--is-upgrade",)) == bootstrap_job_name(
        valid_values
    )


# Routes to the Sync API (User Story 4)

ROUTE_KINDS = {"Ingress", "Gateway", "HTTPRoute"}
API_SERVICE = f"{FULLNAME}-api"


def api_service_port(documents: list[dict]) -> int:
    """Return the port of the rendered Sync API Service."""
    service = find(documents, "Service", API_SERVICE)
    assert service is not None
    return service["spec"]["ports"][0]["port"]


def ingress_backends(ingress: dict) -> set[tuple[str, int]]:
    """Return every (Service name, port) that the Ingress routes to."""
    backends = set()
    for rule in ingress["spec"]["rules"]:
        for path in rule["http"]["paths"]:
            service = path["backend"]["service"]
            backends.add((service["name"], service["port"]["number"]))
    return backends


def route_backends(route: dict) -> set[tuple[str, int]]:
    """Return every (Service name, port) that the HTTPRoute routes to."""
    return {
        (backend["name"], backend["port"])
        for rule in route["spec"]["rules"]
        for backend in rule["backendRefs"]
    }


def of_kind(documents: list[dict], kind: str) -> list[dict]:
    """Return every document of this kind."""
    return [document for document in documents if document["kind"] == kind]


def test_rr18_services_are_cluster_ip_and_no_route_by_default(valid_values):
    documents = render(valid_values)
    services = of_kind(documents, "Service")
    assert services
    assert {service["spec"].get("type") for service in services} == {"ClusterIP"}
    assert [d["kind"] for d in documents if d["kind"] in ROUTE_KINDS] == []


@pytest.mark.parametrize("api_port", [None, 9000])
def test_rr33_ingress_routes_only_to_the_api(valid_values, api_port):
    valid_values["ingress"] = {
        "enabled": True,
        "hostname": "sync.example.com",
        "extraHosts": [{"hostname": "sync.example.org", "path": "/sync"}],
    }
    if api_port is not None:
        valid_values["api"] = {"service": {"port": api_port}}
    documents = render(valid_values)
    ingresses = of_kind(documents, "Ingress")
    assert len(ingresses) == 1
    expected = {(API_SERVICE, api_service_port(documents))}
    assert ingress_backends(ingresses[0]) == expected
    assert of_kind(documents, "HTTPRoute") == []
    assert of_kind(documents, "Gateway") == []


@pytest.mark.parametrize("api_port", [None, 9000])
def test_rr33_httproute_routes_only_to_the_api(valid_values, api_port):
    valid_values["gatewayApi"] = {
        "enabled": True,
        "httpRoute": {"parentRefs": [{"name": "shared-gateway", "namespace": "net"}]},
    }
    if api_port is not None:
        valid_values["api"] = {"service": {"port": api_port}}
    documents = render(valid_values)
    routes = of_kind(documents, "HTTPRoute")
    assert len(routes) == 1
    assert route_backends(routes[0]) == {(API_SERVICE, api_service_port(documents))}
    assert routes[0]["spec"]["parentRefs"] == [
        {"name": "shared-gateway", "namespace": "net"}
    ]
    assert routes[0]["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/"
    assert of_kind(documents, "Gateway") == []
    assert of_kind(documents, "Ingress") == []


def test_rr33_created_gateway_is_the_route_parent(valid_values):
    valid_values["gatewayApi"] = {
        "enabled": True,
        "gateway": {
            "enabled": True,
            "className": "example",
            "listeners": [{"name": "http", "port": 80, "protocol": "HTTP"}],
        },
    }
    documents = render(valid_values)
    gateways = of_kind(documents, "Gateway")
    routes = of_kind(documents, "HTTPRoute")
    assert len(gateways) == 1
    assert len(routes) == 1
    assert gateways[0]["spec"]["gatewayClassName"] == "example"
    assert routes[0]["spec"]["parentRefs"] == [
        {"name": gateways[0]["metadata"]["name"]}
    ]
    assert route_backends(routes[0]) == {(API_SERVICE, api_service_port(documents))}


@pytest.mark.parametrize(
    ("values", "names"),
    [
        (
            {
                "ingress": {"enabled": True},
                "gatewayApi": {
                    "enabled": True,
                    "httpRoute": {"parentRefs": [{"name": "shared-gateway"}]},
                },
            },
            ("ingress.enabled", "gatewayApi.enabled"),
        ),
        ({"gatewayApi": {"enabled": True}}, ("gatewayApi.httpRoute.parentRefs",)),
        (
            {"gatewayApi": {"enabled": True, "gateway": {"enabled": True}}},
            ("gatewayApi.gateway.className",),
        ),
    ],
    ids=["ingress-and-gateway-api", "no-parent", "gateway-without-class"],
)
def test_bad_route_values_are_refused(existing_secret_values, values, names):
    existing_secret_values.update(values)
    error = render(existing_secret_values, expect_failure=True)
    for name in names:
        assert name in error
