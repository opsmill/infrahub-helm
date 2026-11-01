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
