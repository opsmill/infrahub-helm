"""Render tests of the infrahub-sync chart.

Each test runs `helm template` on the local chart, with no cluster, and checks the rendered
manifests against the properties of the chart's contract.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "charts" / "infrahub-sync"

# Placeholder credentials for render tests. They are never used against a service.
TEST_CREDENTIAL = "test-" * 4


def render(values: dict, *, expect_failure: bool = False) -> list[dict] | str:
    """Render the chart with `values`.

    Returns the parsed documents, empty ones left out. With `expect_failure`, the render must
    fail and the error text is returned instead.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(values, handle)
        values_file = Path(handle.name)
    try:
        result = subprocess.run(
            ["helm", "template", "sync", str(CHART), "-f", str(values_file)],
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


def test_endpoint_with_bundled_object_store_is_refused(existing_secret_values):
    existing_secret_values["s3"] = {"endpointUrl": "https://s3.example.com"}
    error = render(existing_secret_values, expect_failure=True)
    assert "s3.endpointUrl" in error
    assert "objectStore.enabled" in error
