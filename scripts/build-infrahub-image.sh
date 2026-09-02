#!/usr/bin/env bash
# Build a custom Infrahub image carrying the backend source of an arbitrary
# git ref (a branch, tag, or the head of a pull request).
#
# The image is an *overlay*: it starts from a published Infrahub image and
# replaces /source/backend, the tree the published image installs in editable
# mode, with the one from the requested ref. Swapping the source is enough for
# the new code to run — no toolchain, frontend or docs rebuild — which makes
# this seconds instead of tens of minutes. Two limits come with it: the ref must
# resolve the same dependencies as the base image (the script compares uv.lock
# and refuses to build when they differ), and changes outside backend/ are not
# picked up. Notably python_sdk is a submodule, absent from `git archive`, so a
# ref that also changes the SDK needs a full build from infrahub's own
# development/Dockerfile instead.
#
# Usage:
#   scripts/build-infrahub-image.sh --pr 10487
#   scripts/build-infrahub-image.sh --ref my-branch --tag my-tag
#
# The full image reference is the only thing printed on stdout; progress goes
# to stderr.
set -euo pipefail

REPO_SLUG="opsmill/infrahub"
REPO_URL=""
REF=""
PR=""
TAG=""
BASE=""
SOURCE_DIR="${INFRAHUB_SOURCE_DIR:-}"
IMAGE_NAME="registry.opsmill.io/opsmill/infrahub"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

usage() {
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'USAGE'

Options:
  --pr N            Pull request number in opsmill/infrahub; its head branch is
                    the ref, and the default tag becomes "pr-N". Needs `gh`.
  --ref REF         Branch, tag or commit to build (alternative to --pr).
  --tag TAG         Tag of the produced image (default: derived from --pr/--ref).
  --base IMAGE      Base image to overlay (default: registry.opsmill.io/opsmill/
                    infrahub:<appVersion of charts/infrahub>).
  --image NAME      Image name without tag (default: the opsmill registry path,
                    so the chart needs only `global.infrahubTag` overridden).
  --source DIR      Existing infrahub checkout to read the ref from, instead of
                    cloning. Read with `git archive`; the working tree and the
                    checked-out branch are left untouched.
  --repo URL        Clone URL when --source is not given (default: the HTTPS URL
                    of opsmill/infrahub).
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pr) PR="$2"; shift 2 ;;
        --ref) REF="$2"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --base) BASE="$2"; shift 2 ;;
        --image) IMAGE_NAME="$2"; shift 2 ;;
        --source) SOURCE_DIR="$2"; shift 2 ;;
        --repo) REPO_URL="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument '$1'" ;;
    esac
done

if [[ -n "$PR" ]]; then
    [[ -n "$REF" ]] && die "--pr and --ref are mutually exclusive"
    command -v gh >/dev/null || die "--pr needs the GitHub CLI (gh) to resolve the head branch"
    REF="$(gh pr view "$PR" --repo "$REPO_SLUG" --json headRefName -q .headRefName)"
    [[ -n "$REF" ]] || die "could not resolve the head branch of PR #$PR"
    TAG="${TAG:-pr-$PR}"
fi
[[ -n "$REF" ]] || { usage >&2; die "one of --pr or --ref is required"; }
# Image tags allow neither "/" nor most of what a branch name allows.
TAG="${TAG:-$(echo "$REF" | tr -c 'a-zA-Z0-9_.-' '-')}"
REPO_URL="${REPO_URL:-https://github.com/${REPO_SLUG}.git}"

if [[ -z "$BASE" ]]; then
    app_version="$(sed -n 's/^appVersion: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$REPO_ROOT/charts/infrahub/Chart.yaml")"
    [[ -n "$app_version" ]] || die "could not read appVersion from charts/infrahub/Chart.yaml"
    BASE="registry.opsmill.io/opsmill/infrahub:${app_version}"
fi
IMAGE="${IMAGE_NAME}:${TAG}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
context="$workdir/context"
mkdir -p "$context"

if [[ -n "$SOURCE_DIR" ]]; then
    git -C "$SOURCE_DIR" rev-parse --verify --quiet "${REF}^{commit}" >/dev/null \
        || die "ref '$REF' not found in $SOURCE_DIR (fetch it first)"
    archive_from=(git -C "$SOURCE_DIR" archive "$REF")
    commit="$(git -C "$SOURCE_DIR" rev-parse --short "${REF}^{commit}")"
else
    echo "==> cloning $REPO_URL at $REF" >&2
    git clone --quiet --depth 1 --single-branch --branch "$REF" "$REPO_URL" "$workdir/src"
    archive_from=(git -C "$workdir/src" archive HEAD)
    commit="$(git -C "$workdir/src" rev-parse --short HEAD)"
fi

echo "==> pulling base image $BASE" >&2
docker pull --quiet "$BASE" >/dev/null

# The overlay only holds if the ref installs the same dependencies as the base.
"${archive_from[@]}" uv.lock | tar -xO > "$workdir/ref-uv.lock"
docker run --rm --entrypoint cat "$BASE" /source/uv.lock > "$workdir/base-uv.lock"
if ! cmp -s "$workdir/ref-uv.lock" "$workdir/base-uv.lock"; then
    die "uv.lock differs between $REF and $BASE: the overlay would run new code against
       the base image's dependencies. Pick a --base built from the same lock, or
       build the image from infrahub's own development/Dockerfile."
fi

echo "==> extracting backend at $REF ($commit)" >&2
"${archive_from[@]}" backend | tar -x -C "$context"
[[ -d "$context/backend/infrahub" ]] || die "no backend/infrahub tree at $REF"

cat > "$context/Dockerfile" <<'DOCKERFILE'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# The venv installs infrahub-server in editable mode against this path, so
# replacing the tree swaps the running code. It is removed first so a file
# deleted upstream does not survive the copy.
RUN rm -rf /source/backend
COPY backend /source/backend
DOCKERFILE

echo "==> building $IMAGE" >&2
docker build --quiet --build-arg "BASE_IMAGE=$BASE" -t "$IMAGE" "$context" >/dev/null

echo "$IMAGE"
