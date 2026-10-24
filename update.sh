#!/bin/sh
# Run on the NAS manually or from DSM Task Scheduler. No inbound GitHub access needed.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_name="${PROJECT_NAME:-electric}"
compose() { docker compose -p "$project_name" -f docker-compose.yml "$@"; }
# Docker on Synology will not create bind-mount folders itself.
mkdir -p data data/postgres data/backups
if ! mkdir data/.update-lock 2>/dev/null; then
  echo 'Another update is active. If an earlier update was interrupted, remove data/.update-lock after checking no update is running.' >&2
  exit 1
fi
trap 'rmdir data/.update-lock' EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
image=$(compose config --images | head -n 1)
container_id=$(compose ps -a -q electric-dashboard)
previous_image=''
if [ -n "$container_id" ]; then previous_image=$(docker inspect --format '{{.Image}}' "$container_id"); fi
compose pull electric-dashboard
new_image=$(docker image inspect --format '{{.Id}}' "$image")
if [ "$previous_image" = "$new_image" ] && [ -n "$container_id" ]; then
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")
  if [ "$health" = healthy ]; then echo 'Already running the latest healthy image.'; exit 0; fi
fi
if [ -n "$previous_image" ]; then docker tag "$previous_image" electric-dashboard:rollback; fi
compose stop electric-dashboard
check_health() {
  service="${1:-electric-dashboard}"
  attempt=0
  while [ "$attempt" -lt 30 ]; do
    candidate=$(compose ps -a -q "$service")
    if [ -n "$candidate" ]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$candidate")
      if [ "$health" = healthy ]; then return 0; fi
      if [ "$health" = unhealthy ] || [ "$health" = exited ] || [ "$health" = dead ]; then return 1; fi
    fi
    attempt=$((attempt+1))
    sleep 3
  done
  return 1
}
restart_previous() {
  compose start electric-dashboard || true
  echo "$1 The previous container was restarted." >&2
  exit 1
}
echo 'Starting the database and backing it up…'
if ! compose up -d db || ! check_health db; then
  restart_previous 'The database did not become healthy.'
fi
mkdir -p data/backups
backup="data/backups/pre-update-$(date -u +%Y%m%d-%H%M%S).dump"
if ! compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$backup"; then
  rm -f "$backup"
  restart_previous 'The database backup failed.'
fi
ls -1t data/backups/pre-update-*.dump | tail -n +6 | while read -r old; do rm -f "$old"; done
echo "Created database backup: $backup"
echo 'Importing legacy data and preserving private settings…'
if ! compose run --rm -T --no-deps -v "$(pwd):/bootstrap:ro" --entrypoint python electric-dashboard /bootstrap/scripts/prepare_data.py /bootstrap /data; then
  restart_previous 'Data preparation failed.'
fi
if compose up -d --no-build --force-recreate electric-dashboard && check_health; then
  echo "Update complete: $image ($new_image)"
  exit 0
fi
compose logs --tail 50 electric-dashboard >&2 || true
if [ -n "$previous_image" ]; then
  echo 'Update failed its health check. Restoring the previous image…' >&2
  ELECTRIC_IMAGE=electric-dashboard:rollback
  export ELECTRIC_IMAGE
  compose up -d --no-build --force-recreate electric-dashboard
  if check_health; then echo 'Previous image restored. Database backups are in data/backups.' >&2; fi
fi
echo 'Update failed. Inspect Container Manager logs before retrying.' >&2
exit 1
