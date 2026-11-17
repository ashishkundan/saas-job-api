#!/usr/bin/env bash
# Revoke a gateway on the Azure SaaS API (the reverse of add-gateway.sh).
#
#   bash infra/azure/remove-gateway.sh <gateway-id>
#
# Removes every token of <gateway-id> from gateway-tokens-json and its entry
# from gateway-tenants-json in the application Key Vault, then restarts the
# API revision so the token stops working. Prints no secret.
set -euo pipefail
GW=${1:?gateway id}
VAULT=${VAULT:-kv-cv360-dev}
APP_RG=${APP_RG:-rg-cv360-app-dev}; APP=${APP:-ca-cv360-api-dev}
[[ $GW =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "bad gateway id" >&2; exit 1; }
PY=
for c in python3 python py; do "$c" -c 'import json' 2>/dev/null && { PY=$c; break; }; done
[[ -n $PY ]] || { echo "Python 3 not found" >&2; exit 1; }
export MSYS_NO_PATHCONV=1
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
chmod 700 "$dir"
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
get() { az keyvault secret show --vault-name "$VAULT" -n "$1" --query value -o tsv | tr -d '\r'; }
get gateway-tokens-json >"$dir/tokens"
get gateway-tenants-json >"$dir/tenants"
removed=$("$PY" - "$(native "$dir")" "$GW" <<'EOF'
import json, os, sys
d, gw = sys.argv[1:]
tokens = json.load(open(os.path.join(d, "tokens")))
tenants = json.load(open(os.path.join(d, "tenants")))
kept = {t: g for t, g in tokens.items() if g != gw}
removed = len(tokens) - len(kept)
had_tenant = tenants.pop(gw, None) is not None
json.dump(kept, open(os.path.join(d, "tokens"), "w"))
json.dump(tenants, open(os.path.join(d, "tenants"), "w"))
print(removed if (removed or had_tenant) else "none")
EOF
)
if [[ $removed == none ]]; then echo "gateway $GW is not registered; nothing to do" >&2; exit 0; fi
for s in tokens tenants; do
  az keyvault secret set --vault-name "$VAULT" -n "gateway-$s-json" --file "$(native "$dir/$s")" --encoding utf-8 -o none
done
rev=$(az containerapp show -g "$APP_RG" -n "$APP" --query properties.latestRevisionName -o tsv | tr -d '\r')
az containerapp revision restart -g "$APP_RG" -n "$APP" --revision "$rev" -o none
echo "gateway $GW removed ($removed token(s)); API revision $rev restarted" >&2
