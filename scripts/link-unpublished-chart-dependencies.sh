#!/usr/bin/env bash
# Point a chart's dependencies on charts of this repository at the local chart
# directory when the pinned version is not published yet.
#
# A pull request that bumps a chart and re-pins the charts that depend on it
# cannot resolve the new version from the registry until that version is
# released, so `helm dependency update` fails on it. This script makes such a
# dependency resolve from charts/<name> instead, but only when that chart has
# exactly the pinned version: a pin that is neither published nor in this
# repository still fails. A pin that is published keeps resolving from the
# registry, so the lint checks what a release would package.
#
# Usage:
#   scripts/link-unpublished-chart-dependencies.sh charts/<name>
#
# Needs helm and yq (mikefarah). It rewrites charts/<name>/Chart.yaml in place,
# so run it in a checkout you throw away, such as a CI job.
set -euo pipefail

REGISTRY="oci://registry.opsmill.io/opsmill/chart"

chart_dir="${1:?usage: $0 charts/<name>}"
chart_yaml="${chart_dir}/Chart.yaml"
charts_root="$(dirname "${chart_dir}")"

dependencies="$(REGISTRY="${REGISTRY}" yq -r \
  '.dependencies[] | select(.repository == strenv(REGISTRY)) | [.name, .version] | @tsv' \
  "${chart_yaml}")"

while IFS=$'\t' read -r name version; do
  [ -n "${name}" ] || continue
  local_yaml="${charts_root}/${name}/Chart.yaml"
  if [ ! -f "${local_yaml}" ]; then
    continue
  fi

  if helm show chart "${REGISTRY}/${name}" --version "${version}" >/dev/null 2>&1; then
    echo "${name} ${version}: published, resolving it from ${REGISTRY}"
    continue
  fi

  local_version="$(yq -r '.version' "${local_yaml}")"
  if [ "${local_version}" != "${version}" ]; then
    echo "${name} ${version}: not published, and ${local_yaml} has version ${local_version}" >&2
    exit 1
  fi

  echo "${name} ${version}: not published, resolving it from ${charts_root}/${name}"
  NAME="${name}" yq -i \
    '(.dependencies[] | select(.name == strenv(NAME))).repository = "file://../" + strenv(NAME)' \
    "${chart_yaml}"
done <<<"${dependencies}"
