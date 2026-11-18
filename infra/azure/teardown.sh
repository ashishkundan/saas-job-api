#!/usr/bin/env bash
# Tear the dev hosting down to what costs (almost) nothing; rebuild.sh brings it back.
#
#   bash infra/azure/teardown.sh          asks you to type "teardown"
#   bash infra/azure/teardown.sh --yes    no question (scripts)
#
# Deleted (billed by the hour, ~AUD 2.20/day together):
#   API container app, migrate + sql jobs, Container Apps environment (with
#   its load balancer and public IP), Key Vault private endpoint.
# Stopped, not deleted: the PostgreSQL server (storage only, ~AUD 0.10/day).
#   All data is kept. It is not deleted because Azure may refuse to create a
#   new one: on 2026-11-18 australiaeast answered SkuNotAvailable for B1ms and
#   B2s on this subscription. Azure starts a stopped server by itself after
#   7 days (compute billed again, ~AUD 1/day): run this script again, or
#   `bash infra/azure/power.sh status`, to stop it. Running it again is safe.
# Kept (free or cents): registry acrcv360dev, all four Key Vaults with every
#   secret and signing key, managed identities, VNet, private DNS zones, Log Analytics.
#
# rebuild.sh starts the database again before it redeploys.
#
# Before deleting, the running API image is tagged saas-job-api:deployed-dev so
# rebuild.sh redeploys exactly that image, and the GitHub variable SAAS_URL is
# removed so the plugin workflows skip the upload instead of failing.
set -euo pipefail

SUB=5b69e8d9-2842-44ff-99eb-55eb9836576d
APP_RG=rg-cv360-app-dev; APP=ca-cv360-api-dev; ENV=cae-cv360-dev
JOBS=(caj-cv360-migrate-dev caj-cv360-sql-dev)
DB_RG=rg-cv360-data-dev; DB=psql-cv360-dev
SEC_RG=rg-cv360-security-dev; PE=pe-kv-cv360-dev
ACR=acrcv360dev
GH_REPO=${GH_REPO:-ashishkundan/certificate-discovery-engine}
export MSYS_NO_PATHCONV=1

if [[ ${1:-} != --yes ]]; then
  echo "This deletes the dev API, its Container Apps environment and the Key Vault"
  echo "private endpoint, and stops the PostgreSQL server (its data is kept)."
  echo "Registry, Key Vaults, keys and secrets are kept."
  read -r -p 'Type "teardown" to continue: ' answer
  [[ $answer == teardown ]] || { echo "cancelled"; exit 1; }
fi

az account set --subscription "$SUB"
exists() { az resource show --ids "$1" -o none 2>/dev/null; }
id() { echo "/subscriptions/$SUB/resourceGroups/$1/providers/$2"; }

echo "== 1. remember the running API image"
image=$(az containerapp show -g "$APP_RG" -n "$APP" --query "properties.template.containers[0].image" -o tsv 2>/dev/null | tr -d '\r' || true)
if [[ $image == *@sha256:* ]]; then
  az acr import -n "$ACR" --source "$image" --image saas-job-api:deployed-dev --force -o none
  echo "   saas-job-api:deployed-dev -> ${image##*@}"
else
  echo "   no running API found; rebuild.sh will use the existing deployed-dev tag"
fi

echo "== 2. GitHub: remove SAAS_URL so the plugin workflows skip the upload"
if command -v gh >/dev/null && gh variable list --repo "$GH_REPO" 2>/dev/null | grep -q '^SAAS_URL'; then
  gh variable delete SAAS_URL --repo "$GH_REPO" && echo "   removed"
else
  echo "   not set (or gh not signed in); nothing to do"
fi

echo "== 3. API and jobs"
if exists "$(id "$APP_RG" Microsoft.App/containerApps/$APP)"; then
  az containerapp delete -g "$APP_RG" -n "$APP" --yes -o none && echo "   $APP deleted"
fi
for j in "${JOBS[@]}"; do
  if exists "$(id "$APP_RG" Microsoft.App/jobs/$j)"; then
    az containerapp job delete -g "$APP_RG" -n "$j" --yes -o none && echo "   $j deleted"
  fi
done

echo "== 4. Container Apps environment (load balancer goes with it; ~5-10 min)"
if exists "$(id "$APP_RG" Microsoft.App/managedEnvironments/$ENV)"; then
  az containerapp env delete -g "$APP_RG" -n "$ENV" --yes -o none && echo "   $ENV deleted"
fi

echo "== 5. PostgreSQL server: stop, keep data (~5 min)"
if exists "$(id "$DB_RG" Microsoft.DBforPostgreSQL/flexibleServers/$DB)"; then
  state=$(az postgres flexible-server show -g "$DB_RG" -n "$DB" --query state -o tsv | tr -d '')
  if [[ $state == Ready ]]; then
    az postgres flexible-server stop -g "$DB_RG" -n "$DB" -o none && echo "   $DB stopped"
  else
    echo "   $DB is $state; left as it is"
  fi
fi

echo "== 6. Key Vault private endpoint"
if exists "$(id "$SEC_RG" Microsoft.Network/privateEndpoints/$PE)"; then
  az network private-endpoint delete -g "$SEC_RG" -n "$PE" -o none && echo "   $PE deleted"
fi

echo
echo "Torn down. Database stopped with its data. Left (no hourly charge): registry, Key Vaults, identities, VNet, DNS, Log Analytics."
echo "Azure restarts the stopped database after 7 days ($(date -d '+7 days' +%Y-%m-%d 2>/dev/null || echo 'in 7 days')): run this script again then."
echo "Bring it back:  bash deploy/test-lab/azure/rebuild-lab.sh   (CDE repo; ~30 min)"
