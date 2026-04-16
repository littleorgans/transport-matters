# Manicure — root justfile
# Proxies to api/ and www/

default:
    @just --list

# --- API ---

api *args:
    cd api && just {{args}}

# --- WWW ---

www *args:
    cd www && just {{args}}

# --- Combined ---

test:
    cd www && just test
    cd api && just test

check:
    cd www && just check
    cd api && just check

[no-exit-message]
dev:
    overmind start

build:
    cd www && just build
    cd api && just build

install:
    cd api && just install
    cd www && pnpm install

[no-exit-message]
tool-install-editable:
    uv tool install --force --editable ./api

[no-exit-message]
start *args:
    uv run --project api manicure start {{args}}

# Cut a release: annotated tag vX.Y.Z -> push -> CI publishes to PyPI.
# Pass --dry-run to just preview, or --yes to skip the confirm.
release *args:
    ./release.sh {{args}}
