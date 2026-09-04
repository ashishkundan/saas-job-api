"""Abstract base class for certificate inventory storage (Phase 2.6)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .inventory import CertificateRecord, SubmitResultOutcome


class InventoryStoreBase(ABC):
    @abstractmethod
    async def submit_result(
        self,
        *,
        job_id: str,
        attempt_token: str,
        tenant_id: str | None,
        target_id: str | None,
        plugin_id: str,
        plugin_version: str,
        certificates: list[dict[str, Any]],
        received_at: datetime,
    ) -> SubmitResultOutcome:
        """Idempotently record one job's result. If (job_id, attempt_token)
        was already submitted, returns dedupe=True and the previously
        recorded record_count without inserting anything new - safe to
        call on every retried/duplicate POST. `certificates` entries carry
        subject/issuer/serialNumber/validFrom/validTo/fingerprint (the
        Developer Implementation Guide §17/18 shape, camelCase, as the
        Gateway's plugin container output already validates it)."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str, *, limit: int) -> list[CertificateRecord]:
        """Certificate inventory for one tenant - the cross-tenant
        isolation boundary later exit criteria check against."""
