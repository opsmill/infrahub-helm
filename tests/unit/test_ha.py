import subprocess
from pathlib import Path

import pytest
import yaml

from tests.helpers.ha import image_overrides, neo4j_dependency


def test_image_overrides_preserve_chart_defaults():
    assert image_overrides({}) == ({}, {})


def test_candidate_images_are_independent():
    neo4j, enterprise = image_overrides(
        {"NEO4J_DOCKER_IMAGE": "registry.example/neo4j@sha256:abc"}
    )
    assert neo4j["image"]["customImage"] == "registry.example/neo4j@sha256:abc"
    assert enterprise == {}
    neo4j, enterprise = image_overrides(
        {"PREFECT_DOCKER_IMAGE": "localhost:5000/enterprise:candidate"}
    )
    assert neo4j == {}
    image = enterprise["infrahub"]["prefect-server"]["global"]["prefect"]["image"]
    assert image == {
        "repository": "localhost:5000/enterprise",
        "prefectTag": "candidate",
    }


@pytest.mark.parametrize(
    "image", ["enterprise", "localhost:5000/enterprise", "repo@sha256:abc", "repo:"]
)
def test_prefect_requires_explicit_tag(image):
    with pytest.raises(ValueError):
        image_overrides({"PREFECT_DOCKER_IMAGE": image})


def test_infrahub_image_sets_registry_repository_and_tag():
    neo4j, enterprise = image_overrides(
        {
            "INFRAHUB_DOCKER_IMAGE": "registry.opsmill.io/opsmill/infrahub-enterprise:dev-1234567"
        }
    )
    assert neo4j == {}
    assert enterprise == {
        "infrahub": {
            "global": {
                "infrahubRepository": "opsmill/infrahub-enterprise",
                "infrahubTag": "dev-1234567",
            },
            "infrahubServer": {"infrahubServer": {"imageRegistry": "registry.opsmill.io"}},
            "infrahubTaskWorker": {
                "infrahubTaskWorker": {"imageRegistry": "registry.opsmill.io"}
            },
        }
    }


def test_infrahub_and_prefect_images_combine():
    image = "localhost:5000/opsmill/infrahub-enterprise:candidate"
    _, enterprise = image_overrides(
        {"INFRAHUB_DOCKER_IMAGE": image, "PREFECT_DOCKER_IMAGE": image}
    )
    infrahub = enterprise["infrahub"]
    assert infrahub["global"]["infrahubTag"] == "candidate"
    assert infrahub["infrahubServer"]["infrahubServer"]["imageRegistry"] == "localhost:5000"
    prefect = infrahub["prefect-server"]["global"]["prefect"]["image"]
    assert prefect == {
        "repository": "localhost:5000/opsmill/infrahub-enterprise",
        "prefectTag": "candidate",
    }


@pytest.mark.parametrize(
    "image",
    [
        "opsmill/infrahub-enterprise:dev-1234567",
        "infrahub-enterprise:dev-1234567",
        "registry.opsmill.io/opsmill/infrahub-enterprise",
        "registry.opsmill.io/opsmill/infrahub-enterprise@sha256:abc",
    ],
)
def test_infrahub_image_requires_registry_and_tag(image):
    with pytest.raises(ValueError):
        image_overrides({"INFRAHUB_DOCKER_IMAGE": image})


def test_chart_selection_uses_pin_not_stale_archive(tmp_path: Path):
    (tmp_path / "charts").mkdir()
    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump(
            {
                "dependencies": [{"name": "neo4j", "version": "2026.5.0"}],
            }
        )
    )
    (tmp_path / "charts/neo4j-2025.10.1.tgz").touch()
    with pytest.raises(FileNotFoundError):
        neo4j_dependency(tmp_path)
    expected = tmp_path / "charts/neo4j-2026.5.0.tgz"
    expected.touch()
    assert neo4j_dependency(tmp_path) == expected


def test_topology_rejects_stale_removed_member_and_no_writer():
    from tests.helpers.ha import topology_ready, writer_member

    rows = [
        {
            "address": f"neo4j-ha-{index}.infrahub-ha.svc.cluster.local:7687",
            "role": "primary",
            "currentStatus": "online",
            "writer": "TRUE" if index == 1 else "FALSE",
        }
        for index in range(1, 4)
    ]
    assert topology_ready(rows, 3)
    assert writer_member(rows) == "neo4j-ha-1"
    assert not topology_ready(rows, 2, "neo4j-ha-1")
    rows[0]["currentStatus"] = "unknown"
    rows[0]["writer"] = "false"
    assert not topology_ready(rows, 2, "neo4j-ha-1")
    rows[1]["writer"] = "true"
    assert topology_ready(rows, 2, "neo4j-ha-1")
    assert writer_member(rows) == "neo4j-ha-2"
    assert not topology_ready(rows, 2, "neo4j-ha-2")


