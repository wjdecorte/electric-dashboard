#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_name="${PROJECT_NAME:-electric-dashboard}"
docker compose -p "$project_name" build --no-cache electric-dashboard
docker compose -p "$project_name" up -d --no-deps --force-recreate electric-dashboard
