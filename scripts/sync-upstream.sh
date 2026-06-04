#!/usr/bin/env bash
# Sync upstream Grafana provisioning (dashboards + datasources) from the infrahub
# repository and adapt it for Kubernetes.
#
# The synced/adapted files are NOT committed (see .gitignore): this script runs
# at packaging/release time so the chart bundles config matching the pinned
# upstream ref. For local `helm template`/`helm lint`, run it by hand first.
#
# Usage:
#   scripts/sync-upstream.sh           # use ref recorded in .upstream-source
#   scripts/sync-upstream.sh <REF>     # override ref (tag/branch/SHA); updates .upstream-source on success
#
# Reads the chart's .upstream-source for repo/ref/paths/files. No clone, no
# submodule — just curl + yq + jq + python3. Designed to run in CI without setup.

set -euo pipefail

CHART_DIR="charts/infrahub-observability"
SOURCE_FILE="${CHART_DIR}/.upstream-source"
DASHBOARDS_DIR="${CHART_DIR}/dashboards"
FILES_DIR="${CHART_DIR}/files"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "error: ${SOURCE_FILE} not found. Run from the repo root." >&2
    exit 1
fi

require() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "error: '$1' is required but not installed" >&2
        exit 1
    fi
}
require curl
require yq
require jq
require python3

REPO=$(yq -r '.repo' "$SOURCE_FILE")
CURRENT_REF=$(yq -r '.ref' "$SOURCE_FILE")
REF="${1:-$CURRENT_REF}"

if [[ -z "$REPO" || -z "$REF" || "$REPO" == "null" || "$REF" == "null" ]]; then
    echo "error: .upstream-source missing repo/ref" >&2
    exit 1
fi

raw_url() { echo "https://raw.githubusercontent.com/${REPO}/${REF}/$1"; }

fetch() {
    # fetch <repo-relative-path> <out-file>
    local url
    url="$(raw_url "$1")"
    echo "  fetching $1"
    if ! curl --fail --silent --show-error --location --output "$2" "$url"; then
        echo "error: failed to download ${url}" >&2
        exit 1
    fi
}

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# --- Dashboards ---------------------------------------------------------------
DASH_PATH=$(yq -r '.dashboards.path' "$SOURCE_FILE")
readarray -t DASH_FILES < <(yq -r '.dashboards.files[]' "$SOURCE_FILE")
if [[ "$DASH_PATH" != "null" && ${#DASH_FILES[@]} -gt 0 ]]; then
    mkdir -p "$DASHBOARDS_DIR"
    echo "Syncing ${#DASH_FILES[@]} dashboard(s) from ${REPO}@${REF}:${DASH_PATH}"
    for f in "${DASH_FILES[@]}"; do
        tmp="${TMPDIR}/${f}"
        fetch "${DASH_PATH}/${f}" "$tmp"
        if ! jq empty "$tmp" >/dev/null 2>&1; then
            echo "error: ${f} is not valid JSON" >&2
            exit 1
        fi
        # Idempotent K8s adaptation (rewrite docker-compose labels to K8s equivalents).
        python3 "${SCRIPT_DIR}/transform_dashboard.py" --in-place "$tmp"
        if ! jq empty "$tmp" >/dev/null 2>&1; then
            echo "error: ${f} became invalid JSON after transform" >&2
            exit 1
        fi
        mv "$tmp" "${DASHBOARDS_DIR}/${f}"
    done
fi

# --- Datasources --------------------------------------------------------------
DS_PATH=$(yq -r '.datasources.path' "$SOURCE_FILE")
DS_FILE=$(yq -r '.datasources.files[0]' "$SOURCE_FILE")
if [[ "$DS_PATH" != "null" && "$DS_FILE" != "null" ]]; then
    mkdir -p "$FILES_DIR"
    echo "Syncing Grafana datasources from ${REPO}@${REF}:${DS_PATH}/${DS_FILE}"
    tmp="${TMPDIR}/datasource.yml"
    fetch "${DS_PATH}/${DS_FILE}" "$tmp"
    # Adapt for K8s: rewrite the docker-compose Service hostnames to the chart's
    # Service-URL helpers (rendered via `tpl` in the ConfigMap), then re-apply
    # the chart's small behavioral overlay (default datasource + query options)
    # on top of the upstream definitions. Everything else — UIDs, derived
    # fields, Tempo trace linking — stays sourced from upstream.
    yq -P '
        .datasources[].name |= sub(" .Local.$"; "")
      | (.datasources[] | select(.type == "prometheus")).url = "{{ include \"infrahub-observability.prometheusUrl\" . }}"
      | (.datasources[] | select(.type == "prometheus")).isDefault = true
      | (.datasources[] | select(.type == "prometheus")).jsonData.httpMethod = "POST"
      | (.datasources[] | select(.type == "prometheus")).jsonData.timeInterval = "15s"
      | (.datasources[] | select(.type == "loki")).url = "{{ include \"infrahub-observability.lokiUrl\" . }}"
      | (.datasources[] | select(.type == "loki")).access = "proxy"
      | (.datasources[] | select(.type == "loki")).jsonData.maxLines = 1000
      | (.datasources[] | select(.type == "tempo")).url = "{{ include \"infrahub-observability.tempoUrl\" . }}"
      | (.datasources[] | select(.type == "tempo")).editable = true
    ' "$tmp" > "${FILES_DIR}/datasources.yaml"
fi

# --- Update pinned ref --------------------------------------------------------
if [[ "$REF" != "$CURRENT_REF" ]]; then
    yq -i ".ref = \"${REF}\"" "$SOURCE_FILE"
    echo "Updated .upstream-source ref: ${CURRENT_REF} -> ${REF}"
fi

echo "Done."
