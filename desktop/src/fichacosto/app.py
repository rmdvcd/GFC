"""Interfaz mínima Flet: fichas, editor de partidas y catálogos."""
from __future__ import annotations

import os
from pathlib import Path
import flet as ft

from .dominio import Categoria, Coeficientes, EstadoFicha, FichaCosto, Importe, Moneda, PartidaCosto
from .intercambio import exportar_ficha
from .repositorio import RepositorioFichas
from .licensing.fingerprint import get_device_fingerprint
from .licensing.licensing_service import LicensingService
from .licensing.models import EstadoLicencia
from .backup.backup_service import BackupError, BackupService, fortaleza_contrasena
from .help import HelpService
from .help.help_ui import help_icon, help_label, help_screen, show_tooltip, show_tutorial, context_banner


class AplicacionFichaCosto:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "FichaCosto Desktop"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.padding = 16
        self.repo: RepositorioFichas | None = None
        self.seleccion: str | None = None
        self.archivo_picker = ft.FilePicker(on_result=self._seleccionar_archivo)
        self.license_picker = ft.FilePicker(on_result=self._importar_licencia)
        self.backup_picker = ft.FilePicker(on_result=self._seleccionar_respaldo)
        self.page.overlay.extend([self.archivo_picker, self.license_picker, self.backup_picker])
        self.licensing: LicensingService | None = None
        self.backup_service: BackupService | None = None
        self.backup_preview = None
        self.backup_password_restore = ""
        self.help: HelpService | None = None
        self._vista_acceso()

    def _notificar(self, texto: str):
        self.page.snack_bar = ft.SnackBar(ft.Text(texto), open=True)
        self.page.update()

    def _vista_acceso(self):
        clave = ft.TextField(label="Clave de cifrado local SQLCipher", password=True, can_reveal_password=True, autofocus=True)
        mensaje = ft.Text("La clave no se guarda en el código. Guárdela de forma segura; sin ella no se puede abrir la base de datos.")
        def abrir(_):
            try:
                ruta = Path.home() / ".fichacosto" / "fichas.db"
                self.repo = RepositorioFichas(ruta, clave.value)
                self.licensing = LicensingService(self.repo)
                self.backup_service = BackupService(self.repo, app_origin="desktop", app_version="0.1.0")
                os.environ["FICHACOSTO_DB_KEY"] = clave.value or ""
                self._vista_principal()
            except Exception as exc:
                mensaje.value = f"No se pudo abrir la base cifrada: {exc}"
                self.page.update()
        self.page.controls.clear()
        self.page.add(ft.Column([ft.Text("FichaCosto Desktop", size=28, weight=ft.FontWeight.BOLD), mensaje, clave,
                                 ft.ElevatedButton("Abrir base cifrada", on_click=abrir)], width=560, spacing=16))
        self.page.update()

    def _vista_principal(self):
        self.help = HelpService.for_repo(self.repo)
        self.page.controls.clear()
        self.nav = ft.NavigationRail(selected_index=0, label_type=ft.NavigationRailLabelType.ALL,
            destinations=[ft.NavigationRailDestination(icon=ft.icons.DESCRIPTION, label="Fichas"),
                          ft.NavigationRailDestination(icon=ft.icons.INVENTORY_2, label="Catálogos"),
                          ft.NavigationRailDestination(icon=ft.icons.VERIFIED_USER, label="Licencia"),
                          ft.NavigationRailDestination(icon=ft.icons.BACKUP, label="Respaldo"),
                          ft.NavigationRailDestination(icon=ft.icons.HELP_OUTLINE, label="Ayuda")],
            on_change=self._navegar)
        self.contenido = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
        self.page.add(ft.Row([self.nav, ft.VerticalDivider(width=1), self.contenido], expand=True))
        if self.help and not self.help.onboarding_completado:
            self._mostrar_onboarding()
        else:
            self._vista_fichas()

    def _navegar(self, e):
        if e.control.selected_index == 0:
            self._vista_fichas()
        elif e.control.selected_index == 1:
            self._vista_catalogos()
        elif e.control.selected_index == 2:
            self._vista_licencia()
        elif e.control.selected_index == 3:
            self._vista_respaldo()
        else:
            self._vista_ayuda()

    def _vista_ayuda(self):
        controles, refrescar = help_screen(self.page, self.help, self._vista_fichas,
            lambda: (self.help.reiniciar_onboarding(), self._mostrar_onboarding()))
        controles.insert(1, ft.OutlinedButton("Completar datos de entidad", icon=ft.icons.EDIT,
            on_click=lambda _: self._configurar_entidad()))
        self.contenido.controls = controles
        refrescar()

    def _configurar_entidad(self):
        profile = self.help.obtener_perfil_entidad()
        fields = {key: ft.TextField(label=label, value=profile.get(key, ""), width=480) for key, label in
                  [("nombre", "Nombre de la entidad"), ("nit", "NIT"), ("actividad", "Actividad económica")]}
        tips = ["campo_entidad_nombre", "campo_entidad_nit", "campo_entidad_actividad"]
        controls = [ft.Row([fields[key], help_icon(self.page, self.help, tip)], tight=True)
                    for key, tip in zip(("nombre", "nit", "actividad"), tips)]
        def save(_):
            self.help.guardar_perfil_entidad(*(fields[key].value or "" for key in ("nombre", "nit", "actividad")))
            self._cerrar_dialogo(); self._notificar("Datos de entidad guardados en la base local cifrada.")
        self.page.dialog = ft.AlertDialog(modal=True, title=ft.Text("Datos de entidad"),
            content=ft.Column(controls, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self._cerrar_dialogo()), ft.ElevatedButton("Guardar", on_click=save)])
        self.page.dialog.open = True; self.page.update()

    def _mostrar_onboarding(self):
        steps = self.help.content["onboarding"]["pasos"]
        profile = self.help.obtener_perfil_entidad()
        fields = {key: ft.TextField(value=profile.get(key, ""), width=480) for key in ("nombre", "nit", "actividad")}
        index = {"value": 0}
        catalog = ft.Dropdown(label="Catálogo de ejemplo", value="paladar", options=[
            ft.dropdown.Option("paladar", "Paladar"), ft.dropdown.Option("cafeteria", "Cafetería")], width=360)
        sample_added = {"value": False}
        demo_added = {"value": False}
        body = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=12)

        def finish(_=None):
            self.help.guardar_perfil_entidad(fields["nombre"].value or "", fields["nit"].value or "", fields["actividad"].value or "")
            self.help.marcar_onboarding_completado()
            self._vista_fichas()

        def load_sample(_=None):
            if self.help.catalogo_ejemplo_cargado(catalog.value):
                sample_added["value"] = True; render(); return
            sample = self.help.content["datos_inicio"]["catalogos"][catalog.value]
            for item in sample["insumos"]:
                self.repo.guardar_catalogo("insumo", {"id": str(__import__("uuid").uuid4()), "nombre": item["nombre"],
                    "unidadMedida": item["unidadMedida"], "costoUnitario": {"valor": item["costoUnitario"], "moneda": item["moneda"]}})
            for item in sample["tarifas"]:
                self.repo.guardar_catalogo("tarifa", {"id": str(__import__("uuid").uuid4()), "cargo": item["cargo"],
                    "unidadTarifa": item["unidadTarifa"], "tarifa": {"valor": item["valor"], "moneda": item["moneda"]}})
            self.help.marcar_catalogo_ejemplo_cargado(catalog.value)
            sample_added["value"] = True
            render()

        def create_demo(_=None):
            existing_demo = self.help.ficha_demo_id()
            if existing_demo:
                demo_added["value"] = True; render(); return
            if demo_added["value"]: return
            data = self.help.content["datos_inicio"]["ficha_demo"]
            lines = [PartidaCosto(categoria=Categoria(item["categoria"]), descripcion=item["descripcion"],
                cantidad=float(item["cantidad"]), unidadMedida=item["unidadMedida"],
                costoUnitario=Importe(float(item["precioUnitario"]), Moneda(item["moneda"]))) for item in data["partidas"]]
            ficha = FichaCosto(nombre=data["nombre"], descripcion=data["descripcion"], partidas=lines)
            self.repo.guardar_ficha(ficha.a_json())
            self.help.marcar_ficha_demo(ficha.id)
            demo_added["value"] = True
            render()

        def render():
            step = steps[index["value"]]
            image_data = self.help.asset_base64(step["imagen"])
            panel = [ft.Text(step["titulo"], size=25, weight=ft.FontWeight.BOLD, semantics_label=step["titulo"])]
            if image_data:
                panel.append(ft.Image(src_base64=image_data, height=170, fit=ft.ImageFit.CONTAIN, semantics_label=step["titulo"]))
            panel.append(ft.Text(step["cuerpo"], selectable=True))
            if step["id"] == "configurar_entidad":
                for label, key, tip_id in [("Nombre de la entidad", "nombre", "campo_entidad_nombre"), ("NIT", "nit", "campo_entidad_nit"), ("Actividad económica", "actividad", "campo_entidad_actividad")]:
                    panel.extend([ft.Row([ft.Text(label), help_icon(self.page, self.help, tip_id)], tight=True), fields[key]])
            elif step["id"] == "catalogos_iniciales":
                panel += [catalog, ft.OutlinedButton("Cargar ejemplos editables", icon=ft.icons.INVENTORY_2,
                    on_click=load_sample, disabled=sample_added["value"]),
                    ft.Text("Ejemplos con costo cero: edítelos con sus comprobantes antes de usarlos.")]
                if sample_added["value"]: panel.append(ft.Text("Catálogo cargado. Puede modificar o eliminar cada elemento desde Catálogos."))
            elif step["id"] == "primera_ficha":
                panel.append(ft.OutlinedButton("Crear ficha demostrativa", icon=ft.icons.DESCRIPTION, on_click=create_demo, disabled=demo_added["value"]))
                if demo_added["value"]: panel.append(ft.Text("Ficha de práctica creada con valores cero; puede editarla o borrarla desde Fichas."))
            body.controls = panel
            navigation = ft.Row([ft.Text(f"Paso {index['value'] + 1} de {len(steps)}"), ft.Container(expand=True),
                ft.TextButton("Saltar", on_click=finish),
                ft.TextButton("Anterior", on_click=lambda _: move(-1), disabled=index["value"] == 0),
                ft.ElevatedButton("Terminar" if index["value"] == len(steps) - 1 else "Siguiente",
                                  on_click=lambda _: move(1))])
            self.contenido.controls = [ft.Text("Primeros pasos", size=20, weight=ft.FontWeight.BOLD), body, navigation]
            self.page.update()

        def move(delta):
            if index["value"] == 1:
                self.help.guardar_perfil_entidad(fields["nombre"].value or "", fields["nit"].value or "", fields["actividad"].value or "")
            if delta > 0 and index["value"] == len(steps) - 1:
                finish()
                return
            index["value"] = min(len(steps) - 1, max(0, index["value"] + delta))
            render()
        def catalog_changed(_):
            sample_added["value"] = self.help.catalogo_ejemplo_cargado(catalog.value)
            render()
        catalog.on_change = catalog_changed
        sample_added["value"] = self.help.catalogo_ejemplo_cargado(catalog.value)
        demo_added["value"] = self.help.ficha_demo_id() is not None
        render()

    def _accion_aviso(self, action):
        target = action.get("target") if isinstance(action, dict) else None
        if isinstance(action, dict) and action.get("tipo") == "abrir_tutorial":
            show_tutorial(self.page, self.help, target); return
        if target == "catalogo_insumos": self.nav.selected_index = 1; self._vista_catalogos()
        elif target == "respaldo": self.nav.selected_index = 3; self._vista_respaldo()
        elif target == "licencia": self.nav.selected_index = 2; self._vista_licencia()
        elif target == "configuracion_entidad": self.nav.selected_index = 4; self._vista_ayuda(); self._configurar_entidad()
        elif target == "editor_ficha_nueva": self._nueva(None)
        else: self.nav.selected_index = 0; self._vista_fichas()

    def _agregar_avisos(self, controls, screen, has_data=True):
        if not self.help: return controls
        context = {"screen": screen, "has_data": has_data,
                   "finished_fichas_unexported": any(doc["ficha"].get("estado") == "finalizada" and not self.repo.get_preference(f"help.pdf_exported.{doc['ficha']['id']}", False) for doc in self.repo.listar_fichas())}
        try:
            state = self.licensing.estado_actual()
            context["license_active"] = state.estado is EstadoLicencia.VALIDA
            context["license_days_remaining"] = state.diasHastaExpiracion if state.estado is EstadoLicencia.VALIDA else None
        except Exception:
            context["license_active"] = False
        notices = self.help.evaluar_avisos_contextuales(context, pantalla=screen)
        return [*([context_banner(self.page, self.help, notice, self._accion_aviso) for notice in notices]), *controls]

    def _vista_fichas(self):
        fichas = self.repo.listar_fichas()
        self.contenido.controls = [ft.Row([ft.Text("Fichas de costos", size=24, weight=ft.FontWeight.BOLD), ft.Container(expand=True),
            ft.ElevatedButton("Nueva ficha", icon=ft.icons.ADD, on_click=self._nueva),
            ft.OutlinedButton("Importar .ficha148", icon=ft.icons.UPLOAD_FILE, on_click=lambda _: self.archivo_picker.pick_files(allowed_extensions=["ficha148"])),
            ft.IconButton(ft.icons.HELP_OUTLINE, tooltip="Ayuda", on_click=lambda _: self._vista_ayuda())]),
            ft.Text("Almacenamiento local cifrado · sin conexión", color=ft.colors.GREY_700)]
        if not fichas:
            self.contenido.controls.append(ft.Text("Aún no hay fichas. Cree una ficha o importe un archivo .ficha148."))
        for documento in fichas:
            ficha = documento["ficha"]
            self.contenido.controls.append(ft.Card(content=ft.Container(padding=12, content=ft.Row([
                ft.Column([ft.Text(ficha["nombre"], size=17, weight=ft.FontWeight.BOLD),
                           ft.Text(f"{ficha['estado']} · {ficha['monedaBase']} · {ficha['fechaActualizacion']}")], expand=True),
                ft.OutlinedButton("Editar", on_click=lambda e, fid=ficha["id"]: self._editar(fid)),
                ft.IconButton(ft.icons.DOWNLOAD, tooltip="Exportar ficha148", on_click=lambda e, doc=documento: self._exportar(doc)),
                ft.IconButton(ft.icons.DELETE_OUTLINE, tooltip="Eliminar", on_click=lambda e, fid=ficha["id"]: self._eliminar(fid))]))))
        self.contenido.controls = self._agregar_avisos(self.contenido.controls, "fichas", has_data=bool(fichas))
        self.page.update()

    def _nueva(self, _):
        campo = ft.TextField(label="Nombre del producto o servicio", autofocus=True)
        dialogo = ft.AlertDialog(modal=True, title=ft.Text("Nueva ficha"), content=ft.Column([ft.Row([campo, help_icon(self.page, self.help, "campo_nombre_ficha")]),
            ft.Row([ft.Text("Datos de la ficha"), help_icon(self.page, self.help, "campo_nombre_ficha")])], tight=True),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: self._cerrar_dialogo()),
                     ft.ElevatedButton("Crear", on_click=lambda e: crear())])
        def crear():
            if not campo.value or not campo.value.strip():
                campo.error_text = "El nombre es obligatorio"; self.page.update(); return
            if not self.licensing.consumir_feature("fichas"):
                self._notificar("No hay licencia activa para crear fichas o se alcanzó el límite. Las fichas existentes siguen disponibles; importe una licencia o revise su límite.")
                return
            ficha = FichaCosto(nombre=campo.value.strip())
            self.repo.guardar_ficha(ficha.a_json())
            self._cerrar_dialogo(); self._editar(ficha.id)
        self.page.dialog = dialogo; dialogo.open = True; self.page.update()

    def _cerrar_dialogo(self):
        self.page.dialog.open = False; self.page.update()

    def _editar(self, ficha_id: str):
        doc = self.repo.obtener_ficha(ficha_id)
        if not doc: return
        ficha = FichaCosto.desde_json(doc)
        def selected_category_help(dropdown):
            tip = {
                Categoria.MATERIAS_PRIMAS_MATERIALES.value: "campo_fila_1",
                Categoria.FUERZA_TRABAJO_DIRECTA.value: "campo_fila_4",
                Categoria.GASTOS_INDIRECTOS_PRODUCCION.value: "campo_fila_5",
                Categoria.OTROS_GASTOS_DIRECTOS.value: "campo_fila_7",
            }.get(dropdown.value, "campo_fila_1")
            show_tooltip(self.page, self.help, tip)
        nombre = ft.TextField(label="Producto o servicio", value=ficha.nombre)
        descripcion = ft.TextField(label="Descripción", value=ficha.descripcion, multiline=True)
        lineas = ft.Column()
        total = ft.Text(size=18, weight=ft.FontWeight.BOLD)
        def refrescar():
            lineas.controls.clear()
            for p in ficha.partidas:
                lineas.controls.append(ft.ListTile(title=ft.Text(p.descripcion), subtitle=ft.Text(
                    f"{p.cantidad:g} {p.unidadMedida} × {p.costoUnitario.valor:g} {p.costoUnitario.moneda.value} = {p.subtotal.valor:.2f} {p.subtotal.moneda.value} · {p.categoria.value}"),
                    trailing=ft.Row([ft.IconButton(ft.icons.EDIT, tooltip="Editar", on_click=lambda e, item=p: editar_partida(item)), ft.IconButton(ft.icons.DELETE, on_click=lambda e, pid=p.id: quitar(pid))], tight=True)))
            calculos = ficha.totales()
            resumen = calculos["costoTotal"]
            precio = calculos["precioCalculado"]
            total.value = f"Costo: {resumen['CUP']:.2f} CUP · {resumen['MLC']:.2f} MLC" + (f"  |  Precio estimado: {precio['CUP']:.2f} CUP · {precio['MLC']:.2f} MLC" if precio else "")
            self.page.update()
        def quitar(pid):
            ficha.partidas = [p for p in ficha.partidas if p.id != pid]; refrescar()
        def editar_partida(item):
            descripcion_p = ft.TextField(label="Descripción", value=item.descripcion)
            cantidad = ft.TextField(label="Cantidad", value=str(item.cantidad), keyboard_type=ft.KeyboardType.NUMBER)
            unidad = ft.TextField(label="Unidad de medida", value=item.unidadMedida)
            precio = ft.TextField(label="Costo unitario", value=str(item.costoUnitario.valor), keyboard_type=ft.KeyboardType.NUMBER)
            cat = ft.Dropdown(label="Categoría", value=item.categoria.value, options=[ft.dropdown.Option(c.value, c.value.replace("_", " ")) for c in Categoria])
            moneda = ft.Dropdown(label="Moneda", value=item.costoUnitario.moneda.value, options=[ft.dropdown.Option("CUP"), ft.dropdown.Option("MLC")])
            def aplicar(_):
                try:
                    nuevo = PartidaCosto(id=item.id, categoria=Categoria(cat.value), descripcion=descripcion_p.value.strip(), cantidad=float(cantidad.value), unidadMedida=unidad.value.strip(), costoUnitario=Importe(float(precio.value), Moneda(moneda.value)), insumoId=item.insumoId, observaciones=item.observaciones)
                    ficha.partidas = [nuevo if p.id == item.id else p for p in ficha.partidas]
                    self.page.dialog.open = False; self.page.update(); refrescar()
                except Exception as exc:
                    descripcion_p.error_text = str(exc); self.page.update()
            self.page.dialog = ft.AlertDialog(modal=True, title=ft.Text("Editar partida"), content=ft.Column([ft.Row([cat, ft.IconButton(ft.icons.HELP_OUTLINE, tooltip="Ayuda para la fila seleccionada", on_click=lambda _: selected_category_help(cat)), ft.IconButton(ft.icons.HELP_OUTLINE, tooltip="Ayuda de moneda", on_click=lambda _: show_tooltip(self.page, self.help, "selector_moneda"))]), descripcion_p, cantidad, unidad, precio, moneda], tight=True), actions=[ft.TextButton("Cancelar", on_click=lambda e: self._cerrar_dialogo()), ft.ElevatedButton("Guardar", on_click=aplicar)])
            self.page.dialog.open = True; self.page.update()
        def nueva_partida(_):
            descripcion_p = ft.TextField(label="Descripción")
            cantidad = ft.TextField(label="Cantidad", value="1", keyboard_type=ft.KeyboardType.NUMBER)
            unidad = ft.TextField(label="Unidad de medida", value="unidad")
            precio = ft.TextField(label="Costo unitario", value="0", keyboard_type=ft.KeyboardType.NUMBER)
            cat = ft.Dropdown(label="Categoría", value=Categoria.MATERIAS_PRIMAS_MATERIALES.value,
                options=[ft.dropdown.Option(c.value, c.value.replace("_", " ")) for c in Categoria])
            moneda = ft.Dropdown(label="Moneda", value=ficha.monedaBase.value, options=[ft.dropdown.Option("CUP"), ft.dropdown.Option("MLC")])
            def agregar(e):
                try:
                    ficha.partidas.append(PartidaCosto(categoria=Categoria(cat.value), descripcion=descripcion_p.value.strip(),
                        cantidad=float(cantidad.value), unidadMedida=unidad.value.strip(),
                        costoUnitario=Importe(float(precio.value), Moneda(moneda.value))))
                    dlg.open = False; self.page.update(); refrescar()
                except Exception as exc:
                    descripcion_p.error_text = str(exc); self.page.update()
            dlg = ft.AlertDialog(modal=True, title=ft.Text("Añadir partida"), content=ft.Column([ft.Row([cat, ft.IconButton(ft.icons.HELP_OUTLINE, tooltip="Ayuda para la fila seleccionada", on_click=lambda _: selected_category_help(cat)), ft.IconButton(ft.icons.HELP_OUTLINE, tooltip="Ayuda de moneda", on_click=lambda _: show_tooltip(self.page, self.help, "selector_moneda"))]), descripcion_p, cantidad, unidad, precio, moneda], tight=True, scroll=ft.ScrollMode.AUTO),
                actions=[ft.TextButton("Cancelar", on_click=lambda e: self._cerrar_dialogo()), ft.ElevatedButton("Añadir", on_click=agregar)])
            self.page.dialog = dlg; dlg.open = True; self.page.update()
        coef_indirecto = ft.TextField(label="Coeficiente indirecto (dato de usuario; no aplicado automáticamente)", value="" if ficha.coeficientes.coeficienteIndirecto is None else str(ficha.coeficientes.coeficienteIndirecto), keyboard_type=ft.KeyboardType.NUMBER)
        margen = ft.TextField(label="Margen de ganancia (vacío = no calcular)", value="" if ficha.coeficientes.margenGanancia is None else str(ficha.coeficientes.margenGanancia), keyboard_type=ft.KeyboardType.NUMBER)
        unidad_coef = ft.Dropdown(label="Interpretar margen como", value=ficha.coeficientes.unidadCoeficiente, options=[ft.dropdown.Option("porcentaje"), ft.dropdown.Option("factor")])
        def actualizar_coeficientes():
            ficha.coeficientes = Coeficientes(coeficienteIndirecto=float(coef_indirecto.value) if coef_indirecto.value else None,
                margenGanancia=float(margen.value) if margen.value else None, unidadCoeficiente=unidad_coef.value or "porcentaje")
        def guardar(_):
            usa_multimoneda = ficha.monedaBase is Moneda.MLC or any(p.costoUnitario.moneda is Moneda.MLC for p in ficha.partidas)
            if usa_multimoneda and not self.licensing.consumir_feature("multimoneda"):
                self._notificar("El uso de MLC requiere una licencia activa con la función multimoneda. Puede consultar las fichas existentes o importar una licencia.")
                return
            ficha.nombre = nombre.value.strip() or ficha.nombre
            ficha.descripcion = descripcion.value or ""
            ficha.estado = EstadoFicha.FINALIZADA if estado.value == "finalizada" else EstadoFicha.BORRADOR
            actualizar_coeficientes()
            self.repo.guardar_ficha(ficha.a_json()); self._vista_fichas(); self._notificar("Ficha guardada")
        estado = ft.Dropdown(label="Estado", value=ficha.estado.value, options=[ft.dropdown.Option("borrador"), ft.dropdown.Option("finalizada")])
        def exportacion_editor(e):
            from .exportaciones import exportar_csv, exportar_excel, exportar_pdf
            ficha.nombre = nombre.value.strip() or ficha.nombre
            ficha.descripcion = descripcion.value or ""
            ficha.estado = EstadoFicha.FINALIZADA if estado.value == "finalizada" else EstadoFicha.BORRADOR
            actualizar_coeficientes()
            documento = ficha.a_json(); documento["ficha"]["catalogosSnapshot"] = self.repo.snapshot_catalogos(); self.repo.guardar_ficha(documento)
            carpeta = Path.home() / "Documents"; carpeta.mkdir(parents=True, exist_ok=True)
            base = ficha.nombre.replace(" ", "_")
            tipo = e.control.data
            estado_licencia = self.licensing.estado_actual()
            if tipo != "pdf" and not self.licensing.consumir_feature("import_export"):
                self._notificar("La exportación avanzada requiere una licencia activa con la función de importación/exportación.")
                return
            if tipo == "pdf":
                destino = exportar_pdf(ficha, carpeta / f"{base}.pdf", marca_agua=estado_licencia.pdf_con_marca_agua)
                if self.help: self.help.registrar_pdf_exportado(ficha.id)
            else:
                fn = {"csv": exportar_csv, "xlsx": exportar_excel}[tipo]
                destino = fn(ficha, carpeta / f"{base}.{tipo}")
            self._notificar(f"Exportado: {destino}")
        fila_guias = ft.ExpansionTile(title=ft.Text("Guía de las filas 1–11 del modelo"), controls=[
            ft.ListTile(title=ft.Text(f"Fila {i} · {self.help.get_tooltip(f'campo_fila_{i}')['titulo'].split('·',1)[-1].strip()}"),
                trailing=help_icon(self.page, self.help, f"campo_fila_{i}")) for i in range(1, 12)])
        self.contenido.controls = [ft.Row([ft.Text("Editor de ficha", size=24, weight=ft.FontWeight.BOLD), ft.Container(expand=True),
            ft.PopupMenuButton(icon=ft.icons.FILE_DOWNLOAD, tooltip="Exportar", items=[ft.PopupMenuItem(text="PDF", data="pdf", on_click=exportacion_editor), ft.PopupMenuItem(text="CSV", data="csv", on_click=exportacion_editor), ft.PopupMenuItem(text="Excel", data="xlsx", on_click=exportacion_editor)]),
            ft.TextButton("Tutorial", icon=ft.icons.MENU_BOOK, on_click=lambda e: show_tutorial(self.page, self.help, "tutorial_crear_ficha")),
            ft.TextButton("Volver", on_click=lambda e: self._vista_fichas()), ft.ElevatedButton("Guardar", icon=ft.icons.SAVE, on_click=guardar)]),
            ft.Row([nombre, help_icon(self.page, self.help, "campo_nombre_ficha")], tight=True), descripcion, estado, coef_indirecto,
            ft.Row([margen, help_icon(self.page, self.help, "margen_utilidad")], tight=True), unidad_coef,
            ft.Text("El precio con margen es una estimación configurable (porcentaje: costo × (1 + margen/100); factor: costo × factor). No representa una fórmula normativa. El coeficiente indirecto se conserva, pero su base de aplicación requiere definición regulatoria.", size=12, color=ft.colors.GREY_700),
            ft.Divider(), ft.Row([ft.Text("Partidas de costo", size=19), ft.Container(expand=True), ft.OutlinedButton("Añadir partida", icon=ft.icons.ADD, on_click=nueva_partida)]),
            lineas, total, ft.Row([ft.Text("Moneda: CUP y MLC se totalizan por separado."), help_icon(self.page, self.help, "selector_moneda")]),
            fila_guias, ft.TextButton("Ver tutorial de creación", icon=ft.icons.MENU_BOOK,
                on_click=lambda e: show_tutorial(self.page, self.help, "tutorial_crear_ficha"))]
        self.contenido.controls = self._agregar_avisos(self.contenido.controls, "editor_ficha", has_data=bool(ficha.partidas))
        refrescar()

    def _exportar(self, documento):
        ruta = Path.home() / "Documents" / f"{documento['ficha']['nombre'].replace(' ', '_')}.ficha148"
        try:
            if not self.licensing.consumir_feature("import_export"):
                self._notificar("La exportación .ficha148 requiere una licencia activa con la función de importación/exportación.")
                return
            documento["ficha"]["catalogosSnapshot"] = self.repo.snapshot_catalogos()
            exportar_ficha(documento, ruta); self._notificar(f"Exportado: {ruta}")
        except Exception as exc: self._notificar(f"Error al exportar: {exc}")

    def _eliminar(self, ficha_id):
        self.repo.eliminar_ficha(ficha_id); self._vista_fichas()

    def _seleccionar_archivo(self, e):
        if not e.files: return
        from .ficha148_validator import Ficha148ValidationError, Ficha148Validator
        try:
            resumen = Ficha148Validator().validar_paquete(e.files[0].path)
            ficha = resumen.document["ficha"]
            dialogo = ft.AlertDialog(modal=True, title=ft.Text("Validación correcta"),
                content=ft.Text(f"Ficha: {ficha['nombre']}\nEntidad: {resumen.entity}\nPeríodo: {resumen.period}\nCosto total: {resumen.cup:.2f} CUP · {resumen.mlc:.2f} MLC\n\n¿Desea incorporarla a la base local cifrada?"),
                actions=[ft.TextButton("Cancelar", on_click=lambda _: cerrar()),
                         ft.ElevatedButton("Importar", on_click=lambda _: confirmar())])
            def cerrar():
                dialogo.open = False; self.page.update()
            def confirmar():
                try:
                    cerrar()
                    self.repo.guardar_ficha(resumen.document)
                    self._vista_fichas(); self._notificar("Ficha validada e importada correctamente")
                except Exception:
                    self._notificar("No se pudo guardar la ficha validada en la base local.")
            self.page.dialog = dialogo; dialogo.open = True; self.page.update()
        except Ficha148ValidationError as exc:
            self._mostrar_errores_importacion(exc.messages)
        except Exception:
            self._notificar("No se pudo leer el paquete .ficha148. Compruebe el archivo e inténtelo nuevamente.")

    def _mostrar_errores_importacion(self, mensajes: list[str]):
        contenido = ft.Column([ft.Text(f"• {mensaje}") for mensaje in mensajes], tight=True, scroll=ft.ScrollMode.AUTO)
        dialogo = ft.AlertDialog(modal=True, title=ft.Text("No se pudo validar el archivo"), content=contenido,
            actions=[ft.TextButton("Cerrar", on_click=lambda _: cerrar())])
        def cerrar():
            dialogo.open = False; self.page.update()
        self.page.dialog = dialogo; dialogo.open = True; self.page.update()

    def _vista_licencia(self):
        estado = self.licensing.estado_actual()
        labels = {
            EstadoLicencia.VALIDA: "Válida", EstadoLicencia.EXPIRADA: "Expirada",
            EstadoLicencia.FINGERPRINT_NO_COINCIDE: "No corresponde a este dispositivo",
            EstadoLicencia.FIRMA_INVALIDA: "Firma inválida", EstadoLicencia.SCHEMA_INVALIDO: "Archivo no válido",
            EstadoLicencia.NO_INSTALADA: "No instalada",
        }
        huella = get_device_fingerprint()
        payload = estado.payload or {}
        self.contenido.controls = [
            ft.Text("Licencia offline", size=24, weight=ft.FontWeight.BOLD),
            ft.Text(f"Estado: {labels[estado.estado]}", size=18),
            ft.Row([ft.Text(f"Tipo: {estado.tipo or '—'}"), help_icon(self.page, self.help, "licencia_tipo")], tight=True),
            ft.Text(f"Funciones: {', '.join(estado.features) or '—'}"),
            ft.Text(f"Fichas restantes: {estado.fichasRestantes if estado.fichasRestantes is not None else '—'}"),
            ft.Text(f"Días hasta expiración: {estado.diasHastaExpiracion if estado.diasHastaExpiracion is not None else '—'}"),
            ft.Text(estado.motivoRechazo or estado.advertencia or "La firma y el dispositivo se validan localmente."),
            ft.Divider(), ft.Row([ft.Text("ID de este dispositivo", weight=ft.FontWeight.BOLD), help_icon(self.page, self.help, "licencia_fingerprint")], tight=True),
            ft.Text(huella, selectable=True),
            ft.Row([ft.OutlinedButton("Copiar ID", icon=ft.icons.COPY, on_click=lambda _: self._copiar_huella(huella)),
                    ft.ElevatedButton("Importar archivo .lic", icon=ft.icons.UPLOAD_FILE,
                                      on_click=lambda _: self.license_picker.pick_files(allowed_extensions=["lic"])),
                    ft.TextButton("Tutorial", icon=ft.icons.MENU_BOOK, on_click=lambda _: show_tutorial(self.page, self.help, "tutorial_importar_licencia"))]),
            ft.Text("Sin licencia activa se conservan las fichas existentes y se permite PDF con marca de agua «VERSIÓN NO LICENCIADA». La hora, la base de datos y la revocación permanecen bajo control del dispositivo mientras está desconectado.", size=12, color=ft.colors.GREY_700),
        ]
        self.contenido.controls = self._agregar_avisos(self.contenido.controls, "licencia", has_data=bool(self.repo.listar_fichas()))
        self.page.update()

    def _copiar_huella(self, huella: str):
        try:
            self.page.set_clipboard(huella)
            self._notificar("ID del dispositivo copiado")
        except Exception:
            self._notificar("Seleccione y copie manualmente el ID mostrado.")

    def _importar_licencia(self, e):
        if not e.files or not e.files[0].path:
            return
        resultado = self.licensing.cargar_licencia(e.files[0].path)
        if resultado.estado is EstadoLicencia.VALIDA:
            self._notificar("Licencia instalada y validada correctamente")
        else:
            self._notificar(resultado.motivoRechazo or "No se pudo validar la licencia")
        self._vista_licencia()

    def _vista_respaldo(self):
        self.backup_password_field = ft.TextField(label="Contraseña del respaldo (mínimo 8 caracteres)", password=True, can_reveal_password=True, width=520)
        self.backup_confirm_field = ft.TextField(label="Repita la contraseña", password=True, can_reveal_password=True)
        self.backup_strength_text = ft.Text("Fortaleza: —")
        self.backup_progress = ft.ProgressBar(visible=False)
        self.restore_password_field = ft.TextField(label="Contraseña del archivo .bak", password=True, can_reveal_password=True, width=520)
        self.contenido.controls = [
            ft.Text("Respaldo cifrado", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("El archivo se cifra localmente con Argon2id y AES-256-GCM. No se sube a internet."),
            ft.Row([ft.Text("Guarde esta contraseña por separado; no existe recuperación si la olvida."), help_icon(self.page, self.help, "backup_contrasena")], wrap=True),
            ft.Divider(), ft.Text("Crear respaldo", size=19, weight=ft.FontWeight.BOLD),
            ft.Row([self.backup_password_field, help_icon(self.page, self.help, "backup_contrasena")], tight=True), self.backup_confirm_field, self.backup_strength_text, self.backup_progress,
            ft.ElevatedButton("Crear respaldo cifrado", icon=ft.icons.LOCK, on_click=self._crear_respaldo_ui),
            ft.Divider(), ft.Text("Restaurar respaldo", size=19, weight=ft.FontWeight.BOLD),
            ft.Row([self.restore_password_field, help_icon(self.page, self.help, "backup_contrasena")], tight=True),
            ft.Row([ft.TextButton("Cómo crear un respaldo", icon=ft.icons.MENU_BOOK, on_click=lambda e: show_tutorial(self.page, self.help, "tutorial_respaldo_cifrado")),
                    ft.TextButton("Cómo restaurarlo en otro dispositivo", icon=ft.icons.RESTORE, on_click=lambda e: show_tutorial(self.page, self.help, "tutorial_restaurar_backup"))]),
            ft.ElevatedButton("Seleccionar archivo .ficha148.bak", icon=ft.icons.UPLOAD_FILE,
                on_click=lambda _: self.backup_picker.pick_files(allowed_extensions=["bak"])),
            ft.Text("La restauración primero valida ZIP, manifiesto, contraseña, autenticación y esquemas. No modifica datos hasta mostrar una previsualización y solicitar confirmación."),
        ]
        self.contenido.controls = self._agregar_avisos(self.contenido.controls, "respaldo", has_data=bool(self.repo.listar_fichas()))
        self.backup_password_field.on_change = self._actualizar_fortaleza
        self.page.update()

    def _actualizar_fortaleza(self, e):
        label, _ = fortaleza_contrasena(e.control.value or "")
        self.backup_strength_text.value = f"Fortaleza: {label}"
        self.page.update()

    def _crear_respaldo_ui(self, _):
        password = self.backup_password_field.value or ""
        if password != (self.backup_confirm_field.value or ""):
            self._notificar("Las contraseñas no coinciden.")
            return
        label, score = fortaleza_contrasena(password)
        if len(password) < 8 or score < 2:
            self._notificar("Elija una contraseña de al menos 8 caracteres que no sea común y combine varios tipos de caracteres.")
            return
        self.backup_progress.visible = True
        self.page.update()
        try:
            destino = self.backup_service.crear_backup(password)
            if self.help: self.help.registrar_respaldo_creado()
            self._notificar(f"Respaldo cifrado creado: {destino}. Guarde la contraseña por separado.")
        except Exception as exc:
            self._notificar(f"No se pudo crear el respaldo: {exc}")
        finally:
            self.backup_progress.visible = False
            self.page.update()

    def _seleccionar_respaldo(self, e):
        if not e.files or not e.files[0].path:
            return
        password = self.restore_password_field.value or ""
        try:
            self.backup_preview = self.backup_service.previsualizar_backup(e.files[0].path, password)
            self._mostrar_previsualizacion_respaldo()
        except Exception as exc:
            self._notificar(str(exc))

    def _mostrar_previsualizacion_respaldo(self):
        preview = self.backup_preview
        mode = ft.Dropdown(label="Modo", value="fusionar", options=[
            ft.dropdown.Option("fusionar", "Fusionar por ID (conservar la ficha más reciente)"),
            ft.dropdown.Option("reemplazar", "Reemplazar todos los datos locales")])
        license_check = ft.Checkbox(label="Restaurar licencia como referencia (no activa otra huella)", value=False)
        usage_check = ft.Checkbox(label="Restaurar historial de uso", value=False)
        confirmation = ft.TextField(label="Para reemplazar, escriba REEMPLAZAR", visible=False)
        details = [
            ft.Text(f"Fecha del respaldo: {preview.fecha_creacion}"),
            ft.Text(f"Fichas: {preview.fichas} · Insumos: {preview.insumos} · Salarios: {preview.salarios}"),
            ft.Text(f"Incluye licencia: {'Sí' if preview.incluye_licencia else 'No'}"),
            ft.Text(f"Fingerprint origen: {preview.fingerprint_origen}", selectable=True),
        ]
        if preview.origen_diferente:
            details.append(ft.Text("Este respaldo proviene de otro dispositivo. Los datos se restaurarán, pero necesitará importar una nueva licencia para este equipo.", color=ft.colors.ORANGE_800))
        details.extend([mode, license_check, usage_check, confirmation])
        def mode_changed(e):
            confirmation.visible = e.control.value == "reemplazar"
            self.page.update()
        mode.on_change = mode_changed
        def apply(_):
            if mode.value == "reemplazar" and confirmation.value != "REEMPLAZAR":
                self._notificar("Escriba exactamente REEMPLAZAR para confirmar el borrado local.")
                return
            try:
                result = self.backup_service.aplicar_restauracion(preview, modo=mode.value,
                    restaurar_licencia=license_check.value or False, restaurar_usage=usage_check.value or False)
                self.page.dialog.open = False
                self.page.update()
                self._notificar(f"Restauración completada: {result.fichas_restauradas} fichas, {result.insumos_restaurados} insumos y {result.salarios_restaurados} salarios.")
                self._vista_fichas()
            except Exception as exc:
                self.page.dialog.open = False
                self.page.update()
                self._mostrar_error_respaldo(str(exc))
        self.page.dialog = ft.AlertDialog(modal=True, title=ft.Text("Previsualización del respaldo"),
            content=ft.Column(details, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self._cerrar_dialogo()),
                     ft.ElevatedButton("Confirmar restauración", icon=ft.icons.RESTORE, on_click=apply)])
        self.page.dialog.open = True
        self.page.update()

    def _mostrar_error_respaldo(self, texto: str):
        dialogo = ft.AlertDialog(modal=True, title=ft.Text("No se pudo completar la restauración"),
            content=ft.Text(texto + " Si el reemplazo falló, puede intentar recuperar el respaldo de seguridad interno."),
            actions=[ft.TextButton("Cerrar", on_click=lambda _: cerrar()),
                     ft.OutlinedButton("Recuperar respaldo interno", on_click=lambda _: recuperar())])
        def cerrar():
            dialogo.open = False; self.page.update()
        def recuperar():
            try:
                dialogo.open = False; self.page.update()
                result = self.backup_service.restaurar_respaldo_seguridad()
                self._notificar(f"Respaldo de seguridad recuperado: {result.fichas_restauradas} fichas.")
                self._vista_fichas()
            except Exception as exc:
                self._notificar(f"No se pudo recuperar el respaldo interno: {exc}")
        self.page.dialog = dialogo; dialogo.open = True; self.page.update()

    def _vista_catalogos(self):
        self.contenido.controls = [ft.Row([ft.Text("Catálogos locales", size=24, weight=ft.FontWeight.BOLD), ft.Container(expand=True),
            ft.TextButton("Tutorial de insumos", icon=ft.icons.MENU_BOOK, on_click=lambda _: show_tutorial(self.page, self.help, "tutorial_insumos"))]),
            ft.Text("Insumos y tarifas se guardan cifrados en esta instalación.")]
        for tipo, titulo in [("insumo", "Insumos"), ("tarifa", "Tarifas salariales")]:
            elementos = self.repo.listar_catalogo(tipo)
            self.contenido.controls.append(ft.Row([ft.Text(titulo, size=18, weight=ft.FontWeight.BOLD), ft.Container(expand=True),
                ft.OutlinedButton("Añadir", icon=ft.icons.ADD, on_click=lambda e, t=tipo: self._nuevo_catalogo(t))]))
            for x in elementos:
                detalle = (f"{x['unidadMedida']} · {x['costoUnitario']['valor']} {x['costoUnitario']['moneda']}" if tipo == "insumo" else f"{x['unidadTarifa']} · {x['tarifa']['valor']} {x['tarifa']['moneda']}")
                self.contenido.controls.append(ft.ListTile(title=ft.Text(x.get("nombre", x.get("cargo", ""))), subtitle=ft.Text(detalle),
                    on_click=lambda e, t=tipo, item=x: self._nuevo_catalogo(t, item),
                    trailing=ft.IconButton(ft.icons.DELETE_OUTLINE, tooltip="Eliminar", on_click=lambda e, xid=x['id']: self._eliminar_catalogo(xid))))
            if not elementos: self.contenido.controls.append(ft.Text("Sin elementos", color=ft.colors.GREY_600))
        self.page.update()

    def _nuevo_catalogo(self, tipo: str, existente: dict | None = None):
        precio = (existente.get("tarifa") if tipo == "tarifa" else existente.get("costoUnitario")) if existente else None
        nombre = ft.TextField(label="Cargo" if tipo == "tarifa" else "Nombre", value=(existente or {}).get("cargo" if tipo == "tarifa" else "nombre", ""))
        unidad = ft.TextField(label="Unidad de tarifa" if tipo == "tarifa" else "Unidad de medida", value=(existente or {}).get("unidadTarifa" if tipo == "tarifa" else "unidadMedida", "hora" if tipo == "tarifa" else "unidad"))
        valor = ft.TextField(label="Tarifa" if tipo == "tarifa" else "Costo unitario", value=str(precio["valor"] if precio else 0), keyboard_type=ft.KeyboardType.NUMBER)
        moneda = ft.Dropdown(label="Moneda", value=precio["moneda"] if precio else "CUP", options=[ft.dropdown.Option("CUP"), ft.dropdown.Option("MLC")])
        def guardar(_):
            try:
                from uuid import uuid4
                item_id = existente["id"] if existente else str(uuid4())
                if tipo == "insumo":
                    item = {"id": item_id, "nombre": nombre.value.strip(), "unidadMedida": unidad.value.strip(), "costoUnitario": {"valor": float(valor.value), "moneda": moneda.value}}
                else:
                    item = {"id": item_id, "cargo": nombre.value.strip(), "unidadTarifa": unidad.value.strip(), "tarifa": {"valor": float(valor.value), "moneda": moneda.value}}
                if not nombre.value.strip(): raise ValueError("El nombre es obligatorio")
                if float(valor.value) < 0: raise ValueError("La tarifa no puede ser negativa")
                self.repo.guardar_catalogo(tipo, item); self._cerrar_dialogo(); self._vista_catalogos()
            except Exception as exc:
                nombre.error_text = str(exc); self.page.update()
        self.page.dialog = ft.AlertDialog(modal=True, title=ft.Text("Nuevo insumo" if tipo == "insumo" else "Nueva tarifa salarial"),
            content=ft.Column([ft.Row([nombre, help_icon(self.page, self.help, "campo_fila_1")]), unidad, valor,
                ft.Row([moneda, help_icon(self.page, self.help, "selector_moneda")])], tight=True), actions=[ft.TextButton("Cancelar", on_click=lambda e: self._cerrar_dialogo()), ft.ElevatedButton("Guardar", on_click=guardar)])
        self.page.dialog.open = True; self.page.update()

    def _eliminar_catalogo(self, elemento_id: str):
        self.repo.eliminar_catalogo(elemento_id); self._vista_catalogos()


def main(page: ft.Page):
    AplicacionFichaCosto(page)


def ejecutar():
    ft.app(target=main)


if __name__ == "__main__":
    ejecutar()
