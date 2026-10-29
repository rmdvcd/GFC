import tempfile
import unittest
from pathlib import Path

from fichacosto.help import HelpService
from fichacosto.help.help_ui import help_icon
from fichacosto.repositorio import RepositorioFichas


class FakePage:
    def __init__(self):
        self.dialog = None
        self.updates = 0
    def update(self):
        self.updates += 1


class HelpServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = RepositorioFichas(Path(self.temp.name) / "help.db", "test-key")
        self.service = HelpService(self.repo)

    def tearDown(self):
        self.repo.cerrar()
        self.temp.cleanup()

    def test_onboarding_state_is_persisted_between_sessions(self):
        self.assertFalse(self.service.onboarding_completado)
        self.service.marcar_onboarding_completado()
        restarted_service = HelpService(self.repo)
        self.assertTrue(restarted_service.onboarding_completado)
        restarted_service.reiniciar_onboarding()
        self.assertFalse(HelpService(self.repo).onboarding_completado)

    def test_app_shows_onboarding_before_completion_and_main_screen_afterward(self):
        from fichacosto.app import AplicacionFichaCosto
        import flet as ft
        class Page(FakePage):
            def __init__(self):
                super().__init__(); self.controls = []
            def add(self, *controls): self.controls.extend(controls)
        app = object.__new__(AplicacionFichaCosto)
        app.page = Page(); app.repo = self.repo; app.help = self.service; app.licensing = None
        app.archivo_picker = object()
        def contains_text(control, text):
            if getattr(control, "value", None) == text: return True
            children = list(getattr(control, "controls", []) or [])
            children += [getattr(control, "content", None), getattr(control, "title", None)]
            return any(child is not None and contains_text(child, text) for child in children)
        app._vista_principal()
        self.assertTrue(contains_text(app.contenido, "Bienvenido a FichaCosto"))
        self.service.marcar_onboarding_completado()
        app._vista_principal()
        self.assertFalse(contains_text(app.contenido, "Bienvenido a FichaCosto"))
        self.assertTrue(contains_text(app.contenido, "Fichas de costos"))

    def test_question_icon_opens_contextual_tooltip(self):
        page = FakePage()
        button = help_icon(page, self.service, "campo_fila_1")
        self.assertTrue(button.tooltip)
        button.on_click(None)
        self.assertTrue(page.dialog.open)
        self.assertEqual(page.dialog.title.value, "Fila 1 · Materias primas y materiales")
        self.assertTrue(any("carta tecnológica" in control.value for control in page.dialog.content.controls if hasattr(control, "value")))

    def test_notice_is_once_per_session_then_repeats_after_configured_interval(self):
        from datetime import datetime, timedelta, timezone
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        service = HelpService(self.repo, clock=lambda: now[0])
        first = service.evaluar_avisos_contextuales({"screen": "editor_ficha", "catalog_items": 0})
        self.assertEqual([x["id"] for x in first], ["primera_ficha_sin_catalogo"])
        self.assertEqual(service.evaluar_avisos_contextuales({"screen": "editor_ficha", "catalog_items": 0}), [])
        service.marcar_aviso_descartado("primera_ficha_sin_catalogo")
        self.assertEqual(HelpService(self.repo, clock=lambda: now[0]).evaluar_avisos_contextuales({"screen": "editor_ficha", "catalog_items": 0}), [])
        now[0] += timedelta(days=8)
        self.assertEqual([x["id"] for x in HelpService(self.repo, clock=lambda: now[0]).evaluar_avisos_contextuales({"screen": "editor_ficha", "catalog_items": 0})], ["primera_ficha_sin_catalogo"])

    def test_search_and_notice_no_show_preference(self):
        self.assertEqual(len(self.service.search("transfermóvil")["tutoriales"]), 1)
        notices = self.service.evaluar_avisos_contextuales({"screen": "fichas", "has_data": False})
        entity_notice = next(item for item in notices if item["id"] == "entidad_sin_configurar")
        self.service.marcar_aviso_descartado(entity_notice["id"], no_mostrar_de_nuevo=True)
        restarted_service = HelpService(self.repo)
        self.assertNotIn("entidad_sin_configurar", {item["id"] for item in restarted_service.evaluar_avisos_contextuales({"screen": "fichas", "has_data": False})})


if __name__ == "__main__":
    unittest.main()
