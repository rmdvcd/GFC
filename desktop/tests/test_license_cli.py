from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tools.license_generator import cli
from fichacosto.licensing.canonical import schema_path


class LicenseCliTests(unittest.TestCase):
    def test_keygen_issue_verify_and_revoke_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, public = root / "signing.pem", root / "public.b64"
            embed_py, embed_dart = root / "public_key.py", root / "public_key.dart"
            with patch.object(cli.getpass, "getpass", side_effect=["safe password 123", "safe password 123"]):
                cli.cmd_keygen(Namespace(private_key=private, public_key=public, embed_python=embed_py,
                                        embed_dart=embed_dart, force=False))
            self.assertTrue(private.read_bytes().startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"))
            self.assertNotIn("PRIVATE", embed_py.read_text())
            self.assertIn("licensePublicKeyB64", embed_dart.read_text())
            payload = {
                "licenseId": str(uuid4()), "producto": "FichaCosto", "tipo": "PRO",
                "titular": {"nombre": "Entidad", "nit": "123", "email": "lic@example.org"},
                "deviceFingerprint": "a" * 64, "fechaEmision": "2026-10-28T12:00:00Z",
                "fechaExpiracion": None, "features": ["fichas", "pdf"], "maxFichas": 10,
            }
            payload_path, license_path, revocations_path = root / "payload.json", root / "customer.lic", root / "revocations.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(cli.getpass, "getpass", return_value="safe password 123"):
                cli.cmd_issue(Namespace(payload=payload_path, private_key=private, output=license_path, schema=schema_path()))
            cli.cmd_verify(Namespace(license=license_path, public_key=public, revocations=None, schema=schema_path()))
            with patch.object(cli.getpass, "getpass", return_value="safe password 123"):
                cli.cmd_revoke(Namespace(license_id=payload["licenseId"], private_key=private, existing=None, output=revocations_path))
            with self.assertRaisesRegex(ValueError, "revocada"):
                cli.cmd_verify(Namespace(license=license_path, public_key=public, revocations=revocations_path, schema=schema_path()))

    def test_refuses_signing_key_inside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "fuera del repositorio"):
                cli.cmd_keygen(Namespace(private_key=cli.ROOT / "unsafe-private-key.pem",
                    public_key=Path(directory) / "pub.b64", embed_python=None, embed_dart=None, force=False))


if __name__ == "__main__":
    unittest.main()
