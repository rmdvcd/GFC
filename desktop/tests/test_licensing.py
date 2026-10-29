from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fichacosto.licensing.canonical import canonical_payload
from fichacosto.licensing.licensing_service import LicensingService
from fichacosto.licensing.models import EstadoLicencia


class MemoryRepository:
    def __init__(self):
        self.state = {}
        self.usage = {}

    def license_get_state(self, key):
        return self.state.get(key)

    def license_set_state(self, key, value):
        self.state[key] = value

    def license_get_usage(self, license_id, feature):
        return self.usage.get((license_id, feature), 0)

    def license_consume_quota(self, license_id, feature, limit):
        key = (license_id, feature)
        if self.usage.get(key, 0) >= limit:
            return False
        self.usage[key] = self.usage.get(key, 0) + 1
        return True


class LicensingTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        raw_public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public_b64 = base64.b64encode(raw_public).decode("ascii")
        self.now = [datetime(2026, 10, 28, 12, tzinfo=timezone.utc)]
        self.repo = MemoryRepository()
        self.fingerprint = "a" * 64
        self.service = LicensingService(self.repo, public_key_b64=self.public_b64,
            fingerprint_provider=lambda: self.fingerprint, now_provider=lambda: self.now[0])
        self.payload = {
            "licenseId": str(uuid4()), "producto": "FichaCosto", "tipo": "PRO",
            "titular": {"nombre": "Entidad", "nit": "123", "email": "licencias@example.org"},
            "deviceFingerprint": self.fingerprint,
            "fechaEmision": "2026-10-28T00:00:00Z", "fechaExpiracion": "2027-10-28T00:00:00Z",
            "features": ["fichas", "pdf", "import_export"], "maxFichas": 2,
        }

    def document(self, payload=None):
        payload = payload or self.payload
        signature = self.private.sign(canonical_payload(payload))
        return {"schemaVersion": "1.0.0", "payload": payload,
                "signature": base64.b64encode(signature).decode("ascii")}

    def import_document(self, document):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "license.lic"
            path.write_text(json.dumps(document), encoding="utf-8")
            return self.service.cargar_licencia(path)

    def test_canonical_nfc_and_signature(self):
        self.assertEqual(canonical_payload({"nombre": "Cafe\u0301"}), '{"nombre":"Café"}'.encode())
        result = self.import_document(self.document())
        self.assertEqual(result.estado, EstadoLicencia.VALIDA)

    def test_schema_signature_and_device_rejections(self):
        tampered = self.document()
        tampered["payload"]["tipo"] = "TRIAL"
        self.assertEqual(self.import_document(tampered).estado, EstadoLicencia.FIRMA_INVALIDA)
        self.assertEqual(self.import_document({"schemaVersion": "1.0.0"}).estado, EstadoLicencia.SCHEMA_INVALIDO)
        mismatch = dict(self.payload, deviceFingerprint="b" * 64)
        self.assertEqual(self.import_document(self.document(mismatch)).estado, EstadoLicencia.FINGERPRINT_NO_COINCIDE)

    def test_quota_and_pdf_watermark_state(self):
        self.import_document(self.document())
        self.assertTrue(self.service.consumir_feature("fichas"))
        self.assertTrue(self.service.consumir_feature("fichas"))
        self.assertFalse(self.service.consumir_feature("fichas"))
        self.assertEqual(self.service.estado_actual().fichasRestantes, 0)

    def test_expiration_and_clock_rollback_grace(self):
        expired = dict(self.payload, fechaExpiracion="2026-10-27T00:00:00Z")
        self.assertEqual(self.import_document(self.document(expired)).estado, EstadoLicencia.EXPIRADA)
        # Reinstall a fresh, nonexpired license, establish last_seen and move clock back.
        self.payload["licenseId"] = str(uuid4())
        self.import_document(self.document())
        self.now[0] = datetime(2026, 10, 27, 0, tzinfo=timezone.utc)
        state = self.service.estado_actual()
        self.assertEqual(state.estado, EstadoLicencia.VALIDA)
        self.assertIsNotNone(state.advertencia)
        self.now[0] += timedelta(hours=24)
        self.assertEqual(self.service.estado_actual().estado, EstadoLicencia.EXPIRADA)


if __name__ == "__main__":
    unittest.main()
