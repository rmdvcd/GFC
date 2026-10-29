"""Componentes Flet reutilizables para la ayuda contextual offline."""
from __future__ import annotations

import flet as ft

from .help_service import HelpService


def _close(page: ft.Page):
    if page.dialog:
        page.dialog.open = False
        page.update()


def show_tooltip(page: ft.Page, service: HelpService, tooltip_id: str):
    item = service.get_tooltip(tooltip_id)
    if item: service.marcar_tooltip_visto(tooltip_id)
    if not item:
        return
    controls = [ft.Text(item["cuerpo"], selectable=True)]
    if item.get("normativa"):
        controls += [ft.Divider(), ft.Text(item["normativa"], size=12, italic=True, selectable=True)]
    actions = [ft.TextButton("Cerrar", on_click=lambda _: _close(page))]
    if item.get("tutorialId"):
        actions.insert(0, ft.TextButton("Ver tutorial", on_click=lambda _: show_tutorial(page, service, item["tutorialId"])))
    page.dialog = ft.AlertDialog(modal=True, title=ft.Text(item["titulo"], selectable=True),
        content=ft.Column(controls, tight=True, scroll=ft.ScrollMode.AUTO, width=520), actions=actions)
    page.dialog.open = True
    page.update()


def help_icon(page: ft.Page, service: HelpService, tooltip_id: str) -> ft.Control:
    item = service.content["tooltips"].get(tooltip_id, {})
    title = item.get("titulo", "Ayuda")
    return ft.IconButton(icon=ft.icons.HELP_OUTLINE, tooltip=ft.Tooltip(message=title),
                         on_click=lambda _: show_tooltip(page, service, tooltip_id),
                         icon_size=18, visual_density=ft.VisualDensity.COMPACT)


def help_label(page: ft.Page, service: HelpService, label: str, tooltip_id: str) -> ft.Control:
    return ft.Row([ft.Text(label, weight=ft.FontWeight.W_500), help_icon(page, service, tooltip_id)], tight=True, spacing=2)


def show_tutorial(page: ft.Page, service: HelpService, tutorial_id: str, index: int = 0):
    tutorial = service.get_tutorial(tutorial_id)
    if not tutorial:
        return
    service.marcar_tutorial_visto(tutorial_id)
    steps = tutorial["pasos"]
    index = max(0, min(index, len(steps) - 1))
    current = steps[index]
    image = service.asset_base64(current["imagen"])
    body = [ft.Text(f"Paso {index + 1} de {len(steps)}", semantics_label=f"Paso {index + 1} de {len(steps)}")]
    if image:
        body.append(ft.Image(src_base64=image, height=170, fit=ft.ImageFit.CONTAIN, semantics_label=tutorial["titulo"]))
    body.append(ft.Text(current["texto"], selectable=True))
    actions = [ft.TextButton("Cerrar", on_click=lambda _: _close(page))]
    if index > 0:
        actions.append(ft.TextButton("Anterior", on_click=lambda _: show_tutorial(page, service, tutorial_id, index - 1)))
    actions.append(ft.ElevatedButton("Terminar" if index == len(steps) - 1 else "Siguiente",
        on_click=lambda _: _close(page) if index == len(steps) - 1 else show_tutorial(page, service, tutorial_id, index + 1)))
    page.dialog = ft.AlertDialog(modal=True, title=ft.Text(tutorial["titulo"], selectable=True),
        content=ft.Column(body, tight=True, scroll=ft.ScrollMode.AUTO, width=560), actions=actions)
    page.dialog.open = True
    page.update()


def help_screen(page: ft.Page, service: HelpService, on_back, on_replay_tour):
    search = ft.TextField(label="Buscar en la ayuda", prefix_icon=ft.icons.SEARCH, autofocus=True)
    results = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)

    def render(_=None):
        found = service.search(search.value or "")
        controls: list[ft.Control] = [ft.Text("Tutoriales", size=20, weight=ft.FontWeight.BOLD)]
        controls.extend(ft.ListTile(leading=ft.Icon(ft.icons.MENU_BOOK_OUTLINED), title=ft.Text(t["titulo"]),
            subtitle=ft.Text(t.get("resumen", "")), on_click=lambda e, tid=t["id"]: show_tutorial(page, service, tid)) for t in found["tutoriales"])
        controls.append(ft.Text("Preguntas frecuentes", size=20, weight=ft.FontWeight.BOLD))
        for faq in found["preguntas_frecuentes"]:
            children = [ft.Text(faq["respuesta"], selectable=True)]
            if faq.get("tutorialId"):
                children.append(ft.TextButton("Ver tutorial relacionado", on_click=lambda e, tid=faq["tutorialId"]: show_tutorial(page, service, tid)))
            controls.append(ft.ExpansionTile(title=ft.Text(faq["pregunta"]), controls=children))
        if found["tooltips"]:
            controls.append(ft.Text("Ayuda por campo", size=20, weight=ft.FontWeight.BOLD))
            for tip in found["tooltips"]:
                controls.append(ft.ExpansionTile(title=ft.Text(tip["titulo"]), controls=[ft.Text(tip["cuerpo"]), ft.Text(tip.get("normativa", ""), size=12)]))
        results.controls = controls
        page.update()

    search.on_change = render
    top = ft.Row([ft.Text("Ayuda", size=24, weight=ft.FontWeight.BOLD), ft.Container(expand=True),
                  ft.OutlinedButton("Ver tour de nuevo", icon=ft.icons.REPLAY, on_click=lambda _: on_replay_tour()),
                  ft.TextButton("Volver", on_click=lambda _: on_back())])
    return [top, search, results], render


def context_banner(page: ft.Page, service: HelpService, notice: dict, on_action):
    notice_id = notice["id"]
    hidden = ft.Row(visible=True, controls=[
        ft.Icon(ft.icons.LIGHTBULB_OUTLINE), ft.Text(notice["mensaje"], expand=True, selectable=True),
        ft.TextButton("Cerrar", on_click=lambda _: dismiss(False)),
        ft.TextButton("No mostrar de nuevo", on_click=lambda _: dismiss(True)),
        ft.ElevatedButton("Abrir", on_click=lambda _: on_action(notice.get("accion", {}))),
    ], wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    def dismiss(permanent: bool):
        service.marcar_aviso_descartado(notice_id, no_mostrar_de_nuevo=permanent)
        hidden.visible = False
        page.update()
    return ft.Container(content=hidden, padding=10, bgcolor=ft.colors.BLUE_50, border=ft.border.all(1, ft.colors.BLUE_200), border_radius=8)
