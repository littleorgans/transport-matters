#!/usr/bin/env bash
#
# Transport Matters one-shot installer
#
# Usage:
#   curl -fsSL https://github.com/littleorgans/transport-matters/releases/latest/download/install.sh | bash
#
# What it does:
#   1. Installs `uv` if it is not already on PATH (official astral installer).
#   2. Runs `uv tool install transport-matters`, which pulls the latest wheel from
#      PyPI and wires up the `transport-matters` console script.
#   3. Prints next steps: where the binary lives and how to start it.
#
# Design goals (shamelessly stolen from attention-matters):
#   - Every failure path prints a specific, actionable next step.
#   - No sudo. No system proxy settings. No cert install.
#   - Safe to re-run. Idempotent by construction.
#
# Environment knobs:
#   TRANSPORT_MATTERS_INSTALL_VERSION   Pin a specific version, e.g. `0.2.0`.
#                              Defaults to the latest on PyPI.
#   TRANSPORT_MATTERS_SKIP_UV_INSTALL   Set to `1` to refuse auto-installing uv.
#                              Useful on CI/hardened hosts.

set -euo pipefail

# --------------------------------------------------------------------------- #
# Pretty output                                                               #
# --------------------------------------------------------------------------- #

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    _bold=$'\033[1m'
    _dim=$'\033[2m'
    _red=$'\033[31m'
    _green=$'\033[32m'
    _yellow=$'\033[33m'
    _cyan=$'\033[36m'
    _reset=$'\033[0m'
else
    _bold=""; _dim=""; _red=""; _green=""; _yellow=""; _cyan=""; _reset=""
fi

say()  { printf "%s==>%s %s\n" "$_cyan$_bold" "$_reset" "$*"; }
ok()   { printf "%s✓%s %s\n" "$_green" "$_reset" "$*"; }
warn() { printf "%s!%s %s\n" "$_yellow" "$_reset" "$*" >&2; }
die()  {
    printf "%serror:%s %s\n" "$_red$_bold" "$_reset" "$*" >&2
    if [ $# -gt 1 ]; then
        shift
        while [ $# -gt 0 ]; do
            printf "       %s\n" "$1" >&2
            shift
        done
    fi
    exit 1
}

# --------------------------------------------------------------------------- #
# Preflight                                                                   #
# --------------------------------------------------------------------------- #

say "transport-matters installer"

case "$(uname -s)" in
    Linux|Darwin) ;;
    *)
        die "unsupported platform: $(uname -s)" \
            "transport-matters currently supports Linux and macOS." \
            "Windows is not yet tested. Track progress at:" \
            "  https://github.com/littleorgans/transport-matters/issues"
        ;;
esac

# --------------------------------------------------------------------------- #
# 1. Ensure uv is available                                                   #
# --------------------------------------------------------------------------- #

if command -v uv >/dev/null 2>&1; then
    ok "uv already installed ($(uv --version))"
else
    if [ "${TRANSPORT_MATTERS_SKIP_UV_INSTALL:-0}" = "1" ]; then
        die "uv is not installed and TRANSPORT_MATTERS_SKIP_UV_INSTALL=1" \
            "Install uv manually, then re-run this installer:" \
            "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi

    say "installing uv (Astral's Python tool manager)"
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        die "uv installer failed" \
            "Try installing uv manually:" \
            "  curl -LsSf https://astral.sh/uv/install.sh | sh" \
            "Then re-run:" \
            "  curl -fsSL https://github.com/littleorgans/transport-matters/releases/latest/download/install.sh | bash"
    fi

    # The official uv installer drops a binary at ~/.local/bin/uv on Linux
    # and ~/.cargo/bin/uv on some older configs. Make it reachable for the
    # rest of this script without requiring a shell reload.
    for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -x "$candidate/uv" ]; then
            export PATH="$candidate:$PATH"
        fi
    done

    if ! command -v uv >/dev/null 2>&1; then
        die "uv installed but not on PATH" \
            "Add uv's bin directory to your shell rc, e.g.:" \
            "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" \
            "Then re-open your terminal and re-run:" \
            "  curl -fsSL https://github.com/littleorgans/transport-matters/releases/latest/download/install.sh | bash"
    fi
    ok "uv installed ($(uv --version))"
fi

# --------------------------------------------------------------------------- #
# 2. Install transport-matters as a uv tool                                            #
# --------------------------------------------------------------------------- #

pin="${TRANSPORT_MATTERS_INSTALL_VERSION:-}"
if [ -n "$pin" ]; then
    target="transport-matters==$pin"
    say "installing $target"
else
    target="transport-matters"
    say "installing transport-matters (latest)"
fi

if ! uv tool install --force "$target"; then
    die "uv tool install $target failed" \
        "Common causes:" \
        "  - No network or PyPI is unreachable" \
        "  - Python 3.12+ not available on this system" \
        "Try a verbose manual install to see the full error:" \
        "  uv tool install --verbose $target" \
        "Open an issue with the output at:" \
        "  https://github.com/littleorgans/transport-matters/issues"
fi

# --------------------------------------------------------------------------- #
# 3. Verify and print next steps                                              #
# --------------------------------------------------------------------------- #

if ! command -v transport-matters >/dev/null 2>&1; then
    warn "transport-matters installed but not yet on PATH"
    printf "       Ensure uv's tool bin directory is on PATH:\n"
    printf "       %suv tool update-shell%s\n\n" "$_bold" "$_reset"
    printf "       Then re-open your terminal.\n\n"
fi

version_line=""
if command -v transport-matters >/dev/null 2>&1; then
    version_line=$(transport-matters --version 2>/dev/null || true)
fi

ok "transport-matters installed${version_line:+ - $version_line}"

cat <<EOF

${_bold}Next steps${_reset}

  ${_cyan}transport-matters claude${_reset}                             ${_dim}# boot proxy + web UI${_reset}
  ${_cyan}ANTHROPIC_BASE_URL=http://localhost:8787 claude${_reset}

Then open ${_cyan}http://localhost:8788${_reset} for the live log, rules UI,
and breakpoint editor.

${_bold}Diagnose the install${_reset}

  ${_cyan}transport-matters doctor${_reset}      ${_dim}# runs a checklist of things that can go wrong${_reset}
  ${_cyan}transport-matters paths${_reset}       ${_dim}# show where captured exchanges and rules live${_reset}

${_bold}Learn more${_reset}

  ${_cyan}transport-matters --help${_reset}
  Docs & source:  https://github.com/littleorgans/transport-matters
  Report issues:  https://github.com/littleorgans/transport-matters/issues
EOF
