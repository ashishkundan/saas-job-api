#!/usr/bin/env bash
# Register (or re-key) a gateway on the Azure SaaS API.
#
#   bash infra/azure/add-gateway.sh <gateway-id> <tenant-id> | <install the token on the gateway>
#
# Generates a new API token, then in the application Key Vault:
#   gateway-tokens-json   drops any old token of <gateway-id>, adds the new one
#   gateway-tenants-json  maps <gateway-id> to <tenant-id>
# and restarts the API revision so it loads the new values.
#
# The token is written to stdout only, and only into a pipe (the script refuses
# a terminal), e.g. straight into `systemd-creds encrypt` on the gateway. It is
# never printed, logged or left on disk.
set -euo pipefail
GW=${1:?gateway id}; TENANT=${2:?tenant id}
VAULT=${VAULT:-kv-cv360-dev}
APP_RG=${APP_RG:-rg-cv360-app-dev}; APP=${APP:-ca-cv360-api-dev}
[[ -t 1 ]] && { echo "stdout is a terminal: pipe the token into the gateway's credential store" >&2; exit 1; }
[[ $GW =~ ^[A-Za-z0-9_.-]+$ && $TENANT =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "bad gateway or tenant id" >&2; exit 1; }
command -v az >/dev/null || { echo "Azure CLI (az) not on PATH" >&2; exit 1; }
PY=
for c in python3 python py; do "$c" -c 'import secrets' 2>/dev/null && { PY=$c; break; }; done
[[ -n $PY ]] || { echo "Python 3 not found" >&2; exit 1; }
export MSYS_NO_PATHCONV=1

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
chmod 700 "$dir"
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
get() { az keyvault secret show --vault-name "$VAULT" -n "$1" --query value -o tsv | tr -d '\r'; }

get gateway-tokens-json >"$dir/tokens"
get gateway-tenants-json >"$dir/tenants"
"$PY" - "$(native "$dir")" "$GW" "$TENANT" <<'EOF'
import json, os, secrets, sys
d, gw, tenant = sys.argv[1:]
tokens = {t: g for t, g in json.load(open(os.path.join(d, "tokens"))).items() if g != gw}
token = secrets.token_urlsafe(32)
tokens[token] = gw
tenants = json.load(open(os.path.join(d, "tenants")))
tenants[gw] = tenant
json.dump(tokens, open(os.path.join(d, "tokens"), "w"))
json.dump(tenants, open(os.path.join(d, "tenants"), "w"))
open(os.path.join(d, "token"), "w").write(token)
EOF
for s in tokens tenants; do
  az keyvault secret set --vault-name "$VAULT" -n "gateway-$s-json" --file "$(native "$dir/$s")" --encoding utf-8 -o none
done
rev=$(az containerapp show -g "$APP_RG" -n "$APP" --query properties.latestRevisionName -o tsv | tr -d '\r')
az containerapp revision restart -g "$APP_RG" -n "$APP" --revision "$rev" -o none
echo "gateway $GW -> tenant $TENANT registered; API revision $rev restarted" >&2
cat "$dir/token"
