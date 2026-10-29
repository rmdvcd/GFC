from __future__ import annotations

import base64
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fichacosto.licensing.canonical import canonical_payload
from fichacosto.backup.backup_service import BackupArchiveCorrupt, BackupPasswordOrDataError, BackupService
from fichacosto.dominio import FichaCosto, Importe, Insumo, Moneda, TarifaSalario
from fichacosto.repositorio import RepositorioFichas


class BackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fingerprint = "a" * 64
        self.source = RepositorioFichas(self.root / "source.db", "source-key")
        self.service = BackupService(self.source, fingerprint_provider=lambda: self.fingerprint,
                                     output_dir=self.root / "backups")
        ficha = FichaCosto(nombre="Mesa", descripcion="Madera", partidas=[])
        self.source.guardar_ficha(ficha.a_json())
        self.source.guardar_catalogo("insumo", {"id": "d1a4e2bb-11b4-4750-90ab-319d48f87c10", "nombre": "Madera", "unidadMedida": "m", "costoUnitario": {"valor": 12.0, "moneda": "CUP"}})
        self.source.guardar_catalogo("tarifa", {"id": "d1a4e2bb-11b4-4750-90ab-319d48f87c11", "cargo": "Carpintero", "unidadTarifa": "hora", "tarifa": {"valor": 5, "moneda": "CUP"}})
        license_payload = {"licenseId": str(uuid4()), "producto": "FichaCosto", "tipo": "PRO",
            "titular": {"nombre": "Entidad", "nit": "123", "email": "lic@example.org"},
            "deviceFingerprint": self.fingerprint, "fechaEmision": "2026-10-28T12:00:00Z",
            "fechaExpiracion": None, "features": ["fichas", "pdf"], "maxFichas": 10}
        signing_key = Ed25519PrivateKey.generate()
        signature = base64.b64encode(signing_key.sign(canonical_payload(license_payload))).decode("ascii")
        license_document = {"schemaVersion": "1.0.0", "payload": license_payload, "signature": signature}
        self.source.license_set_state("license_document", json.dumps(license_document))
        self.source.license_set_state("last_seen_ts", "2026-10-28T14:00:00Z")
        self.source.license_consume_quota("72ab6b6c-f55e-4ff0-99cf-2b5fb6bb8231", "fichas", 10)
        self.source.db.execute("INSERT INTO preferences (key, value_json) VALUES (?, ?)", ("theme", '"dark"'))
        self.source.db.commit()

    def tearDown(self):
        self.source.cerrar()
        self.temp.cleanup()

    def test_create_preview_and_restore_into_empty_database(self):
        archive_path = self.service.crear_backup("correct horse battery", self.root / "client.ficha148.bak")
        with zipfile.ZipFile(archive_path) as zf:
            self.assertEqual(set(zf.namelist()), {"ficha148_backup_v1/manifest.json", "ficha148_backup_v1/payload.enc"})
            manifest = json.loads(zf.read("ficha148_backup_v1/manifest.json"))
            self.assertEqual(manifest["kdf"], {"algoritmo": "argon2id", "salt": manifest["kdf"]["salt"], "memory": 65536, "iterations": 3, "parallelism": 4})
            self.assertNotIn(b"Mesa", zf.read("ficha148_backup_v1/payload.enc"))
            self.assertNotIn("Mesa", zf.read("ficha148_backup_v1/manifest.json").decode())
        preview = self.service.previsualizar_backup(archive_path, "correct horse battery")
        self.assertEqual((preview.fichas, preview.insumos, preview.salarios), (1, 1, 1))
        self.assertTrue(preview.origen_diferente is False)
        target = RepositorioFichas(self.root / "target.db", "target-key")
        target_service = BackupService(target, fingerprint_provider=lambda: "b" * 64, output_dir=self.root / "target-backups")
        target_preview = target_service.previsualizar_backup(archive_path, "correct horse battery")
        self.assertTrue(target_preview.origen_diferente)
        self.assertTrue(target_preview.incluye_licencia)
        result = target_service.aplicar_restauracion(target_preview, modo="reemplazar", restaurar_licencia=False, restaurar_usage=True)
        self.assertEqual(result.fichas_restauradas, 1)
        self.assertEqual(len(target.listar_fichas()), 1)
        self.assertEqual(target.listar_catalogo("insumo")[0]["nombre"], "Madera")
        self.assertEqual(target.listar_catalogo("tarifa")[0]["cargo"], "Carpintero")
        self.assertIsNone(target.license_get_state("license_document"))
        self.assertEqual(target.license_get_usage("72ab6b6c-f55e-4ff0-99cf-2b5fb6bb8231", "fichas"), 1)
        self.assertEqual(json.loads(target.db.execute("SELECT value_json FROM preferences WHERE key='theme'").fetchone()[0]), "dark")
        self.assertIsNotNone(result.respaldo_seguridad)
        self.assertIsNone(target.license_get_state("license_document"))
        target_service.aplicar_restauracion(target_preview, modo="fusionar", restaurar_licencia=True)
        self.assertIsNotNone(target.license_get_state("license_document"))
        target.cerrar()

    def test_wrong_password_and_corruption_do_not_touch_database(self):
        archive_path = self.service.crear_backup("correct horse battery", self.root / "client.ficha148.bak")
        with self.assertRaises(BackupPasswordOrDataError):
            self.service.previsualizar_backup(archive_path, "wrong password")
        raw = archive_path.read_bytes()
        damaged = self.root / "damaged.ficha148.bak"
        with zipfile.ZipFile(BytesIO(raw)) as source, zipfile.ZipFile(damaged, "w", compression=zipfile.ZIP_STORED) as dest:
            for name in source.namelist():
                value = source.read(name)
                if name.endswith("payload.enc"):
                    value = value[:-1] + bytes([value[-1] ^ 1])
                dest.writestr(name, value)
        with self.assertRaises(BackupPasswordOrDataError):
            self.service.previsualizar_backup(damaged, "correct horse battery")
        with self.assertRaises(BackupArchiveCorrupt):
            self.service.previsualizar_backup(self.root / "missing.zip", "correct horse battery")
        self.assertEqual(len(self.source.listar_fichas()), 1)

    def test_failed_replace_is_atomic_and_keeps_recovery_backup(self):
        archive_path = self.service.crear_backup("correct horse battery", self.root / "replace.ficha148.bak")
        preview = self.service.previsualizar_backup(archive_path, "correct horse battery")
        target = RepositorioFichas(self.root / "replace.db", "replace-key")
        existing = FichaCosto(nombre="Datos locales previos")
        target.guardar_ficha(existing.a_json())
        target_service = BackupService(target, fingerprint_provider=lambda: self.fingerprint, output_dir=self.root / "recovery")
        def fail_after_delete(*_args):
            raise RuntimeError("forced insert failure")
        target_service._insert_records = fail_after_delete
        with self.assertRaisesRegex(ValueError, "restauración se revirtió"):
            target_service.aplicar_restauracion(preview, modo="reemplazar")
        self.assertEqual([x["ficha"]["nombre"] for x in target.listar_fichas()], ["Datos locales previos"])
        del target_service._insert_records
        recovered = target_service.restaurar_respaldo_seguridad()
        self.assertEqual(recovered.fichas_restauradas, 1)
        self.assertEqual([x["ficha"]["nombre"] for x in target.listar_fichas()], ["Datos locales previos"])
        target.cerrar()

    def test_merge_keeps_newer_existing_ficha(self):
        archive_path = self.service.crear_backup("correct horse battery", self.root / "merge.ficha148.bak")
        preview = self.service.previsualizar_backup(archive_path, "correct horse battery")
        target = RepositorioFichas(self.root / "merge.db", "merge-key")
        incoming = preview.payload["fichas"][0]
        incoming["ficha"]["fechaActualizacion"] = "2020-01-01T00:00:00Z"
        # Keep the authenticated preview's data schema-valid; the merge uses updated date ordering.
        target.guardar_ficha(incoming)
        original_name = target.obtener_ficha(incoming["ficha"]["id"])["ficha"]["nombre"]
        target_service = BackupService(target, fingerprint_provider=lambda: self.fingerprint, output_dir=self.root / "merge-backups")
        target_service.aplicar_restauracion(preview, modo="fusionar")
        self.assertEqual(target.obtener_ficha(incoming["ficha"]["id"])["ficha"]["nombre"], original_name)
        target.cerrar()


if __name__ == "__main__":
    unittest.main()
