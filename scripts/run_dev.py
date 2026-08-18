"""Run the reference SaaS Job API locally with sensible dev defaults.

    python scripts/run_dev.py

Then, from the parent repo, point HttpJobSource at:
    poll_url="http://127.0.0.1:8000/gateway/v1/jobs/poll"
    api_token="dev-gateway-token"

Example manual smoke test:
    curl -X POST http://127.0.0.1:8000/admin/jobs \
      -H "X-Admin-Token: dev-admin-token" -H "Content-Type: application/json" \
      -d '{"jobType": "TLS_SCAN", "manifestVersion": "1.0"}'

    curl -X POST http://127.0.0.1:8000/gateway/v1/jobs/poll \
      -H "Authorization: Bearer dev-gateway-token" -H "Content-Type: application/json" \
      -d '{"maxJobs": 5}'
"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("saas_job_api.main:app", host="127.0.0.1", port=8000, reload=True)