def test_upgrade_mode_is_off_without_a_chart_version():
    from tests.helpers.ha import upgrade_from_chart

    assert upgrade_from_chart({}) is None
    assert upgrade_from_chart({"NEO4J_UPGRADE_FROM_CHART": " "}) is None


@pytest.mark.parametrize("version", ["2026.5.0", " 2026.5.0 ", "2026.1.3-1"])
def test_upgrade_mode_reads_the_chart_version(version):
    from tests.helpers.ha import upgrade_from_chart

    assert upgrade_from_chart({"NEO4J_UPGRADE_FROM_CHART": version}) == version.strip()


@pytest.mark.parametrize(
    "version", ["latest", "2026.5", "v2026.5.0", "2026.05.0-enterprise", "neo4j-2026.5.0"]
)
def test_upgrade_mode_rejects_a_value_that_is_not_a_chart_version(version):
    from tests.helpers.ha import upgrade_from_chart

    with pytest.raises(ValueError):
        upgrade_from_chart({"NEO4J_UPGRADE_FROM_CHART": version})


def test_upgrade_mode_rejects_a_neo4j_image_override():
    from tests.helpers.ha import upgrade_from_chart

    with pytest.raises(ValueError):
        upgrade_from_chart(
            {
                "NEO4J_UPGRADE_FROM_CHART": "2026.5.0",
                "NEO4J_DOCKER_IMAGE": "neo4j:2026.10.1-enterprise",
            }
        )


def test_chart_and_neo4j_versions_compare_as_numbers():
    from tests.helpers.ha import version_key

    assert version_key("2026.5.0") == version_key("2026.05.0")
    assert version_key("2026.10.1") > version_key("2026.9.0")
    assert version_key("2026.1.3-1") > version_key("2026.1.3")
    with pytest.raises(ValueError):
        version_key("2026.10")


def test_upgrade_is_required_only_for_a_newer_target():
    from tests.helpers.ha import upgrade_required

    assert upgrade_required("2026.05.0", "2026.10.1")
    assert not upgrade_required("2026.10.1", "2026.10.1")
    with pytest.raises(ValueError):
        upgrade_required("2026.10.1", "2026.05.0")


def test_writer_is_upgraded_last():
    from tests.helpers.ha import next_upgrade

    assert next_upgrade(["neo4j-ha-1", "neo4j-ha-2", "neo4j-ha-3"], "neo4j-ha-1") == "neo4j-ha-2"
    assert next_upgrade(["neo4j-ha-1", "neo4j-ha-3"], "neo4j-ha-1") == "neo4j-ha-3"
    assert next_upgrade(["neo4j-ha-1"], "neo4j-ha-1") == "neo4j-ha-1"
    # The writer moved to a member that is already upgraded.
    assert next_upgrade(["neo4j-ha-1", "neo4j-ha-3"], "neo4j-ha-2") == "neo4j-ha-1"
    with pytest.raises(ValueError):
        next_upgrade([], "neo4j-ha-1")


def test_chart_metadata_reads_the_top_level_chart(tmp_path: Path):
    import io
    import tarfile

    from tests.helpers.ha import chart_metadata

    def add(archive, name, data):
        content = yaml.safe_dump(data).encode()
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    chart = tmp_path / "neo4j-2026.5.0.tgz"
    with tarfile.open(chart, "w:gz") as archive:
        add(archive, "neo4j/charts/sub/Chart.yaml", {"appVersion": "1.0.0"})
        add(archive, "neo4j/Chart.yaml", {"version": "2026.5.0", "appVersion": "2026.05.0"})
    assert chart_metadata(chart) == {"version": "2026.5.0", "appVersion": "2026.05.0"}

    empty = tmp_path / "empty.tgz"
    with tarfile.open(empty, "w:gz") as archive:
        add(archive, "neo4j/values.yaml", {})
    with pytest.raises(FileNotFoundError):
        chart_metadata(empty)


def test_command_error_describes_failures_and_timeouts():
    from tests.helpers.ha import RETRYABLE_ERRORS, command_error

    failed = subprocess.CalledProcessError(1, ["kubectl"], stderr="connection refused")
    assert command_error(failed) == "connection refused"
    assert "returned non-zero exit status 1" in command_error(
        subprocess.CalledProcessError(1, ["kubectl"])
    )
    timed_out = subprocess.TimeoutExpired(["kubectl"], 60, stderr=b"partial")
    assert isinstance(timed_out, RETRYABLE_ERRORS)
    assert "timed out after 60 seconds" in command_error(timed_out)
