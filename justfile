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

[no-exit-message]
dev:
    overmind start

build:
    cd www && just build
    cd api && just build

install:
    cd api && just install
    cd www && pnpm install
