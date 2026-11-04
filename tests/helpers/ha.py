"""Configuration and observations for the isolated Neo4j HA test deployment."""

import csv
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path
from typing import NamedTuple

import yaml

NAMESPACE = "infrahub-ha"
MEMBERS = ("neo4j-ha-1", "neo4j-ha-2", "neo4j-ha-3")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(\d+))?")


class Neo4jUpgrade(NamedTuple):
    """Charts and Neo4j versions of the members before and after a rolling upgrade."""

    source_chart: Path
    target_chart: Path
    source_version: str
    target_version: str


def _split_image(variable: str, image: str) -> tuple[str, str]:
    repository, separator, tag = image.rpartition(":")
    if not separator or not repository or not tag or "/" in tag or "@" in image:
        raise ValueError(f"{variable} must be an explicit repository:tag (no digest)")
    return repository, tag


def _merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def image_overrides(environ=None) -> tuple[dict, dict]:
    """Use YAML values to preserve image references without Helm --set parsing.

    Prefect runs Infrahub's custom entrypoint, so its override must be an
    Infrahub Enterprise image containing the candidate Prefect dependency.
    The Infrahub override must name its registry host, because the chart sets
    the registry apart from the repository and the tag.
    """
    environ = os.environ if environ is None else environ
    neo4j = {}
    enterprise: dict = {}
    if image := environ.get("NEO4J_DOCKER_IMAGE"):
        neo4j = {"image": {"customImage": image}}
    if image := environ.get("PREFECT_DOCKER_IMAGE"):
        repository, tag = _split_image("PREFECT_DOCKER_IMAGE", image)
        _merge(
            enterprise,
            {
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
            },
        )
    if image := environ.get("INFRAHUB_DOCKER_IMAGE"):
        repository, tag = _split_image("INFRAHUB_DOCKER_IMAGE", image)
        registry, _, path = repository.partition("/")
        if not path or not ("." in registry or ":" in registry or registry == "localhost"):
            raise ValueError(
                "INFRAHUB_DOCKER_IMAGE must start with a registry host, "
                "for example registry.opsmill.io/opsmill/infrahub-enterprise:<tag>"
            )
        _merge(
            enterprise,
            {
                "infrahub": {
                    "global": {"infrahubRepository": path, "infrahubTag": tag},
                    "infrahubServer": {"infrahubServer": {"imageRegistry": registry}},
                    "infrahubTaskWorker": {
                        "infrahubTaskWorker": {"imageRegistry": registry}
                    },
                }
            },
        )
    return neo4j, enterprise


def _neo4j_pin(staged_infrahub: Path) -> dict:
    chart = yaml.safe_load((staged_infrahub / "Chart.yaml").read_text())
    return next(item for item in chart["dependencies"] if item["name"] == "neo4j")


def neo4j_dependency(staged_infrahub: Path) -> Path:
    """Select exactly the chart pinned by Chart.yaml, including upgrade branches."""
    path = staged_infrahub / "charts" / f"neo4j-{_neo4j_pin(staged_infrahub)['version']}.tgz"
    if not path.is_file():
        raise FileNotFoundError(f"Staged Neo4j dependency missing: {path}")
    return path


def pull_neo4j_chart(staged_infrahub: Path, version: str, destination: Path) -> Path:
    """Fetch another version of the Neo4j chart from the repository of the pin."""
    repository = _neo4j_pin(staged_infrahub)["repository"]
    subprocess.run(
        [
            "helm",
            "pull",
            "neo4j",
            "--repo",
            repository,
            "--version",
            version,
            "--destination",
            str(destination),
        ],
        check=True,
        timeout=300,
    )
    path = destination / f"neo4j-{version}.tgz"
    if not path.is_file():
        raise FileNotFoundError(f"helm pull did not write {path}")
    return path


def chart_metadata(chart: Path) -> dict:
    """Read Chart.yaml of a packaged chart without extracting the archive."""
    with tarfile.open(chart) as archive:
        member = next(
            (
                item
                for item in archive.getmembers()
                if item.isfile()
                and item.name.count("/") == 1
                and item.name.endswith("/Chart.yaml")
            ),
            None,
        )
        if member is None:
            raise FileNotFoundError(f"No top-level Chart.yaml in {chart}")
        content = archive.extractfile(member)
        assert content is not None
        return yaml.safe_load(content.read())


