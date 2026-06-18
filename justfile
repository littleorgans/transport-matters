# Transport Matters root justfile
# Proxies to api/ and www/

repo_root := justfile_directory()
api_dir := repo_root / "api"
desktop_dir := repo_root / "desktop"
www_dir := repo_root / "www"
python_version_file := api_dir / ".python-version"
version_file := api_dir / "src/transport_matters/_version.py"

dev_target_dir := invocation_directory()

default:
    @just --list

# --- API ---

api *args:
    cd "{{api_dir}}" && just {{args}}

# --- WWW ---

www *args:
    cd "{{www_dir}}" && just {{args}}

# --- Desktop ---

desktop *args:
    cd "{{desktop_dir}}" && just {{args}}

# --- Combined ---

test:
    cd "{{desktop_dir}}" && just test
    cd "{{www_dir}}" && just test
    cd "{{api_dir}}" && just test

test-e2e:
    cd "{{www_dir}}" && just test-e2e

check:
    cd "{{desktop_dir}}" && just check
    cd "{{www_dir}}" && just check
    cd "{{api_dir}}" && just check

[no-exit-message]
dev client directory=dev_target_dir:
    "{{repo_root}}/scripts/local-dev-mode.sh" {{client}} {{directory}}

build:
    cd "{{desktop_dir}}" && just build
    cd "{{www_dir}}" && just build
    cd "{{api_dir}}" && just build

clean:
    cd "{{desktop_dir}}" && just clean
    cd "{{www_dir}}" && just clean
    cd "{{api_dir}}" && just clean

install:
    cd "{{api_dir}}" && just install
    cd "{{desktop_dir}}" && pnpm install
    cd "{{www_dir}}" && pnpm install

[no-exit-message]
install-local:
    rm -f "{{version_file}}"
    cd "{{www_dir}}" && pnpm install && pnpm build
    # Desktop must be set up too, or `transport-matters desktop` has no Electron app:
    # build compiles dist/main.js; electron:install fetches the Electron binary
    # (pnpm does not run electron's own postinstall, hence the explicit script).
    cd "{{desktop_dir}}" && pnpm install && pnpm build && pnpm electron:install
    uv tool install --force --python "$(cat "{{python_version_file}}")" --refresh-package transport-matters --editable "{{api_dir}}"
    transport-matters --version

[no-exit-message]
tool-install-editable: install-local

[no-exit-message]
install-release version="latest":
    @set -euo pipefail; \
    git -C "{{repo_root}}" fetch --quiet --tags origin; \
    if [ "{{version}}" = "--list" ] || [ "{{version}}" = "list" ]; then \
        git -C "{{repo_root}}" tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | sed -n '1,20p'; \
        exit 0; \
    fi; \
    version="{{version}}"; \
    if [ "$version" = "latest" ]; then \
        tag="$(git -C "{{repo_root}}" tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n 1)"; \
        if [ -z "$tag" ]; then \
            echo "error: no release tags found" >&2; \
            exit 1; \
        fi; \
        version="${tag#v}"; \
    else \
        version="${version#v}"; \
    fi; \
    echo "Installing transport-matters $version"; \
    uv tool install --force --refresh-package transport-matters "transport-matters==$version"; \
    transport-matters --version

[no-exit-message]
start *args:
    uv run --project "{{api_dir}}" transport-matters claude {{args}}

# Cut a release: annotated tag vX.Y.Z -> push -> CI publishes to PyPI.
# Pass --dry-run to just preview, or --yes to skip the confirm.
release *args:
    "{{repo_root}}/scripts/release.sh" {{args}}
