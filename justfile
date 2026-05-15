# Transport Matters root justfile
# Proxies to api/ and www/

dev_target_dir := invocation_directory()

default:
    @just --list

# --- API ---

api *args:
    cd api && just {{args}}

# --- WWW ---

www *args:
    cd www && just {{args}}

# --- Desktop ---

desktop *args:
    cd desktop && just {{args}}

# --- Combined ---

test:
    cd desktop && just test
    cd www && just test
    cd api && just test

check:
    cd desktop && just check
    cd www && just check
    cd api && just check

[no-exit-message]
dev client directory=dev_target_dir:
    ./scripts/local-dev-mode.sh {{client}} {{directory}}

build:
    cd desktop && just build
    cd www && just build
    cd api && just build

clean:
    cd desktop && just clean
    cd www && just clean
    cd api && just clean

install:
    cd api && just install
    cd desktop && pnpm install
    cd www && pnpm install

[no-exit-message]
install-local:
    rm -f api/src/transport_matters/_version.py
    cd www && pnpm install && pnpm build
    uv tool install --force --refresh-package transport-matters --editable ./api
    transport-matters --version

[no-exit-message]
tool-install-editable: install-local

[no-exit-message]
install-release version="latest":
    @set -euo pipefail; \
    git fetch --quiet --tags origin; \
    if [ "{{version}}" = "--list" ] || [ "{{version}}" = "list" ]; then \
        git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | sed -n '1,20p'; \
        exit 0; \
    fi; \
    version="{{version}}"; \
    if [ "$version" = "latest" ]; then \
        tag="$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n 1)"; \
        if [ -z "$tag" ]; then \
            echo "error: no release tags found" >&2; \
            exit 1; \
        fi; \
        version="${tag#v}"; \
    else \
        version="${version#v}"; \
    fi; \
    echo "Installing transport-matters $version"; \
    uv tool install --force "transport-matters==$version"; \
    transport-matters --version

[no-exit-message]
start *args:
    uv run --project api transport-matters claude {{args}}

# Cut a release: annotated tag vX.Y.Z -> push -> CI publishes to PyPI.
# Pass --dry-run to just preview, or --yes to skip the confirm.
release *args:
    ./release.sh {{args}}
