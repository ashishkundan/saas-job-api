from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from saas_job_api.certs import CertificateAuthority, InvalidCsrError, generate_ca


def _build_gateway_csr(gateway_id: str, key: Ed25519PrivateKey | None = None) -> tuple[Ed25519PrivateKey, bytes]:
    key = key or Ed25519PrivateKey.generate()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, gateway_id)]))
        .sign(key, algorithm=None)
    )
    return key, csr.public_bytes(Encoding.PEM)


def test_generate_ca_produces_a_self_signed_ca_certificate() -> None:
    key_pem, cert_pem = generate_ca()

    cert = x509.load_pem_x509_certificate(cert_pem)
    basic_constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic_constraints.ca is True
    assert cert.issuer == cert.subject  # self-signed


def test_sign_gateway_csr_issues_a_certificate_that_chains_to_the_ca() -> None:
    key_pem, cert_pem = generate_ca()
    ca = CertificateAuthority(key_pem, cert_pem, validity_days=30)
    _, csr_pem = _build_gateway_csr("gw-test-001")

    cert_pem_out, serial_hex, not_after = ca.sign_gateway_csr(csr_pem, gateway_id="gw-test-001")

    issued = x509.load_pem_x509_certificate(cert_pem_out)
    ca_cert = x509.load_pem_x509_certificate(cert_pem)
    assert issued.issuer == ca_cert.subject
    assert issued.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "gw-test-001"
    assert format(issued.serial_number, "x") == serial_hex
    assert not_after > datetime.now(timezone.utc)
    # The CA's public key must actually verify the issued cert's signature.
    ca_cert.public_key().verify(issued.signature, issued.tbs_certificate_bytes)


def test_sign_gateway_csr_rejects_a_tampered_csr() -> None:
    key_pem, cert_pem = generate_ca()
    ca = CertificateAuthority(key_pem, cert_pem, validity_days=30)

    with pytest.raises(InvalidCsrError):
        ca.sign_gateway_csr(b"not a real csr", gateway_id="gw-bad")


def test_sign_gateway_csr_rejects_a_forged_signature() -> None:
    """A CSR whose signature bytes don't actually match its claimed public
    key must be rejected - proves possession of the private key is checked,
    not just that some signature bytes are present. The last bytes of a
    DER-encoded CSR are its signature (a fixed-length Ed25519 value at a
    known trailing offset), so flipping the final byte corrupts only the
    signature, not the ASN.1 structure/length headers earlier in the blob."""
    key_pem, cert_pem = generate_ca()
    ca = CertificateAuthority(key_pem, cert_pem, validity_days=30)

    _, csr_pem = _build_gateway_csr("gw-forged")
    csr = x509.load_pem_x509_csr(csr_pem)
    assert csr.is_signature_valid  # sanity: the untampered CSR verifies

    der = bytearray(csr.public_bytes(Encoding.DER))
    der[-1] ^= 0xFF
    corrupted_b64 = base64.encodebytes(bytes(der)).decode("ascii")
    corrupted_pem = f"-----BEGIN CERTIFICATE REQUEST-----\n{corrupted_b64}-----END CERTIFICATE REQUEST-----\n".encode("ascii")

    with pytest.raises(InvalidCsrError):
        ca.sign_gateway_csr(corrupted_pem, gateway_id="gw-forged")
