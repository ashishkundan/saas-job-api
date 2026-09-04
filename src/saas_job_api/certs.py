"""Minimal X.509 CA for issuing short-lived Gateway mTLS client certificates.

Open question #2 (Gateway VM implementation plan) locked on mTLS over a
bearer token: registration issues a short-lived, renewable client
certificate. The Registration Agent's Ed25519 keypair (Gateway VM 1.1b)
becomes the basis of a CSR rather than just an identity marker; the SaaS
side here signs it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID


class InvalidCsrError(ValueError):
    """CSR signature does not verify, or the CSR is otherwise malformed."""


class CertificateAuthority:
    """Verifies and signs Gateway CSRs into short-lived client certificates."""

    def __init__(self, ca_key_pem: bytes, ca_cert_pem: bytes, *, validity_days: int) -> None:
        self._ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
        self._ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        self.validity_days = validity_days

    @property
    def ca_certificate_pem(self) -> bytes:
        return self._ca_cert.public_bytes(serialization.Encoding.PEM)

    def sign_gateway_csr(self, csr_pem: bytes, *, gateway_id: str) -> tuple[bytes, str, datetime]:
        """Verify a CSR's self-signature and issue a short-lived client cert.

        Returns (certificate_pem, serial_hex, not_after).
        Raises InvalidCsrError if the CSR is malformed or its self-signature
        doesn't verify (i.e. the requester doesn't actually hold the private
        key matching the public key it's presenting).
        """
        try:
            csr = x509.load_pem_x509_csr(csr_pem)
        except ValueError as exc:
            raise InvalidCsrError("malformed CSR") from exc
        if not csr.is_signature_valid:
            raise InvalidCsrError("CSR signature does not verify")

        now = datetime.now(timezone.utc)
        not_after = now + timedelta(days=self.validity_days)
        serial = x509.random_serial_number()

        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, gateway_id)]))
            .issuer_name(self._ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(serial)
            .not_valid_before(now)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            # Ed25519 (EdDSA) signing requires algorithm=None - the hash is
            # fixed by the signature scheme itself, not chosen separately.
            .sign(self._ca_key, algorithm=None)
        )
        pem = certificate.public_bytes(serialization.Encoding.PEM)
        return pem, format(serial, "x"), not_after


def generate_ca(*, common_name: str = "CertVision360 Gateway CA", validity_days: int = 3650) -> tuple[bytes, bytes]:
    """Generate a new self-signed CA keypair+cert.

    Production deployments must configure a persistent CA (settings.ca_*_pem)
    - every restart with no configured CA generates a *new* one, invalidating
    every previously-issued gateway certificate. This is only safe for
    dev/test, where main.py falls back to it with a startup warning.
    """
    key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, algorithm=None)
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem
