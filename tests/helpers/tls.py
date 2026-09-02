"""Throwaway PKI for the e2e suite: a private CA and the server certificates it
issues.

Used by the custom-CA test, which needs a TLS endpoint that no public trust
store accepts, so a successful connection can only come from the CA bundle the
test mounted into Infrahub.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Long enough that a slow session never trips over expiry, short enough that a
# key leaked from a test log is worthless.
VALIDITY_DAYS = 7


@dataclass(frozen=True)
class CertificateAuthority:
    """A self-signed CA plus the material needed to issue certificates from it."""

    certificate: x509.Certificate
    private_key: rsa.RSAPrivateKey

    @property
    def pem(self) -> str:
        """The CA certificate in PEM form — what goes into a CA bundle."""
        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()


@dataclass(frozen=True)
class ServerCertificate:
    """A leaf certificate and its key, both PEM-encoded, ready for a TLS Secret."""

    certificate_pem: str
    private_key_pem: str


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_certificate_authority(common_name: str) -> CertificateAuthority:
    """Generate a self-signed CA."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=5))
        .not_valid_after(_now() + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
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
        .sign(private_key, hashes.SHA256())
    )
    return CertificateAuthority(certificate=certificate, private_key=private_key)


def issue_server_certificate(
    authority: CertificateAuthority, common_name: str, dns_names: list[str]
) -> ServerCertificate:
    """Issue a server certificate for ``dns_names`` from ``authority``.

    Every name a client may use must be in the SAN list: git verifies the
    hostname from the URL against it, so the in-cluster Service name and its
    fully-qualified forms all have to be present.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(authority.certificate.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=5))
        .not_valid_after(_now() + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in dns_names]),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(authority.private_key, hashes.SHA256())
    )
    return ServerCertificate(
        certificate_pem=certificate.public_bytes(serialization.Encoding.PEM).decode(),
        private_key_pem=private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
    )


def service_dns_names(service: str, namespace: str) -> list[str]:
    """Every name a pod in ``namespace`` can use to reach ``service``."""
    return [
        service,
        f"{service}.{namespace}",
        f"{service}.{namespace}.svc",
        f"{service}.{namespace}.svc.cluster.local",
    ]