def version_key(version: str) -> tuple[int, ...]:
    """Compare as numbers, so chart 2026.5.0 equals Neo4j 2026.05.0 and 2026.10 follows 2026.9."""
    match = _VERSION.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Not a Neo4j or Neo4j chart version: {version!r}")
    return tuple(int(part or 0) for part in match.groups())


def upgrade_from_chart(environ=None) -> str | None:
    """Return the Neo4j chart version the members run before a rolling upgrade, if any.

    A Neo4j image override would run the same image before and after the
    upgrade, so the two settings are rejected together.
    """
    environ = os.environ if environ is None else environ
    version = (environ.get("NEO4J_UPGRADE_FROM_CHART") or "").strip()
    if not version:
        return None
    if not _VERSION.fullmatch(version):
        raise ValueError(
            "NEO4J_UPGRADE_FROM_CHART must be a Neo4j chart version such as "
            f"2026.5.0, got {version!r}"
        )
    if environ.get("NEO4J_DOCKER_IMAGE"):
        raise ValueError(
            "NEO4J_UPGRADE_FROM_CHART cannot be combined with NEO4J_DOCKER_IMAGE: "
            "the image override would run the same Neo4j before and after the upgrade"
        )
    return version


def upgrade_required(source: str, target: str) -> bool:
    """Tell whether members on Neo4j `source` need an upgrade to run `target`.

    Raises:
        ValueError: `source` is newer than `target`; the test does not cover downgrades.
    """
    if version_key(source) > version_key(target):
        raise ValueError(f"Neo4j {source} to {target} is a downgrade, not an upgrade")
    return version_key(source) < version_key(target)


def next_upgrade(remaining: list[str], writer: str) -> str:
    """Choose a member that does not host the writer, so the writer is upgraded last.

    The writer can move after each restart, so the caller asks again before every step.
    """
    if not remaining:
        raise ValueError("No member left to upgrade")
    return next((member for member in remaining if member != writer), remaining[0])


def neo4j_release(
    kubeconfig: str,
    member: str,
    chart: Path,
    values_files: list[Path],
    *,
    install: bool = True,
) -> None:
    """Install or upgrade one member release, always with the same values files."""
    command = ["helm", "upgrade", *(["--install"] if install else [])]
    command += [member, str(chart), "-n", NAMESPACE, "--kubeconfig", kubeconfig]
    for values_file in values_files:
        command += ["-f", str(values_file)]
    subprocess.run([*command, "--timeout", "15m"], check=True)


def kubectl(kubeconfig: str, *args: str, input: str | None = None) -> str:
    return subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE, *args],
        input=input,
        capture_output=True,
        text=True,
        check=True,
        timeout=360,
    ).stdout


def member_pod(kubeconfig: str, member: str) -> dict:
    return json.loads(kubectl(kubeconfig, "get", "pod", f"{member}-0", "-o", "json"))


def data_claim(kubeconfig: str, pod: dict) -> tuple[str, str]:
    """Return the name and UID of the PersistentVolumeClaim behind a member's data volume."""
    claim = next(
        volume["persistentVolumeClaim"]["claimName"]
        for volume in pod["spec"]["volumes"]
        if volume["name"] == "data"
    )
    uid = json.loads(kubectl(kubeconfig, "get", "pvc", claim, "-o", "json"))["metadata"][
        "uid"
    ]
    return claim, uid


def pod_summary(kubeconfig: str) -> str:
    """List every pod with its node, container images and restart counts."""
    return kubectl(
        kubeconfig,
        "get",
        "pods",
        "-o",
        "custom-columns=POD:.metadata.name,NODE:.spec.nodeName,"
        "IMAGES:.spec.containers[*].image,"
        "RESTARTS:.status.containerStatuses[*].restartCount",
    )


def neo4j_version(kubeconfig: str, member: str) -> str:
    """Ask one member for its Neo4j version over a direct Bolt connection.

    The bolt:// scheme skips routing, so the answer cannot come from another member,
    and the query runs on the neo4j database because the system database rejects
    procedure calls.
    """
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
        "read",
        "--format",
        "plain",
        "CALL dbms.components() YIELD name, versions "
        "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version",
    )
    rows = list(csv.DictReader(io.StringIO(output), skipinitialspace=True))
    assert len(rows) == 1, f"Expected one Neo4j Kernel component on {member}: {output}"
    return rows[0]["version"]


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
