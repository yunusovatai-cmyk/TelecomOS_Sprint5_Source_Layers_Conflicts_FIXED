#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
docker compose up --build
