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
