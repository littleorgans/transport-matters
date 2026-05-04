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

install:
    cd api && just install
    cd desktop && pnpm install
    cd www && pnpm install

[no-exit-message]
tool-install-editable:
    uv tool install --force --editable ./api

[no-exit-message]
start *args:
    uv run --project api transport-matters claude {{args}}

# Cut a release: annotated tag vX.Y.Z -> push -> CI publishes to PyPI.
# Pass --dry-run to just preview, or --yes to skip the confirm.
release *args:
    ./release.sh {{args}}
