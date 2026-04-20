#!/bin/sh
set -eu
cd /app/service
if [ -n "${DATABASE_URL:-}" ]; then
  # Local dev often uses 127.0.0.1/localhost; from inside Kubernetes that is the pod, not the host.
  case "$DATABASE_URL" in
    *127.0.0.1*|*localhost*)
      echo "docker-entrypoint: DATABASE_URL refers to localhost; skipping db-init (use a cluster-reachable Postgres URL or omit DATABASE_URL)"
      ;;
    *)
      /bin/sh /app/service/db-init.sh
      ;;
  esac
else
  echo "docker-entrypoint: DATABASE_URL not set; skipping migrations and seed"
fi
exec uvicorn app:app --host 0.0.0.0 --port 8000
