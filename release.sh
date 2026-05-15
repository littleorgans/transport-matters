#!/usr/bin/env bash
#
# Cut a Transport Matters release.
#
# Pushing an annotated vX.Y.Z tag triggers .github/workflows/release.yml
# which builds the wheel (version stamped from the tag by hatch-vcs and
# the www bundle stamped via TRANSPORT_MATTERS_VERSION), publishes to PyPI via
# trusted publishing, and creates a GitHub Release with auto-notes.
#
# Usage:
#   ./release.sh 0.2.2             # cut v0.2.2 (interactive confirm)
#   ./release.sh --dry-run 0.2.2   # validate + show plan, do not push
#   ./release.sh --yes 0.2.2       # skip the interactive confirm
#   ./release.sh --wait 0.2.2      # wait for release CI after tag push
#   ./release.sh --install 0.2.2   # wait, install exact release, verify CLI
#
# Equivalent entry points:
#   just release 0.2.2             # from repo root
#   pnpm release 0.2.2             # from www/
#
set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
WAIT=0
INSTALL=0
VERSION=""

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \?//'
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    --wait)    WAIT=1 ;;
    --install) INSTALL=1 ;;
    --help|-h) usage; exit 0 ;;
    -*)        echo "error: unknown flag '$arg'" >&2; usage; exit 2 ;;
    *)
      if [[ -n "$VERSION" ]]; then
        echo "error: multiple positional args ('$VERSION', '$arg')" >&2
        exit 2
      fi
      VERSION="$arg"
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  echo "error: version required (e.g. 0.2.2)" >&2
  usage
  exit 2
fi

if (( INSTALL && DRY_RUN )); then
  echo "error: --install cannot be combined with --dry-run" >&2
  exit 2
fi

if (( INSTALL )); then
  WAIT=1
fi

if (( WAIT )) && ! command -v gh >/dev/null 2>&1; then
  echo "error: gh is required for --wait / --install" >&2
  exit 1
fi

if (( INSTALL )); then
  for required_command in just python3 uv; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
      echo "error: $required_command is required for --install" >&2
      exit 1
    fi
  done
fi

VERSION="${VERSION#v}"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: version must be X.Y.Z (got '$VERSION')" >&2
  exit 2
fi

TAG="v$VERSION"

cd "$(git rev-parse --show-toplevel)"

echo "Transport Matters release -> $TAG"
echo

# --- guards ------------------------------------------------------------

BRANCH=$(git symbolic-ref --quiet --short HEAD || echo "<detached>")
if [[ "$BRANCH" != "main" ]]; then
  echo "error: not on main (on '$BRANCH')" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "error: working tree not clean" >&2
  git status --short >&2
  exit 1
fi

git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "error: local main does not match origin/main" >&2
  echo "  local:  $LOCAL" >&2
  echo "  remote: $REMOTE" >&2
  exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "error: tag $TAG already exists locally" >&2
  exit 1
fi

if git ls-remote --tags --exit-code origin "refs/tags/$TAG" >/dev/null 2>&1; then
  echo "error: tag $TAG already exists on origin" >&2
  exit 1
fi

LAST_TAG=$(git describe --tags --abbrev=0 --match='v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || true)

# --- plan --------------------------------------------------------------

echo "  from:    ${LAST_TAG:-<none>}"
echo "  to:      $TAG"
echo "  commit:  $LOCAL"
echo "  message: Transport Matters $VERSION"
echo
echo "Commits since ${LAST_TAG:-<start>}:"
if [[ -n "$LAST_TAG" ]]; then
  git log --oneline "$LAST_TAG..HEAD"
else
  git log --oneline -10
fi
echo

if (( DRY_RUN )); then
  echo "--dry-run: not creating or pushing tag"
  exit 0
fi

if (( ! ASSUME_YES )); then
  read -r -p "Cut $TAG? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 1 ;;
  esac
fi

# --- cut & push --------------------------------------------------------

git tag -a "$TAG" -m "Transport Matters $VERSION"
echo "[tag] created annotated $TAG"

git push origin "$TAG"
echo "[push] pushed $TAG to origin"

resolve_release_workflow_run() {
  local tag="$1"
  local run_id=""

  for attempt in $(seq 1 30); do
    run_id=$(
      gh run list \
        --workflow=release.yml \
        --limit 20 \
        --json databaseId,headBranch \
        --jq ".[] | select(.headBranch == \"$tag\") | .databaseId" \
        | head -n 1
    )
    if [[ -n "$run_id" && "$run_id" != "null" ]]; then
      echo "$run_id"
      return 0
    fi
    if (( attempt < 30 )); then
      sleep 5
    fi
  done

  echo "error: release workflow run for $tag was not found" >&2
  exit 1
}

verify_pypi_version() {
  local version="$1"

  python3 - "$version" <<'PY'
import json
import sys
import urllib.request

version = sys.argv[1]
url = "https://pypi.org/pypi/transport-matters/json"
try:
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
except Exception as exc:
    print(f"PyPI check failed: {exc}", file=sys.stderr)
    raise SystemExit(1)

if version in payload.get("releases", {}):
    raise SystemExit(0)

raise SystemExit(1)
PY
}

wait_for_pypi_version() {
  local version="$1"

  for attempt in $(seq 1 12); do
    if verify_pypi_version "$version"; then
      return 0
    fi
    if (( attempt < 12 )); then
      sleep 5
    fi
  done

  echo "error: transport-matters $version is not visible on PyPI" >&2
  exit 1
}

if (( WAIT )); then
  echo
  echo "Waiting for release workflow run for $TAG"
  RUN_ID=$(resolve_release_workflow_run "$TAG")
  gh run watch "$RUN_ID" --exit-status
fi

if (( INSTALL )); then
  echo
  echo "Verifying transport-matters $VERSION is visible on PyPI"
  wait_for_pypi_version "$VERSION"

  echo "Installing released CLI with: just install-release $VERSION"
  just install-release "$VERSION"

  VERSION_LINE=$(transport-matters --version)
  echo "$VERSION_LINE"
  case "$VERSION_LINE" in
    "transport-matters $VERSION") ;;
    *)
      echo "error: expected transport-matters $VERSION after install" >&2
      exit 1
      ;;
  esac
fi

echo
echo "Release workflow: https://github.com/littleorgans/transport-matters/actions/workflows/release.yml"
if command -v gh >/dev/null 2>&1; then
  echo "Tail with:  gh run watch \$(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status"
fi
echo
echo "After the release workflow passes, update your local CLI with:"
echo "  just install-release $VERSION"
