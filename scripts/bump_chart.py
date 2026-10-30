#!/usr/bin/env python3
"""Change chart versions and pins the way AGENTS.md describes, for the release workflows.

Subcommands:

    app-version <chart> <app-version> [--notes-url URL]
        Set `appVersion` of charts/<chart>, bump the chart `version` and add a
        `changed` news fragment. The chart gets a minor bump when the major or
        minor part of `appVersion` changes, and a patch bump otherwise. Prints
        the new chart version.

    repin <chart> <version>
        Point every chart in this repository that pins <chart> from the OpsMill
        registry at <version>, update the dependency row of its README.md and
        add a `changed` news fragment to it. Charts that pin those charts get a
        fragment too, since the change reaches them through that pin. The
        chart versions are not bumped: a pull request does not have to bump
        them, and the Infrahub release process sets the versions of `infrahub`
        and `infrahub-enterprise`. Prints the charts it changed.

Chart.yaml files are edited as text, not through a YAML library, so that their
comments and layout are kept.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHARTS = Path(__file__).resolve().parent.parent / "charts"
REGISTRY = "oci://registry.opsmill.io/opsmill/chart"
RELEASES = "https://github.com/opsmill/infrahub-helm/releases/tag"


def _semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip().strip('"'))
    if not match:
        raise SystemExit(f"Not a final MAJOR.MINOR.PATCH version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _replace_once(text: str, pattern: str, repl: str, what: str) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not find {what}")
    return new


def _fragment(chart: str, name: str, text: str) -> None:
    # towncrier rejects dots in the fragment name: they separate name and type.
    path = CHARTS / chart / "changelog" / f"+{name.replace('.', '-')}.changed.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text + "\n")


def app_version(chart: str, new_app: str, notes_url: str | None) -> None:
    chart_yaml = CHARTS / chart / "Chart.yaml"
    text = chart_yaml.read_text()
    old_app = re.search(r'^appVersion:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    old_version = re.search(r"^version:\s*([^\s]+)\s*$", text, re.MULTILINE)
    if not old_app or not old_version:
        raise SystemExit(f"{chart_yaml} has no appVersion or version")
    if old_app.group(1) == new_app:
        raise SystemExit(f"{chart} already has appVersion {new_app}")

    if _semver(new_app) < _semver(old_app.group(1)):
        raise SystemExit(f"{chart} has appVersion {old_app.group(1)}, which is newer than {new_app}")
    old_major, old_minor, _ = _semver(old_app.group(1))
    new_major, new_minor, _ = _semver(new_app)
    major, minor, patch = _semver(old_version.group(1))
    if (new_major, new_minor) != (old_major, old_minor):
        version = f"{major}.{minor + 1}.0"
    else:
        version = f"{major}.{minor}.{patch + 1}"

    text = _replace_once(text, r"^appVersion:.*$", f'appVersion: "{new_app}"', "appVersion")
    text = _replace_once(text, r"^version:.*$", f"version: {version}", "version")
    chart_yaml.write_text(text)

    sentence = f"Bumped the `{chart}` image to `{new_app}`."
    if notes_url:
        sentence += f" See the [{chart} {new_app.lstrip('v')} release notes]({notes_url})."
    _fragment(chart, f"{chart}-{new_app}", sentence)
    print(version)


def _pinning_charts(dependency: str) -> list[str]:
    pattern = re.compile(
        rf"^\s*- name: {re.escape(dependency)}\s*\n\s*version: .*\n\s*repository: \"?{re.escape(REGISTRY)}\"?",
        re.MULTILINE,
    )
    return sorted(p.parent.name for p in CHARTS.glob("*/Chart.yaml") if pattern.search(p.read_text()))


def repin(chart: str, version: str) -> None:
    _semver(version)
    url = f"{RELEASES}/{chart}-{version}"
    parents = _pinning_charts(chart)
    if not parents:
        raise SystemExit(f"No chart pins {chart} from {REGISTRY}")

    changed: list[str] = []
    for parent in parents:
        chart_yaml = CHARTS / parent / "Chart.yaml"
        chart_yaml.write_text(
            _replace_once(
                chart_yaml.read_text(),
                rf"^(\s*- name: {re.escape(chart)}\s*\n\s*version: ).*$",
                rf'\g<1>"{version}"',
                f"the {chart} dependency in {chart_yaml}",
            )
        )
        readme = CHARTS / parent / "README.md"
        if readme.exists():
            readme.write_text(
                re.sub(
                    rf"^\| {re.escape(REGISTRY)} \| {re.escape(chart)} \| [^|]+ \|$",
                    f"| {REGISTRY} | {chart} | {version} |",
                    readme.read_text(),
                    flags=re.MULTILINE,
                )
            )
        _fragment(parent, f"{chart}-{version}", f"Bumped the bundled `{chart}` subchart to `{version}`. See the [{chart} {version} release]({url}).")
        changed.append(parent)

        # The change reaches the charts that pin `parent` once `parent` is released.
        pending = _pinning_charts(parent)
        while pending:
            grandparent = pending.pop()
            if grandparent in changed:
                continue
            _fragment(
                grandparent,
                f"{chart}-{version}",
                f"Bumped the `{chart}` subchart of the bundled `{parent}` chart to `{version}`."
                f" See the [{chart} {version} release]({url}).",
            )
            changed.append(grandparent)
            pending.extend(_pinning_charts(grandparent))

    print(" ".join(changed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    app = sub.add_parser("app-version", help="set appVersion and bump the chart version")
    app.add_argument("chart")
    app.add_argument("app_version")
    app.add_argument("--notes-url")
    pin = sub.add_parser("repin", help="point the charts that pin <chart> at <version>")
    pin.add_argument("chart")
    pin.add_argument("version")
    args = parser.parse_args()

    if not (CHARTS / args.chart / "Chart.yaml").exists():
        raise SystemExit(f"Unknown chart: {args.chart}")
    if args.command == "app-version":
        app_version(args.chart, args.app_version, args.notes_url)
    else:
        repin(args.chart, args.version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
