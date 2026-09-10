#!/usr/bin/env python3
"""Issue or explicitly renew Redis leaf certificates into Doppler, without local PEM files."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import re
import secrets
import subprocess
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

INFRA = "infrastructure"
APP = "auth"


def doppler(project, command, value=None):
    result = subprocess.run(["doppler", *command, "--project", project, "--config", "prd", "--no-check-version"],
                            input=value, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("Doppler request failed; output suppressed")
    return result.stdout.strip()


def get(project, key):
    return doppler(project, ["secrets", "get", key, "--plain"])


def name():
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "redis-" + secrets.token_hex(12))])


def new_ca():
    key = ec.generate_private_key(ec.SECP256R1())
    subject = name()
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1095)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False).sign(key, hashes.SHA256()))
    return key, cert


def leaf(ca_key, ca_cert, hostname=None):
    if hostname is not None and not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", hostname):
        raise ValueError("Invalid DNS identity")
    now = datetime.now(timezone.utc)
    if ca_cert.not_valid_after_utc < now + timedelta(days=91):
        raise ValueError("CA requires a separately reviewed rotation")
    key = ec.generate_private_key(ec.SECP256R1())
    purposes = [ExtendedKeyUsageOID.CLIENT_AUTH]
    if hostname:
        purposes.append(ExtendedKeyUsageOID.SERVER_AUTH)
    builder = (x509.CertificateBuilder().subject_name(name()).issuer_name(ca_cert.subject)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
               .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, None, None), True)
               .add_extension(x509.ExtendedKeyUsage(purposes), False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False))
    if hostname:
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.DNSName(hostname), x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
    return key, builder.sign(ca_key, hashes.SHA256())


def pem(pair):
    key, cert = pair
    return {"CERT": cert.public_bytes(serialization.Encoding.PEM).decode(),
            "KEY": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()}


def provision(renew=False):
    existing = {p: set(json.loads(doppler(p, ["secrets", "--only-names", "--json"]))) for p in [INFRA, APP]}
    pairs = [(INFRA, "REDIS_MASTER_TLS", "REDIS_HOST"), (INFRA, "REDIS_REPLICA_TLS", "REDIS_REPLICA_HOST"),
             (INFRA, "REDIS_OPERATIONS_TLS", None), (APP, "REDIS_TLS", None)]
    ca_names = {"REDIS_TLS_CA_CERT", "REDIS_TLS_CA_KEY"}
    if renew:
        assert ca_names <= existing[INFRA], "Missing CA; do not replace it implicitly"
        ca_key = serialization.load_pem_private_key(get(INFRA, "REDIS_TLS_CA_KEY").encode(), password=None)
        ca_cert = x509.load_pem_x509_certificate(get(INFRA, "REDIS_TLS_CA_CERT").encode())
        assert ca_key.public_key().public_numbers() == ca_cert.public_key().public_numbers(), "CA mismatch"
        assert ca_cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    else:
        assert not (ca_names & existing[INFRA]), "CA already exists; use explicit leaf renewal"
        for project, prefix, _ in pairs:
            assert not ({prefix + "_CERT", prefix + "_KEY"} & existing[project]), "Existing certificate requires review"
        assert "REDIS_TLS_CA_CERT" not in existing[APP], "Existing app CA requires review"
        ca_key, ca_cert = new_ca()
    # Prepare every certificate before the first external write. No CA private key enters Kubernetes.
    pending = []
    for project, prefix, host_key in pairs:
        for suffix, value in pem(leaf(ca_key, ca_cert, get(INFRA, host_key) if host_key else None)).items():
            pending.append((project, prefix + "_" + suffix, value))
    if not renew:
        for suffix, value in pem((ca_key, ca_cert)).items():
            doppler(INFRA, ["secrets", "set", "REDIS_TLS_CA_" + suffix, "--no-interactive"], value)
    for project, key, value in pending:
        doppler(project, ["secrets", "set", key, "--no-interactive"], value)
    doppler(APP, ["secrets", "set", "REDIS_TLS_CA_CERT", "--no-interactive"], "${infrastructure.prd.REDIS_TLS_CA_CERT}")
    assert get(APP, "REDIS_TLS_CA_CERT") == get(INFRA, "REDIS_TLS_CA_CERT"), "CA reference unresolved"
    print(json.dumps({"leaf_certificates": 4, "leaf_valid_days": 90, "ca_reused": renew,
                      "private_files_written": False, "deployment_performed": False}))


def check():
    ca = x509.load_pem_x509_certificate(get(INFRA, "REDIS_TLS_CA_CERT").encode())
    now = datetime.now(timezone.utc)
    remaining = []
    for project, prefix, host_key in [(INFRA, "REDIS_MASTER_TLS", "REDIS_HOST"),
            (INFRA, "REDIS_REPLICA_TLS", "REDIS_REPLICA_HOST"), (INFRA, "REDIS_OPERATIONS_TLS", None), (APP, "REDIS_TLS", None)]:
        cert = x509.load_pem_x509_certificate(get(project, prefix + "_CERT").encode())
        key = serialization.load_pem_private_key(get(project, prefix + "_KEY").encode(), password=None)
        cert.verify_directly_issued_by(ca)
        assert cert.public_key().public_numbers() == key.public_key().public_numbers()
        assert cert.not_valid_before_utc <= now < cert.not_valid_after_utc
        days = (cert.not_valid_after_utc - now).days
        assert days >= 30, "Renewal due"
        remaining.append(days)
        purposes = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert ExtendedKeyUsageOID.CLIENT_AUTH in purposes
        if host_key:
            assert ExtendedKeyUsageOID.SERVER_AUTH in purposes
            assert get(INFRA, host_key) in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        else:
            assert ExtendedKeyUsageOID.SERVER_AUTH not in purposes
    assert get(APP, "REDIS_TLS_CA_CERT") == get(INFRA, "REDIS_TLS_CA_CERT")
    print(json.dumps({"certificate_pairs_verified": 4, "minimum_remaining_days": min(remaining), "values_displayed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write", action="store_true")
    actions.add_argument("--check", action="store_true")
    parser.add_argument("--renew-leaves", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            assert not args.renew_leaves
            check()
        else:
            provision(args.renew_leaves)
    except Exception:
        raise SystemExit("PKI preparation failed; private details suppressed. Inspect key presence before retrying.")
