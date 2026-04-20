#!/bin/sh
# Apply supabase/migrations/*.sql and seed.sql once per DATABASE_URL, tracked in Postgres.
# Requires DATABASE_URL (Postgres URI, e.g. from Supabase → Settings → Database).
set -eu

MIG_DIR="/app/service/supabase/migrations"
SEED_FILE="/app/service/supabase/seed.sql"

psql_cmd() {
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
}

echo "db-init: ensuring migration tracking table"
psql_cmd -q -c "
CREATE TABLE IF NOT EXISTS public.dummy_test_auth_applied (
  id TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);"

apply_if_missing() {
  kind="$1"
  path="$2"
  name="$3"
  aid="${kind}:${name}"
  esc_aid=$(printf '%s' "$aid" | sed "s/'/''/g")
  cnt=$(psql "$DATABASE_URL" -tAc "SELECT COUNT(*)::int FROM public.dummy_test_auth_applied WHERE id = '${esc_aid}'")
  if [ "$cnt" != "0" ]; then
    echo "db-init: skip ${aid} (already applied)"
    return 0
  fi
  echo "db-init: applying ${aid}"
  psql_cmd -f "$path"
  psql_cmd -q -c "INSERT INTO public.dummy_test_auth_applied (id) VALUES ('${esc_aid}');"
  echo "db-init: applied ${aid}"
}

for f in "$MIG_DIR"/*.sql; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  apply_if_missing migration "$f" "$base"
done

if [ -f "$SEED_FILE" ]; then
  apply_if_missing seed "$SEED_FILE" "seed.sql"
fi

echo "db-init: done"
