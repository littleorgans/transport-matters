#!/usr/bin/env bash
set -euo pipefail

readonly SUPPORTED_CLIENTS=("claude" "codex")

supported_clients_label() {
    local IFS='|'
    echo "${SUPPORTED_CLIENTS[*]}"
}

is_supported_client() {
    local candidate="$1"
    local supported
    for supported in "${SUPPORTED_CLIENTS[@]}"; do
        [[ "$candidate" == "$supported" ]] && return 0
    done
    return 1
}

usage() {
    echo "usage: $(basename "$0") <$(supported_clients_label)> [path]" >&2
    exit 2
}

[[ $# -ge 1 ]] || usage
client="$1"
shift
is_supported_client "$client" || usage

target_path="${1:-$PWD}"
target_path="$(cd "$target_path" && pwd)"

[[ -n "${TMUX:-}" ]] || { echo "error: not inside tmux" >&2; exit 2; }
command -v transport-matters >/dev/null || { echo "error: transport-matters not on PATH" >&2; exit 2; }
command -v node >/dev/null || { echo "error: node not on PATH" >&2; exit 2; }
command -v pnpm >/dev/null || { echo "error: pnpm not on PATH" >&2; exit 2; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
www_dir="$repo_root/www"
[[ -d "$www_dir" ]] || { echo "error: $www_dir missing" >&2; exit 2; }

channel="${TRANSPORT_MATTERS_CHANNEL:-stable}"
channel_specs_path="$repo_root/api/src/transport_matters/channel-specs.json"

ports="$(
    node - "$channel_specs_path" "$channel" <<'NODE'
const { readFileSync } = require("node:fs");

const [specsPath, channel] = process.argv.slice(2);
const payload = JSON.parse(readFileSync(specsPath, "utf8"));
const spec = payload.channels.find((candidate) => candidate.id === channel);
if (spec === undefined) {
    console.error(`error: unknown channel ${channel}`);
    process.exit(2);
}
console.log(`${spec.proxyPort} ${spec.webPort}`);
NODE
)"
read -r proxy_port web_port <<<"$ports"

for port in "$proxy_port" "$web_port"; do
    if lsof -i ":$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "error: port $port in use" >&2
        exit 2
    fi
done

discover_dev_api_base_url() {
    local status_json
    status_json="$(transport-matters channel status "$channel" --json 2>/dev/null)" || return 1
    STATUS_JSON="$status_json" node - <<'NODE'
const payload = JSON.parse(process.env.STATUS_JSON ?? "");
const apiBaseUrl = payload.runtime?.apiBaseUrl;
if (typeof apiBaseUrl !== "string" || apiBaseUrl.length === 0) {
    process.exit(1);
}
console.log(apiBaseUrl);
NODE
}

shell_quote() {
    printf "%q" "$1"
}

dev_api_base_url="$(discover_dev_api_base_url || true)"
if [[ -z "$dev_api_base_url" ]]; then
    dev_api_base_url="http://127.0.0.1:$web_port"
fi

window_name="transport-matters-$client"
api_cmd="cd $(shell_quote "$repo_root") && transport-matters $client --debug --proxy-port $proxy_port --web-port $web_port $(shell_quote "$target_path")"
www_cmd="cd $(shell_quote "$www_dir") && TRANSPORT_MATTERS_DEV_API_BASE_URL=$(shell_quote "$dev_api_base_url") pnpm dev"

tmux new-window -n "$window_name" -c "$repo_root" "$api_cmd"
tmux split-window -v -p 20 -t "$window_name" -c "$www_dir" "$www_cmd"
tmux select-pane -t "$window_name".0
