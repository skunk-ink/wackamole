# Makefile — wackamole gateway helpers
# Usage:
#   make up                     # Start with existing ./data/manifest.json
#   make up SHARE_URL=''        # Build and start the gateway with provided SHARE_URL
#   make up INDEXD_URL=''       # Build and start the gateway with provided INDEXD_URL
#   make down                   # Stop and remove the container
#   make logs                   # Tail container logs
#   make ps                     # Show compose status
#   make seed                   # Create ./data/manifest.json if missing
#   make manifest SHARE_URL=''  # Update manifest.json safely
#   make clean                  # Remove ./data (careful!)
#   make health                 # Curl the health endpoint

# Avoid tab headaches by picking a different recipe prefix:
.RECIPEPREFIX := >

SHELL := /bin/bash

# Load .env if present so INDEXD_URL/SHARE_URL/etc. can flow in
ifneq ("$(wildcard .env)","")
include .env
export
endif

# -------- Configurable knobs (override via env or CLI: make up VAR=value) -----
SERVICE      ?= gateway
IMAGE        ?= wackamole-gateway
DATA_DIR     ?= ./data
MANIFEST     ?= $(DATA_DIR)/manifest.json

# Optional pass-throughs (do NOT hardcode defaults here):
#   SHARE_URL='https://.../shared?...#encryption_key=...'
#   INDEXD_URL='https://indexd.example'
SHARE_URL    ?=
INDEXD_URL   ?=

# You can also override Docker Compose file and health host/port if needed:
COMPOSE_FILE ?= docker-compose.yml
HOST         ?= 127.0.0.1
PORT         ?= 8787

# ------------------------------ Phony targets ---------------------------------
.PHONY: up down logs ps seed manifest clean help health ensure-script

help:
> echo "Targets:"
> echo "  make up [SHARE_URL=…] [INDEXD_URL=…]  - Build and start the gateway"
> echo "  make down                             - Stop and remove the stack"
> echo "  make logs                             - Tail container logs"
> echo "  make ps                               - Show compose status"
> echo "  make seed                             - Create ./data/manifest.json if missing"
> echo "  make manifest [SHARE_URL=…]           - Update manifest.json safely"
> echo "  make clean                            - Remove ./data (careful!)"
> echo "  make health                           - Curl http://$(HOST):$(PORT)/__health"
> echo
> echo "Notes:"
> echo "  • If SHARE_URL contains '&', quote it: SHARE_URL='...&sc=...&ss=...'"
> echo "  • INDEXD_URL is optional; if omitted the manifest's existing value is kept."
> echo "  • Values may also come from .env if present."

# Main entry: ensure manifest exists/updated, then up
up: manifest
> echo "docker compose up -d --build"
> COMPOSE_FILE=$(COMPOSE_FILE) docker compose up -d --build

down:
> COMPOSE_FILE=$(COMPOSE_FILE) docker compose down

logs:
> COMPOSE_FILE=$(COMPOSE_FILE) docker compose logs -f

ps:
> COMPOSE_FILE=$(COMPOSE_FILE) docker compose ps

# Create data dir and a minimal manifest if missing (no hardcoded indexd_url)
seed:
> mkdir -p "$(DATA_DIR)"
> if [ ! -f "$(MANIFEST)" ]; then \
>   echo "Seeding $(MANIFEST)"; \
>   printf '{}\n' > "$(MANIFEST)"; \
> else \
>   echo "$(MANIFEST) already exists; skipping seed."; \
> fi

# Ensure the helper script exists (use repo copy if present)
ensure-script:
> if [ ! -f scripts/update_manifest.py ]; then \
>   echo "ERROR: scripts/update_manifest.py is missing."; \
>   echo "Create it from the snippet in chat, then re-run make."; \
>   exit 1; \
> fi
> chmod +x scripts/update_manifest.py

# Safely write SHARE_URL / INDEXD_URL into manifest.json, preserving everything else.
manifest: seed ensure-script
> scripts/update_manifest.py \
>   --manifest "$(MANIFEST)" \
>   $(if $(strip $(SHARE_URL)),--share-url "$(SHARE_URL)",) \
>   $(if $(strip $(INDEXD_URL)),--indexd-url "$(INDEXD_URL)",)

clean:
> echo "Removing $(DATA_DIR) (careful!)"
> rm -rf "$(DATA_DIR)"

# Health-check the running gateway (assumes port mapping in compose)
health:
> set -e; \
> URL="http://$(HOST):$(PORT)/__health"; \
> echo "GET $$URL"; \
> if command -v curl >/dev/null 2>&1; then \
>   curl -fsS "$$URL" || (echo "Health check failed" && exit 1); \
> else \
>   echo "curl not found"; exit 127; \
> fi
