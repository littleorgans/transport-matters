# Transport Matters root justfile
# api/ stays uv/hatch; repo root owns the pnpm workspace for www packages and desktop.

repo_root := justfile_directory()
api_dir := repo_root / "api"
desktop_dir := repo_root / "desktop"
shell_dir := repo_root / "www/packages/shell"
shell_package := "@tm/shell"
desktop_package := "transport-matters-desktop"
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
    cd "{{shell_dir}}" && just {{args}}

# --- Desktop ---

desktop *args:
    cd "{{desktop_dir}}" && just {{args}}

# --- Combined ---

js-install:
    pnpm install --frozen-lockfile --ignore-scripts

test: js-install
    cd "{{desktop_dir}}" && just test
    cd "{{shell_dir}}" && just test
    cd "{{api_dir}}" && just test

check: js-install
    cd "{{desktop_dir}}" && just check
    cd "{{shell_dir}}" && just check
    pnpm --filter @tm/core typecheck
    pnpm --filter @tm/inspector typecheck
    pnpm --filter @tm/canvas typecheck
    cd "{{api_dir}}" && just check

[no-exit-message]
dev client directory=dev_target_dir:
    "{{repo_root}}/scripts/local-dev-mode.sh" {{client}} {{directory}}

build: js-install
    cd "{{desktop_dir}}" && just build
    cd "{{shell_dir}}" && just build
    cd "{{api_dir}}" && just build

clean:
    cd "{{desktop_dir}}" && just clean
    cd "{{shell_dir}}" && just clean
    rm -rf "{{repo_root}}/www/packages/host/node_modules"
    rm -rf "{{repo_root}}/node_modules"
    cd "{{api_dir}}" && just clean

install:
    cd "{{api_dir}}" && just install
    pnpm install

[no-exit-message]
install-local:
    rm -f "{{version_file}}"
    pnpm install
    pnpm --filter {{shell_package}} build
    # Desktop must be set up too, or `transport-matters desktop` has no Electron app:
    # build compiles dist/main.js; electron:install fetches the Electron binary
    # (pnpm does not run electron's own postinstall, hence the explicit script).
    pnpm --filter {{desktop_package}} build
    pnpm --filter {{desktop_package}} electron:install
    uv tool install --force --python "$(cat "{{python_version_file}}")" --refresh-package transport-matters --editable "{{api_dir}}"
    transport-matters --version

[no-exit-message]
channel-restart channel="preview" *desktop_args:
    pnpm install
    pnpm --filter {{shell_package}} build
    pnpm --filter {{desktop_package}} build
    pnpm --filter {{desktop_package}} electron:install
    uv run --project "{{api_dir}}" transport-matters channel stop {{channel}}
    uv run --project "{{api_dir}}" transport-matters channel ensure-db {{channel}}
    TRANSPORT_MATTERS_CHANNEL={{channel}} uv run --project "{{api_dir}}" transport-matters desktop --channel {{channel}} {{desktop_args}}

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
# Pass --dry-run to preview, or --yes to skip the confirm.
release *args:
    "{{repo_root}}/scripts/release.sh" {{args}}
