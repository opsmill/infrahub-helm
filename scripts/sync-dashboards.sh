#!/usr/bin/env bash
# Sync vendored Grafana dashboards from the upstream infrahub repository.
#
# Usage:
#   scripts/sync-dashboards.sh           # use ref recorded in .dashboards-source
#   scripts/sync-dashboards.sh <REF>     # override ref (git tag/branch/SHA), updates .dashboards-source on success
#
# Reads the chart's .dashboards-source for repo/path/files, fetches each file
# from raw.githubusercontent.com, validates JSON, writes into
# charts/infrahub-observability/dashboards/, and (if a REF was passed) updates
# the ref field in .dashboards-source.
#
# No clone, no submodule — just curl + jq. Designed to run in CI without setup.

set -euo pipefail

CHART_DIR="charts/infrahub-observability"
SOURCE_FILE="${CHART_DIR}/.dashboards-source"
DASHBOARDS_DIR="${CHART_DIR}/dashboards"

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
PATH_IN_REPO=$(yq -r '.path' "$SOURCE_FILE")
CURRENT_REF=$(yq -r '.ref' "$SOURCE_FILE")
REF="${1:-$CURRENT_REF}"

if [[ -z "$REPO" || -z "$PATH_IN_REPO" || -z "$REF" ]]; then
    echo "error: .dashboards-source missing repo/path/ref" >&2
    exit 1
fi

readarray -t FILES < <(yq -r '.files[]' "$SOURCE_FILE")
if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "error: .dashboards-source has no files listed" >&2
    exit 1
fi

mkdir -p "$DASHBOARDS_DIR"

echo "Syncing ${#FILES[@]} dashboard(s) from ${REPO}@${REF}:${PATH_IN_REPO}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

for f in "${FILES[@]}"; do
    URL="https://raw.githubusercontent.com/${REPO}/${REF}/${PATH_IN_REPO}/${f}"
    TMP_FILE="${TMPDIR}/${f}"
    echo "  fetching ${f}"
    if ! curl --fail --silent --show-error --location --output "$TMP_FILE" "$URL"; then
        echo "error: failed to download ${URL}" >&2
        exit 1
    fi
    if ! jq empty "$TMP_FILE" >/dev/null 2>&1; then
        echo "error: ${f} is not valid JSON" >&2
        exit 1
    fi
    # Apply K8s adaptations (rewrite docker-compose labels to K8s
    # equivalents). The transform is idempotent — running it on an
    # already-transformed file is a no-op.
    python3 "$(dirname "$0")/transform_dashboard.py" --in-place "$TMP_FILE"
    if ! jq empty "$TMP_FILE" >/dev/null 2>&1; then
        echo "error: ${f} became invalid JSON after transform" >&2
        exit 1
    fi
    mv "$TMP_FILE" "${DASHBOARDS_DIR}/${f}"
done

if [[ "$REF" != "$CURRENT_REF" ]]; then
    yq -i ".ref = \"${REF}\"" "$SOURCE_FILE"
    echo "Updated .dashboards-source ref: ${CURRENT_REF} -> ${REF}"
fi

echo "Done."
