#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $(basename "$0") <claude|codex> [path]" >&2
    exit 2
}

[[ $# -ge 1 ]] || usage
client="$1"
shift
case "$client" in
    claude | codex) ;;
    *) usage ;;
esac

target_path="${1:-$PWD}"
target_path="$(cd "$target_path" && pwd)"

[[ -n "${TMUX:-}" ]] || { echo "error: not inside tmux" >&2; exit 2; }
command -v transport-matters >/dev/null || { echo "error: transport-matters not on PATH" >&2; exit 2; }
command -v pnpm >/dev/null || { echo "error: pnpm not on PATH" >&2; exit 2; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
www_dir="$repo_root/www"
[[ -d "$www_dir" ]] || { echo "error: $www_dir missing" >&2; exit 2; }

for port in 8787 8788; do
    if lsof -i ":$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "error: port $port in use" >&2
        exit 2
    fi
done

window_name="transport-matters-$client"
api_cmd="cd '$repo_root' && transport-matters $client --debug --proxy-port 8787 --web-port 8788 '$target_path'"
www_cmd="cd '$www_dir' && pnpm dev"

tmux new-window -n "$window_name" -c "$repo_root" "$api_cmd"
tmux split-window -v -p 20 -t "$window_name" -c "$www_dir" "$www_cmd"
tmux select-pane -t "$window_name".0
