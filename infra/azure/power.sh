#!/usr/bin/env bash
# Pause / resume the dev hosting to save cost while nobody is testing.
#
#   bash infra/azure/power.sh status   state of the API, database and month-to-date cost
#   bash infra/azure/power.sh pause    API to 0 replicas, PostgreSQL compute stopped
#   bash infra/azure/power.sh resume   PostgreSQL started, API back to 1 replica, health check
#
# Paused, the database and API compute stop billing (about AUD 1.75/day saved).
# Storage, the Key Vault keys, the load balancer, the private endpoint and the
# registry keep billing: they cannot be paused without deleting them.
#
# While paused:
#   - schedules do not fire (the scheduler runs inside the API) and nothing
#     is lost: on resume each overdue schedule fires once, then keeps its interval.
#   - switch the lab gateway away first (sudo cv-use-saas lab) or shut its VM
#     down; its polls would otherwise wake the API, which cannot reach the DB.
#   - Azure restarts a stopped PostgreSQL server by itself after 7 days;
#     run "pause" again then.
#   - run "resume" before any deployment: Bicep cannot update a stopped server.
set -euo pipefail

SUB=5b69e8d9-2842-44ff-99eb-55eb9836576d
APP_RG=rg-cv360-app-dev
APP=ca-cv360-api-dev
DB_RG=rg-cv360-data-dev
DB=psql-cv360-dev

az account set --subscription "$SUB"

db_state() { az postgres flexible-server show -g "$DB_RG" -n "$DB" --query state -o tsv; }
min_replicas() { az containerapp show -g "$APP_RG" -n "$APP" --query properties.template.scale.minReplicas -o tsv; }
api_url() { az containerapp show -g "$APP_RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv; }

month_cost() {
  # The body goes through a file: Windows az mangles inline JSON quotes.
  local f arg
  f=$(mktemp)
  echo '{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"cost":{"name":"Cost","function":"Sum"}}}}' > "$f"
  arg="$f"; command -v cygpath >/dev/null && arg=$(cygpath -w "$f")
  MSYS_NO_PATHCONV=1 az rest --method post \
    --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.CostManagement/query?api-version=2023-03-01" \
    --body "@$arg" --query "properties.rows" -o tsv 2>/dev/null | awk '{printf "%.2f %s\n", $1, $2}'
  rm -f "$f"
}

status() {
  echo "PostgreSQL $DB:      $(db_state)"
  echo "API $APP min replicas: $(min_replicas)"
  echo "Month-to-date cost:       $(month_cost || echo unavailable)"
}

case "${1:-}" in
  status)
    status
    ;;
  pause)
    echo "Reminder: switch the lab gateway away first (sudo cv-use-saas lab) or shut its VM down."
    az containerapp update -g "$APP_RG" -n "$APP" --min-replicas 0 --query "properties.template.scale.minReplicas" -o tsv >/dev/null
    echo "API scaled to 0 (idle replicas stop within ~5 minutes)"
    if [ "$(db_state)" = "Ready" ]; then
      echo "stopping PostgreSQL (takes a few minutes) ..."
      az postgres flexible-server stop -g "$DB_RG" -n "$DB" -o none
    fi
    status
    ;;
  resume)
    if [ "$(db_state)" != "Ready" ]; then
      echo "starting PostgreSQL (takes a few minutes) ..."
      az postgres flexible-server start -g "$DB_RG" -n "$DB" -o none
    fi
    az containerapp update -g "$APP_RG" -n "$APP" --min-replicas 1 -o none
    url="https://$(api_url)/healthz"
    for _ in $(seq 1 30); do
      if curl -fsS "$url" >/dev/null 2>&1; then echo "API healthy: $url"; status; exit 0; fi
      sleep 10
    done
    echo "API did not answer $url within 5 minutes" >&2
    exit 1
    ;;
  *)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
