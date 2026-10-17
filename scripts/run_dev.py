"""Run the reference SaaS Job API locally with sensible dev defaults.

    python scripts/run_dev.py

Then, from the parent repo, point HttpJobSource at:
    poll_url="http://127.0.0.1:8000/gateway/v1/jobs/poll"
    api_token="dev-gateway-token"

The dev gateway (gw_dev_local) belongs to tenant "tenant-dev", and every job
is created for one of that tenant's managed Targets. Example smoke test:

    TOKEN=$(curl -s -X POST http://127.0.0.1:8000/admin/v1/login -H "Content-Type: application/json"       -d '{"username": "dev-admin", "password": "dev-admin-password"}' | python -c "import json,sys; print(json.load(sys.stdin)['accessToken'])")
    curl -X POST http://127.0.0.1:8000/admin/v1/tenants -H "Authorization: Bearer $TOKEN"       -H "Content-Type: application/json" -d '{"tenantId": "tenant-dev", "name": "Dev"}'
    curl -X POST http://127.0.0.1:8000/admin/v1/tenants/tenant-dev/targets -H "Authorization: Bearer $TOKEN"       -H "Content-Type: application/json"       -d '{"targetId": "dev-target", "name": "dev", "host": "127.0.0.1", "port": 443, "pluginRef": "tls-scanner", "pluginVersion": "1.0"}'

    curl -X POST http://127.0.0.1:8000/admin/jobs       -H "X-Admin-Token: dev-admin-token" -H "Content-Type: application/json"       -d '{"tenantId": "tenant-dev", "targetId": "dev-target"}'

    curl -X POST http://127.0.0.1:8000/gateway/v1/jobs/poll       -H "Authorization: Bearer dev-gateway-token" -H "Content-Type: application/json"       -d '{"maxJobs": 5}'
"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    # Dev-only bootstrap admin so the tenant/target admin API is usable
    # out of the box; an explicitly set environment always wins.
    os.environ.setdefault("SAAS_JOB_API_BOOTSTRAP_ADMIN_USERNAME", "dev-admin")
    os.environ.setdefault("SAAS_JOB_API_BOOTSTRAP_ADMIN_PASSWORD", "dev-admin-password")
    uvicorn.run("saas_job_api.main:app", host="127.0.0.1", port=8000, reload=True)
