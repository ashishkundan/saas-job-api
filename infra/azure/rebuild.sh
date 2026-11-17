#!/usr/bin/env bash
# Rebuild the dev hosting after teardown.sh (also safe on a running environment).
#
#   bash infra/azure/rebuild.sh                 redeploys saas-job-api:deployed-dev
#   API_IMAGE=acrcv360dev.azurecr.io/saas-job-api@sha256:... bash infra/azure/rebuild.sh
#
# Deploys main.bicep (network, database, Container Apps, private endpoint),
# runs the database migration and waits for /healthz. The last line printed
# is the API URL, which changes on every rebuild (new environment = new
# default domain); deploy/test-lab/azure/rebuild-lab.sh (CDE repo) takes it
# from there. Secrets come from Key Vault as on a first deployment.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SUB=5b69e8d9-2842-44ff-99eb-55eb9836576d
LOCATION=australiaeast
APP_RG=rg-cv360-app-dev; APP=ca-cv360-api-dev; MIGRATE=caj-cv360-migrate-dev
ACR=acrcv360dev
export MSYS_NO_PATHCONV=1
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

az account set --subscription "$SUB"

if [[ -z ${API_IMAGE:-} ]]; then
  digest=$(az acr manifest list-metadata -r "$ACR" -n saas-job-api \
    --query "[?tags && contains(tags, 'deployed-dev')].digest | [0]" -o tsv 2>/dev/null | tr -d '\r')
  [[ $digest == sha256:* ]] || { echo "no saas-job-api:deployed-dev in $ACR; set API_IMAGE" >&2; exit 1; }
  API_IMAGE=$ACR.azurecr.io/saas-job-api@$digest
fi
export API_IMAGE
echo "== 1. deploy main.bicep with ${API_IMAGE##*@} (~15-20 min after a teardown)"
az deployment sub create -n "cv360-dev-$(date +%Y%m%d%H%M)" -l "$LOCATION" \
  -f "$(native "$HERE/main.bicep")" -p "$(native "$HERE/dev.bicepparam")" \
  --query properties.provisioningState -o tsv --only-show-errors

echo "== 2. database migration"
ex=$(az containerapp job start -g "$APP_RG" -n "$MIGRATE" --query name -o tsv | tr -d '\r')
status=
for _ in $(seq 1 60); do
  status=$(az containerapp job execution show -g "$APP_RG" -n "$MIGRATE" --job-execution-name "$ex" \
    --query properties.status -o tsv | tr -d '\r')
  [[ $status == Running || $status == Processing || -z $status ]] || break
  sleep 10
done
[[ $status == Succeeded ]] || { echo "migration $ex: $status" >&2; exit 1; }
echo "   $ex succeeded"

echo "== 3. health"
url="https://$(az containerapp show -g "$APP_RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv | tr -d '\r')"
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "$url/healthz" 2>/dev/null; then echo "   healthy"; echo "$url"; exit 0; fi
  sleep 10
done
echo "API did not answer $url/healthz within 5 minutes" >&2
exit 1
