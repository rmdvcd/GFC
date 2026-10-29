import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fichacosto.cli import ejemplo
from fichacosto.ficha148_validator import Ficha148ValidationError, Ficha148Validator, ZIP_ERROR
from fichacosto.intercambio import exportar_ficha
from fichacosto.servicios import importar as importar_a_base


class Ficha148ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = Ficha148Validator()

    def test_recolecta_y_traduce_errores_semanticos(self):
        document = ejemplo()
        document["ficha"]["nombre"] = ""
        document["ficha"]["partidas"][0]["costoUnitario"]["valor"] = "texto"
        document["ficha"]["partidas"][0]["fechaInventada"] = "no"
        messages = self.validator.validar_documento(document)
        self.assertGreaterEqual(len(messages), 2)
        self.assertTrue(any("nombre de la ficha" in message for message in messages))
        self.assertTrue(any("costo unitario" in message or "valor" in message for message in messages))
        self.assertTrue(any("propiedad no reconocida" in message for message in messages))

    def test_rechaza_firma_zip_invalida_con_mensaje_amigable(self):
        with self.assertRaises(Ficha148ValidationError) as ctx:
            self.validator.validar_paquete(b"not a zip")
        self.assertEqual(ctx.exception.messages, [ZIP_ERROR])
        self.assertTrue(ctx.exception.package_error)

    def test_rechaza_ruta_zipslip_y_entradas_no_esperadas(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("ficha.json", json.dumps(ejemplo()))
            archive.writestr("../escape.txt", "malicioso")
        with self.assertRaises(Ficha148ValidationError) as ctx:
            self.validator.validar_paquete(payload.getvalue())
        self.assertTrue(ctx.exception.package_error)

    def test_rechaza_bomba_de_descompresion(self):
        payload = io.BytesIO()
        manifest = {"format": "ficha148", "formatVersion": 1, "schemaVersion": 1, "document": "ficha.json"}
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("ficha.json", b"0" * (2 * 1024 * 1024))
        with self.assertRaises(Ficha148ValidationError) as ctx:
            self.validator.validar_paquete(payload.getvalue())
        self.assertTrue(ctx.exception.package_error)

    def test_resumen_sin_escritura_a_base(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "valid.ficha148"
            expected = ejemplo()
            exportar_ficha(expected, path)
            summary = self.validator.validar_paquete(path)
        self.assertEqual(summary.document, expected)
        self.assertEqual(summary.entity, "[PENDIENTE]")
        self.assertIsInstance(summary.cup, float)

    def test_la_capa_de_servicios_exige_confirmacion_antes_de_guardar(self):
        class RepoFalso:
            def __init__(self):
                self.guardado = False
            def guardar_ficha(self, _document):
                self.guardado = True

        repo = RepoFalso()
        with self.assertRaisesRegex(ValueError, "Confirme primero"):
            importar_a_base("no-se-lee-antes-de-confirmar.ficha148", repo)
        self.assertFalse(repo.guardado)


if __name__ == "__main__":
    unittest.main()
