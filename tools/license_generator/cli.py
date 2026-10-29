"""Internal offline license generator. Keep the encrypted signing key outside the app repo."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop" / "src"))
from fichacosto.licensing.canonical import canonical_payload, schema_path, validate_license, verify_payload_signature  # noqa: E402


def _strict_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Clave JSON duplicada: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Número JSON no permitido: {value}")))


def _write_private(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _private_key(path: Path) -> Ed25519PrivateKey:
    password = getpass.getpass("Contraseña de la clave privada: ").encode("utf-8")
    key = serialization.load_pem_private_key(path.read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("El archivo no contiene una clave Ed25519")
    return key


def _public_bytes(path: Path) -> bytes:
    data = path.read_bytes().strip()
    try:
        key = serialization.load_pem_public_key(data)
        if isinstance(key, Ed25519PublicKey):
            return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    except (ValueError, TypeError):
        pass
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        raw = data
    if len(raw) != 32:
        raise ValueError("La clave pública debe ser Ed25519 en PEM, Base64 o 32 bytes raw")
    return raw


def cmd_keygen(args):
    args.private_key = args.private_key.expanduser()
    args.public_key = args.public_key.expanduser()
    if args.embed_python:
        args.embed_python = args.embed_python.expanduser()
    if args.embed_dart:
        args.embed_dart = args.embed_dart.expanduser()
    private_path = args.private_key.resolve()
    try:
        private_path.relative_to(ROOT.resolve())
        raise ValueError("Por seguridad, la clave privada debe guardarse fuera del repositorio.")
    except ValueError as exc:
        if str(exc).startswith("Por seguridad"):
            raise
    if (args.private_key.exists() or args.public_key.exists()) and not args.force:
        raise ValueError("Ya existe un archivo de clave; use otro destino o indique --force tras respaldar la clave anterior.")
    first = getpass.getpass("Nueva contraseña de la clave privada: ")
    second = getpass.getpass("Repita la contraseña: ")
    if len(first) < 12 or first != second:
        raise ValueError("Las contraseñas deben coincidir y tener al menos 12 caracteres")
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.BestAvailableEncryption(first.encode("utf-8")))
    public_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_b64 = base64.b64encode(public_raw).decode("ascii")
    _write_private(args.private_key, private_pem)
    args.public_key.parent.mkdir(parents=True, exist_ok=True)
    args.public_key.write_text(public_b64 + "\n", encoding="ascii")
    if args.embed_python:
        args.embed_python.parent.mkdir(parents=True, exist_ok=True)
        args.embed_python.write_text('"""Generated public key. This is not a signing secret."""\nPUBLIC_KEY_B64 = "' + public_b64 + '"\n', encoding="utf-8")
    if args.embed_dart:
        args.embed_dart.parent.mkdir(parents=True, exist_ok=True)
        args.embed_dart.write_text("// Generated public key. This is not a signing secret.\nconst licensePublicKeyB64 = '" + public_b64 + "';\n", encoding="utf-8")
    print(f"Clave privada cifrada: {args.private_key}\nClave pública: {args.public_key}\nHuella de clave pública (SHA-256): {__import__('hashlib').sha256(public_raw).hexdigest()}")


def cmd_issue(args):
    payload = _strict_json(args.payload)
    if not isinstance(payload, dict):
        raise ValueError("El payload debe ser un objeto JSON")
    # Force canonicalization before signing: rejects floats and invalid value types.
    canonical_payload(payload)
    UUID(str(payload.get("licenseId", "")))
    document = {"schemaVersion": "1.0.0", "payload": payload, "signature": "A" * 88}
    errors = validate_license(document, args.schema)
    if errors:
        raise ValueError("Payload no válido según schema v1:\n" + "\n".join("• " + error for error in errors))
    key = _private_key(args.private_key)
    signature = key.sign(canonical_payload(payload))
    document["signature"] = base64.b64encode(signature).decode("ascii")
    errors = validate_license(document, args.schema)
    if errors:
        raise ValueError("El documento final no cumple schema: " + "; ".join(errors))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Licencia emitida: {args.output}")


def _verify_revocations(path: Path | None, public: bytes) -> set[str]:
    if path is None:
        return set()
    doc = _strict_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict):
        raise ValueError("Manifiesto de revocación no válido")
    payload = doc["payload"]
    try:
        signature = base64.b64decode(doc["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_payload(payload))
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise ValueError("Firma del manifiesto de revocación no válida") from exc
    if payload.get("manifestType") != "FichaCostoRevocationsV1" or not isinstance(payload.get("revokedLicenseIds"), list):
        raise ValueError("Schema del manifiesto de revocación no válido")
    return set(payload["revokedLicenseIds"])


def cmd_verify(args):
    document = _strict_json(args.license)
    public = _public_bytes(args.public_key)
    errors = validate_license(document, args.schema)
    if errors:
        raise ValueError("Schema inválido:\n" + "\n".join(errors))
    if not verify_payload_signature(document, public):
        raise ValueError("Firma Ed25519 no válida")
    revoked = _verify_revocations(args.revocations, public)
    license_id = document["payload"]["licenseId"]
    if license_id in revoked:
        raise ValueError(f"Licencia revocada: {license_id}")
    print(f"Licencia válida: {license_id}")


def cmd_revoke(args):
    key = _private_key(args.private_key)
    license_id = str(UUID(args.license_id))
    revoked = set()
    if args.existing and args.existing.exists():
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        revoked = _verify_revocations(args.existing, public)
    revoked.add(license_id)
    payload = {"manifestType": "FichaCostoRevocationsV1", "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "revokedLicenseIds": sorted(revoked)}
    signature = base64.b64encode(key.sign(canonical_payload(payload))).decode("ascii")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"payload": payload, "signature": signature}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifiesto firmado creado: {args.output}. Solo tendrá efecto en dispositivos a los que se entregue/importen este archivo.")


def parser():
    root = argparse.ArgumentParser(prog="fichacosto-license", description="Herramienta interna de licencias offline Ed25519")
    sub = root.add_subparsers(dest="command", required=True)
    keygen = sub.add_parser("keygen", help="crear par Ed25519 (privada cifrada con contraseña)")
    keygen.add_argument("--private-key", type=Path, default=Path.home() / ".config" / "fichacosto" / "license_signing_key.pem")
    keygen.add_argument("--public-key", type=Path, default=Path("public_key.b64"))
    keygen.add_argument("--embed-python", type=Path)
    keygen.add_argument("--embed-dart", type=Path)
    keygen.add_argument("--force", action="store_true", help="sobrescribir archivos existentes después de respaldar la clave anterior")
    keygen.set_defaults(func=cmd_keygen)
    issue = sub.add_parser("issue", help="firmar payload JSON y producir archivo .lic")
    issue.add_argument("--payload", type=Path, required=True)
    issue.add_argument("--private-key", type=Path, required=True)
    issue.add_argument("--output", type=Path, required=True)
    issue.add_argument("--schema", type=Path, default=schema_path())
    issue.set_defaults(func=cmd_issue)
    verify = sub.add_parser("verify", help="validar schema, firma y revocación")
    verify.add_argument("--license", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)
    verify.add_argument("--revocations", type=Path)
    verify.add_argument("--schema", type=Path, default=schema_path())
    verify.set_defaults(func=cmd_verify)
    revoke = sub.add_parser("revoke", help="crear/actualizar manifiesto firmado de revocaciones")
    revoke.add_argument("--license-id", required=True)
    revoke.add_argument("--private-key", type=Path, required=True)
    revoke.add_argument("--existing", type=Path)
    revoke.add_argument("--output", type=Path, required=True)
    revoke.set_defaults(func=cmd_revoke)
    return root


def main():
    args = parser().parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
