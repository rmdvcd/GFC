"""Motor de ayuda offline. El contenido y los textos proceden del contrato JSON compartido."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class HelpContentError(ValueError):
    """Contenido de ayuda ausente, inválido o incompatible."""


class HelpService:
    CONTENT_PATH = Path(__file__).with_name("help_content_v1.json")
    SCHEMA_PATH = Path(__file__).with_name("help_content_v1.schema.json")
    PREF_ONBOARDING = "help.onboarding_completed"
    PREF_ENTITY = "help.entity_profile"

    def __init__(self, repo, content_path: str | Path | None = None,
                 schema_path: str | Path | None = None, clock=None):
        self.repo = repo
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        content_path = Path(content_path or self.CONTENT_PATH)
        schema_path = Path(schema_path or self.SCHEMA_PATH)
        try:
            self.content = json.loads(content_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            errors = sorted(Draft202012Validator(schema).iter_errors(self.content), key=lambda e: list(e.absolute_path))
            if errors:
                where = "/".join(map(str, errors[0].absolute_path)) or "raíz"
                raise HelpContentError(f"Contenido de ayuda inválido en {where}: {errors[0].message}")
        except (OSError, json.JSONDecodeError) as exc:
            raise HelpContentError("No se pudo cargar el contenido de ayuda offline incluido en la aplicación.") from exc
        self._notice_session: set[str] = set()
        if self.repo.get_preference(self.PREF_ONBOARDING) is None:
            self.repo.set_preference(self.PREF_ONBOARDING, False)

    @staticmethod
    def for_repo(repo) -> "HelpService":
        cached = getattr(repo, "_help_service", None)
        if cached is None:
            cached = HelpService(repo)
            setattr(repo, "_help_service", cached)
        return cached

    def get_tooltip(self, tooltip_id: str) -> dict[str, Any] | None:
        return self.content["tooltips"].get(tooltip_id)

    def marcar_tooltip_visto(self, tooltip_id: str) -> None:
        self.repo.set_preference(f"help.tooltip_seen.{tooltip_id}", self._now().isoformat())

    def get_tutorial(self, tutorial_id: str) -> dict[str, Any] | None:
        return next((x for x in self.content["tutoriales"] if x["id"] == tutorial_id), None)

    def marcar_tutorial_visto(self, tutorial_id: str) -> None:
        self.repo.set_preference(f"help.tutorial_seen.{tutorial_id}", self._now().isoformat())

    def get_faq(self) -> list[dict[str, Any]]:
        return list(self.content["preguntas_frecuentes"])

    def search(self, query: str) -> dict[str, list[dict[str, Any]]]:
        needle = (query or "").strip().casefold()
        if not needle:
            return {"tooltips": list(self.content["tooltips"].values()),
                    "tutoriales": list(self.content["tutoriales"]), "preguntas_frecuentes": self.get_faq()}
        includes = lambda item, text: needle in text.casefold()
        tips = [v for v in self.content["tooltips"].values()
                if includes(v, " ".join([v.get("titulo", ""), v.get("cuerpo", ""), v.get("normativa", "")]))]
        tutorials = [v for v in self.content["tutoriales"]
                     if includes(v, " ".join([v.get("titulo", ""), v.get("resumen", ""), *(s["texto"] for s in v["pasos"])]))]
        faq = [v for v in self.get_faq() if includes(v, v["pregunta"] + " " + v["respuesta"])]
        return {"tooltips": tips, "tutoriales": tutorials, "preguntas_frecuentes": faq}

    @property
    def onboarding_completado(self) -> bool:
        return bool(self.repo.get_preference(self.PREF_ONBOARDING, False))

    def marcar_onboarding_completado(self) -> None:
        self.repo.set_preference(self.PREF_ONBOARDING, True)
        self.repo.set_preference("help.onboarding_completed_at", self._now().isoformat())

    def reiniciar_onboarding(self) -> None:
        self.repo.set_preference(self.PREF_ONBOARDING, False)

    def guardar_perfil_entidad(self, nombre: str, nit: str, actividad: str) -> None:
        self.repo.set_preference(self.PREF_ENTITY, {"nombre": nombre.strip(), "nit": nit.strip(), "actividad": actividad.strip()})

    def obtener_perfil_entidad(self) -> dict[str, str]:
        return self.repo.get_preference(self.PREF_ENTITY, {"nombre": "", "nit": "", "actividad": ""})

    def marcar_aviso_descartado(self, notice_id: str, no_mostrar_de_nuevo: bool = False) -> None:
        self.repo.set_preference(f"help.notice.{notice_id}.dismissed_at", self._now().isoformat())
        if no_mostrar_de_nuevo:
            self.repo.set_preference(f"help.notice.{notice_id}.disabled", True)
        self._notice_session.add(notice_id)

    def reactivar_aviso(self, notice_id: str) -> None:
        self.repo.set_preference(f"help.notice.{notice_id}.disabled", False)
        self.repo.set_preference(f"help.notice.{notice_id}.dismissed_at", None)

    def evaluar_avisos_contextuales(self, context: dict[str, Any] | None = None,
                                   pantalla: str | None = None) -> list[dict[str, Any]]:
        context = dict(context or {})
        now = self._now()
        screen = pantalla or context.get("screen")
        catalog_count = context.get("catalog_items")
        if catalog_count is None:
            try:
                catalog_count = len(self.repo.listar_catalogo("insumo"))
            except Exception:
                catalog_count = 0
        if context.get("last_backup_at") is None:
            context["last_backup_at"] = self.repo.get_preference("help.last_backup_at")
        if "finished_fichas_unexported" not in context:
            context["finished_fichas_unexported"] = any(
                doc.get("ficha", {}).get("estado") == "finalizada" and
                not self.repo.get_preference(f"help.pdf_exported.{doc.get('ficha', {}).get('id')}", False)
                for doc in self.repo.listar_fichas())
        if context.get("license_active") is True and context.get("license_days_remaining") is None:
            try:
                raw_license = self.repo.license_get_state("license_document")
                payload = json.loads(raw_license).get("payload", {}) if raw_license else {}
                expiry = payload.get("fechaExpiracion")
                if expiry:
                    context["license_days_remaining"] = int((self._parse_time(expiry) - now).total_seconds() // 86400)
            except Exception:
                pass
        if context.get("clock_suspicious") is None:
            try:
                context["clock_suspicious"] = bool(self.repo.license_get_state("clock_rollback_started_at"))
            except Exception:
                context["clock_suspicious"] = False
        context["catalog_items"] = catalog_count
        context["entity_profile_complete"] = context.get("entity_profile_complete", all(self.obtener_perfil_entidad().get(k, "").strip() for k in ("nombre", "nit", "actividad")))
        context["screen"] = screen
        result = []
        for notice_id, notice in self.content["avisos_contextuales"].items():
            if notice_id in self._notice_session or self.repo.get_preference(f"help.notice.{notice_id}.disabled", False):
                continue
            if not self._condition(notice_id, context, now):
                continue
            dismissed = self.repo.get_preference(f"help.notice.{notice_id}.dismissed_at")
            if dismissed:
                try:
                    if now - self._parse_time(dismissed) < timedelta(days=notice["repetirTrasDias"]):
                        continue
                except (ValueError, TypeError):
                    pass
            self._notice_session.add(notice_id)
            days = None
            if notice_id == "backup_vencido":
                last = context.get("last_backup_at")
                days = max(0, (now - self._parse_time(last)).days) if last else 8
            elif notice_id == "licencia_por_expirar":
                days = max(0, int(context.get("license_days_remaining", 0)))
            result.append({"id": notice_id, "mensaje": notice["mensaje"].replace("{dias}", str(days if days is not None else "")),
                           "accion": notice["accion"], "repetirTrasDias": notice["repetirTrasDias"]})
        return result

    def registrar_respaldo_creado(self, timestamp: datetime | None = None) -> None:
        self.repo.set_preference("help.last_backup_at", (timestamp or self._now()).isoformat())

    def registrar_pdf_exportado(self, ficha_id: str) -> None:
        self.repo.set_preference(f"help.pdf_exported.{ficha_id}", True)

    def catalogo_ejemplo_cargado(self, tipo: str) -> bool:
        return bool(self.repo.get_preference(f"help.sample_catalog.{tipo}", False))

    def marcar_catalogo_ejemplo_cargado(self, tipo: str) -> None:
        self.repo.set_preference(f"help.sample_catalog.{tipo}", True)

    def ficha_demo_id(self) -> str | None:
        return self.repo.get_preference("help.demo_ficha_id")

    def marcar_ficha_demo(self, ficha_id: str) -> None:
        self.repo.set_preference("help.demo_ficha_id", ficha_id)

    def _condition(self, notice_id: str, c: dict[str, Any], now: datetime) -> bool:
        if notice_id == "primera_ficha_sin_catalogo":
            return c.get("screen") in ("editor_ficha", "ficha_editor", "editor_ficha_nueva") and not c.get("catalog_items")
        if notice_id == "backup_vencido":
            last = c.get("last_backup_at")
            return (now - self._parse_time(last)).days > 7 if last else bool(c.get("has_data", False))
        if notice_id == "licencia_por_expirar":
            days = c.get("license_days_remaining")
            return c.get("license_active") is True and days is not None and 0 <= int(days) < 7
        if notice_id == "fichas_sin_exportar":
            return bool(c.get("finished_fichas_unexported", False))
        if notice_id == "reloj_sospechoso":
            return bool(c.get("clock_suspicious", False))
        if notice_id == "entidad_sin_configurar":
            return c.get("screen") == "fichas" and not c.get("entity_profile_complete", False)
        return False

    def asset_path(self, asset: str) -> str:
        name = Path(asset).name
        path = Path(__file__).with_name("assets") / name
        return str(path) if path.is_file() else ""

    def asset_base64(self, asset: str) -> str:
        path = self.asset_path(asset)
        return base64.b64encode(Path(path).read_bytes()).decode("ascii") if path else ""

    def _now(self) -> datetime:
        now = self.clock()
        return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)

    # Camel-case aliases match the cross-platform HelpService API.
    getTooltip = get_tooltip
    getTutorial = get_tutorial
    marcarTooltipVisto = marcar_tooltip_visto
    marcarTutorialVisto = marcar_tutorial_visto
    marcarOnboardingCompletado = marcar_onboarding_completado
    evaluarAvisosContextuales = evaluar_avisos_contextuales
