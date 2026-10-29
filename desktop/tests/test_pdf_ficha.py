import unittest
from fichacosto.dominio import Categoria, FichaCosto, Importe, Moneda, PartidaCosto
from fichacosto.exportaciones import generar_pdf_ficha


class FichaPdfTest(unittest.TestCase):
    def test_genera_pdf_con_datos_faltantes_sin_fallar(self):
        pdf = generar_pdf_ficha(FichaCosto(nombre="Servicio de ejemplo"))
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)

    def test_pdf_sin_licencia_se_genera_con_marca_de_agua(self):
        pdf = generar_pdf_ficha(FichaCosto(nombre="Sin licencia"), marca_agua=True)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)

    def test_calcula_total_solo_con_filas_confirmadas_y_base_margen(self):
        ficha = FichaCosto(nombre="Ejemplo completo")
        ficha.partidas.extend([
            PartidaCosto(Categoria.MATERIAS_PRIMAS_MATERIALES, "Papel", 2, "u", Importe(10, Moneda.CUP)),
            PartidaCosto(Categoria.FUERZA_TRABAJO_DIRECTA, "Salario", 1, "h", Importe(30, Moneda.CUP)),
            PartidaCosto(Categoria.GASTOS_INDIRECTOS_PRODUCCION, "Depreciación", 1, "u", Importe(5, Moneda.CUP)),
        ])
        ficha.extensionData = {"anexoI": {
            "nombreEntidad": "Entidad ejemplo", "actividadEconomica": "Servicio",
            "periodoVigencia": "2026", "filas": {"2": [], "3": [], "6": [], "7": [], "8": []},
            "margenUtilidad": {"baseAutorizada": "Base indicada por la entidad", "porcentaje": 10,
                               "importe": {"CUP": 5, "MLC": 0}},
        }}
        pdf = generar_pdf_ficha(ficha)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)

if __name__ == "__main__":
    unittest.main()
