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
#
# Equivalent entry points:
#   just release 0.2.2             # from repo root
#   pnpm release 0.2.2             # from www/
#
set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
VERSION=""

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \?//'
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
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

echo
echo "Release workflow: https://github.com/littleorgans/transport-matters/actions/workflows/release.yml"
if command -v gh >/dev/null 2>&1; then
  echo "Tail with:  gh run watch \$(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status"
fi
