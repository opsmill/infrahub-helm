"""Configuration and observations for the isolated Neo4j HA test deployment."""

import csv
import io
import os
import subprocess
from pathlib import Path

import yaml

NAMESPACE = "infrahub-ha"
MEMBERS = ("neo4j-ha-1", "neo4j-ha-2", "neo4j-ha-3")


def image_overrides(environ=None) -> tuple[dict, dict]:
    """Use YAML values to preserve image references without Helm --set parsing.

    Prefect runs Infrahub's custom entrypoint, so its override must be an
    Infrahub Enterprise image containing the candidate Prefect dependency.
    """
    environ = os.environ if environ is None else environ
    neo4j = {}
    enterprise = {}
    if image := environ.get("NEO4J_DOCKER_IMAGE"):
        neo4j = {"image": {"customImage": image}}
    if image := environ.get("PREFECT_DOCKER_IMAGE"):
        repository, separator, tag = image.rpartition(":")
        if not separator or not repository or not tag or "/" in tag or "@" in image:
            raise ValueError(
                "PREFECT_DOCKER_IMAGE must be an explicit repository:tag (no digest)"
            )
        enterprise = {
            "infrahub": {
                "prefect-server": {
                    "global": {
                        "prefect": {
                            "image": {
                                "repository": repository,
                                "prefectTag": tag,
                            }
                        }
                    }
                }
            }
        }
    return neo4j, enterprise


def neo4j_dependency(staged_infrahub: Path) -> Path:
    """Select exactly the chart pinned by Chart.yaml, including upgrade branches."""
    chart = yaml.safe_load((staged_infrahub / "Chart.yaml").read_text())
    dependency = next(item for item in chart["dependencies"] if item["name"] == "neo4j")
    path = staged_infrahub / "charts" / f"neo4j-{dependency['version']}.tgz"
    if not path.is_file():
        raise FileNotFoundError(f"Staged Neo4j dependency missing: {path}")
    return path


def kubectl(kubeconfig: str, *args: str, input: str | None = None) -> str:
    return subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE, *args],
        input=input,
        capture_output=True,
        text=True,
        check=True,
        timeout=360,
    ).stdout


def database_topology(kubeconfig: str, member: str = MEMBERS[0]) -> list[dict]:
    """Ask Neo4j about database members, not just Kubernetes pod readiness."""
    output = kubectl(
        kubeconfig,
        "exec",
        f"{member}-0",
        "--",
        "cypher-shell",
        "-u",
        "neo4j",
        "-p",
        "admin",
        "-d",
        "system",
        "--format",
        "plain",
        "SHOW DATABASE neo4j YIELD address, role, currentStatus, writer "
        "RETURN address, role, currentStatus, writer",
    )
    return list(csv.DictReader(io.StringIO(output), skipinitialspace=True))


def writer_member(rows: list[dict]) -> str:
    writers = [row for row in rows if row["writer"].lower() == "true"]
    assert len(writers) == 1, f"Expected one database writer, got {writers}"
    address = writers[0]["address"]
    matches = [
        member for member in MEMBERS if address.startswith((member + ".", member + ":"))
    ]
    assert (
        len(matches) == 1
    ), f"Writer address does not identify a test member: {address}"
    return matches[0]


def topology_ready(
    rows: list[dict], online_members: int, absent: str | None = None
) -> bool:
    online = [
        row
        for row in rows
        if row["role"] == "primary" and row["currentStatus"] == "online"
    ]
    if (
        len(online) != online_members
        or sum(row["writer"].lower() == "true" for row in online) != 1
    ):
        return False
    # Do not accept stale topology that still reports the removed member online.
    if absent and any(
        row["address"].startswith((absent + ".", absent + ":")) for row in online
    ):
        return False
    return True


def recovery_probe(
    kubeconfig: str, member: str, ids: list[str], *, write: bool = False
) -> list[dict]:
    """Small raw database markers, separate from the application smoke writes.

    A direct Bolt read on the returning member must see both markers; a routed
    API read alone could be satisfied entirely by the surviving members.
    """
    import json
    import uuid

    for probe in ids:
        uuid.UUID(probe)  # Only internally generated UUIDs enter the Cypher literal.
    if write:
        assert len(ids) == 1
        query = f'MERGE (:HelmHAProbe {{id: "{ids[0]}"}}) RETURN 1 AS count'
    else:
        query = f"MATCH (p:HelmHAProbe) WHERE p.id IN {json.dumps(ids)} RETURN count(DISTINCT p.id) AS count"
    output = kubectl(
        kubeconfig,
        "exec",
        f"{member}-0",
        "--",
        "cypher-shell",
        "-a",
        "bolt://localhost:7687",
        "-u",
        "neo4j",
        "-p",
        "admin",
        "-d",
        "neo4j",
        "--access-mode",
        "write" if write else "read",
        "--format",
        "plain",
        query,
    )
    return list(csv.DictReader(io.StringIO(output), skipinitialspace=True))
