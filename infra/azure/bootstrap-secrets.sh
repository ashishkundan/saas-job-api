#!/usr/bin/env bash
# First-time application secrets for the SaaS API on Azure (idempotent).
#
# Generates random values straight into the application Key Vault. Nothing is
# printed, passed on a command line or left on disk (values go through a
# private temp file that is removed). Existing secrets are never overwritten:
# rotate one deliberately with `az keyvault secret set`.
#
#   bash infra/azure/bootstrap-secrets.sh [vault-name]
#
# Secrets: postgres-admin-password, admin-token, jwt-secret,
# gateway-tokens-json ({} - add gateways later), gateway-tenants-json ({}).
# database-url is written by the Bicep deployment (it needs the server name).
set -euo pipefail
VAULT=${1:-kv-cv360-dev}
command -v az >/dev/null || { echo "Azure CLI (az) not on PATH" >&2; exit 1; }
PY=
for c in python3 python py; do "$c" -c 'import secrets' 2>/dev/null && { PY=$c; break; }; done
[[ -n $PY ]] || { echo "Python 3 not found" >&2; exit 1; }
export MSYS_NO_PATHCONV=1   # Git Bash: keep /subscriptions/... scopes intact

me=$(az ad signed-in-user show --query id -o tsv | tr -d '\r')
vault_id=$(az keyvault show -n "$VAULT" --query id -o tsv | tr -d '\r')
# Key Vault Secrets Officer for the operator, so the secrets can be created.
az role assignment create --assignee-object-id "$me" --assignee-principal-type User \
  --role b86a8fe4-44ce-4948-aee5-eccb2c155cd7 --scope "$vault_id" -o none
# Lets `az.getSecret` in the parameters file read the PostgreSQL password.
# Azure requires the trusted-services bypass for that; with the dev vault's
# defaultAction=Allow it does not widen access.
az keyvault update -n "$VAULT" --enabled-for-template-deployment true --bypass AzureServices -o none

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
# Windows az (Git Bash) cannot open /tmp/...; give it the native path.
tmp_arg=$tmp
command -v cygpath >/dev/null && tmp_arg=$(cygpath -w "$tmp")

put() {  # put <name> <python expression producing the value>
  if az keyvault secret show --vault-name "$VAULT" -n "$1" -o none 2>/dev/null; then
    echo "  = $1 (exists, kept)"; return
  fi
  "$PY" -c "import secrets, string, sys; sys.stdout.write($2)" >"$tmp"
  local err
  for _ in 1 2 3 4 5 6; do   # a new role assignment can take a minute to apply
    err=$(az keyvault secret set --vault-name "$VAULT" -n "$1" --file "$tmp_arg" --encoding utf-8 -o none 2>&1) \
      && { echo "  + $1"; return; }
    sleep 20
  done
  echo "  ! could not write $1: $err" >&2; exit 1
}

echo "secrets in $VAULT:"
# Letters and digits only: safe inside the database URL without escaping.
put postgres-admin-password "''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))"
put admin-token "secrets.token_urlsafe(32)"
put jwt-secret "secrets.token_urlsafe(48)"
put gateway-tokens-json "'{}'"
put gateway-tenants-json "'{}'"
