#!/usr/bin/env bash
# Run one read-only SQL query against the private dev database and print the
# result. PostgreSQL stays private: the query runs inside Azure in the job
# caj-cv360-sql-<env> (modules/app.bicep) as the SELECT-only role cv_readonly.
#
#   bash infra/azure/sql.sh "SELECT job_id, state FROM jobs LIMIT 5"
#   bash infra/azure/sql.sh < query.sql
#
# Needs `az login`. Takes 1-3 minutes: the output is read back from Log
# Analytics, which receives container logs with a short delay.
set -euo pipefail
RG=${APP_RG:-rg-cv360-app-dev}; JOB=${SQL_JOB:-caj-cv360-sql-dev}
MON_RG=${MON_RG:-rg-cv360-monitor-dev}; WS_NAME=${WS_NAME:-log-cv360-dev}
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
command -v az >/dev/null || { echo "Azure CLI (az) not on PATH" >&2; exit 1; }
PY=
for c in python3 python py; do "$c" -c 'import json' 2>/dev/null && { PY=$c; break; }; done
[[ -n $PY ]] || { echo "Python 3 not found" >&2; exit 1; }

q=${1:-$(cat)}
[[ -n ${q//[[:space:]]/} ]] || { echo "empty query" >&2; exit 1; }
b64=$(printf %s "$q" | base64 | tr -d '\n')

az containerapp job update -g "$RG" -n "$JOB" --container-name sql --set-env-vars "QUERY_B64=$b64" -o none 2>/dev/null
ex=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv | tr -d '\r')
echo "running in Azure as $ex ..." >&2
for _ in $(seq 1 60); do
    s=$(az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$ex" --query properties.status -o tsv | tr -d '\r')
    [[ $s == Running || $s == Processing ]] || break
    sleep 5
done

ws=$(az monitor log-analytics workspace show -g "$MON_RG" -n "$WS_NAME" --query customerId -o tsv | tr -d '\r')
body=$(mktemp); trap 'rm -f "$body"' EXIT
printf '{"query":"ContainerAppConsoleLogs_CL | where ContainerGroupName_s startswith \\"%s\\" | order by TimeGenerated asc, _timestamp_d asc | project Log_s"}' "$ex" >"$body"
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
for _ in $(seq 1 30); do
    rows=$(az rest --method post --url "https://api.loganalytics.io/v1/workspaces/$ws/query" \
        --resource https://api.loganalytics.io --body @"$(native "$body")" --query "tables[0].rows" -o json)
    grep -q -- '---- end (exit' <<<"$rows" && break
    sleep 10
done
"$PY" -c 'import json, sys; [print(r[0]) for r in json.load(sys.stdin)]' <<<"$rows"
echo "(execution $s)" >&2
