import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../data/app_database.dart';
import '../domain/models.dart';
import 'help_service.dart';

void showTooltip(BuildContext context, HelpService service, String tooltipId) {
  unawaited(service.marcarTooltipVisto(tooltipId));
  final item = service.getTooltip(tooltipId);
  if (item == null) return;
  showModalBottomSheet<void>(context: context, showDragHandle: true, isScrollControlled: true,
    builder: (sheetContext) => SafeArea(child: Padding(padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
      child: SingleChildScrollView(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Semantics(header: true, child: Text(item['titulo'] as String, style: Theme.of(context).textTheme.titleLarge)),
        const SizedBox(height: 12), Text(item['cuerpo'] as String),
        if (item['normativa'] is String) ...[const SizedBox(height: 12), Text(item['normativa'] as String, style: Theme.of(context).textTheme.bodySmall)],
        if (item['tutorialId'] is String) ...[const SizedBox(height: 12), TextButton.icon(onPressed: () { Navigator.pop(sheetContext); showTutorial(context, service, item['tutorialId'] as String); }, icon: const Icon(Icons.menu_book_outlined), label: const Text('Ver tutorial relacionado'))],
        Align(alignment: Alignment.centerRight, child: TextButton(onPressed: () => Navigator.pop(sheetContext), child: const Text('Cerrar'))),
      ])))));
}

class HelpTooltip extends StatelessWidget {
  const HelpTooltip({required this.service, required this.id, super.key, this.compact = false});
  final HelpService service;
  final String id;
  final bool compact;

  @override Widget build(BuildContext context) {
    final item = service.getTooltip(id);
    if (item == null) return const SizedBox.shrink();
    final title = item['titulo'] as String;
    return IconButton(
      tooltip: '$title. Abrir explicación',
      visualDensity: compact ? VisualDensity.compact : VisualDensity.standard,
      icon: const Icon(Icons.help_outline, size: 19),
      onPressed: () => showTooltip(context, service, id),
    );
  }
}

class HelpLabel extends StatelessWidget {
  const HelpLabel({required this.service, required this.tooltipId, required this.label, super.key, this.style});
  final HelpService service; final String tooltipId; final String label; final TextStyle? style;
  @override Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
    Flexible(child: Text(label, style: style)), HelpTooltip(service: service, id: tooltipId, compact: true),
  ]);
}

void showTutorial(BuildContext context, HelpService service, String tutorialId) {
  unawaited(service.marcarTutorialVisto(tutorialId));
  final tutorial = service.getTutorial(tutorialId);
  if (tutorial == null) return;
  showDialog<void>(context: context, builder: (_) => TutorialStepper(service: service, tutorial: tutorial));
}

class TutorialStepper extends StatefulWidget {
  const TutorialStepper({required this.service, required this.tutorial, super.key});
  final HelpService service; final Map<String, dynamic> tutorial;
  @override State<TutorialStepper> createState() => _TutorialStepperState();
}
class _TutorialStepperState extends State<TutorialStepper> {
  int current = 0;
  late final List<Map<String, dynamic>> steps;
  @override void initState() {
    super.initState();
    steps = (widget.tutorial['pasos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      for (final step in steps) { precacheImage(AssetImage(step['imagen'] as String), context).catchError((_) {}); }
    });
  }
  @override Widget build(BuildContext context) => AlertDialog(
    title: Semantics(header: true, child: Text(widget.tutorial['titulo'] as String)),
    content: SizedBox(width: 560, height: 470, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Paso ${current + 1} de ${steps.length}', semanticsLabel: 'Paso ${current + 1} de ${steps.length}'),
      Expanded(child: SingleChildScrollView(child: Stepper(
        type: StepperType.vertical,
        currentStep: current,
        onStepContinue: () { if (current + 1 < steps.length) { setState(() => current++); } else { Navigator.pop(context); } },
        onStepCancel: current > 0 ? () => setState(() => current--) : null,
        controlsBuilder: (context, details) => Padding(padding: const EdgeInsets.only(top: 12), child: Row(children: [
          if (current > 0) TextButton(onPressed: details.onStepCancel, child: const Text('Anterior')),
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cerrar')),
          const Spacer(), FilledButton(onPressed: details.onStepContinue, child: Text(current + 1 == steps.length ? 'Terminar' : 'Siguiente')),
        ])),
        steps: List.generate(steps.length, (index) {
          final step = steps[index];
          return Step(title: Text('Paso ${index + 1}'), isActive: index <= current,
            state: index < current ? StepState.complete : StepState.indexed,
            content: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              ClipRRect(borderRadius: BorderRadius.circular(12), child: Image.asset(step['imagen'] as String, height: 150, width: double.infinity, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const SizedBox(height: 0))),
              const SizedBox(height: 12), Text(step['texto'] as String),
            ]));
        }),
      ))),
    ])),
  );
}

class ContextBanner extends StatelessWidget {
  const ContextBanner({required this.notice, required this.onDismiss, required this.onNeverDismiss, required this.onAction, super.key});
  final Map<String, dynamic> notice; final VoidCallback onDismiss; final VoidCallback onNeverDismiss; final VoidCallback onAction;
  @override Widget build(BuildContext context) => MaterialBanner(
    content: Row(children: [Expanded(child: Text(notice['mensaje'] as String)), IconButton(tooltip: 'Cerrar aviso', onPressed: onDismiss, icon: const Icon(Icons.close))]),
    leading: const Icon(Icons.lightbulb_outline),
    actions: [TextButton(onPressed: onNeverDismiss, child: const Text('No mostrar de nuevo')), TextButton(onPressed: onAction, child: const Text('Abrir'))],
  );
}

class FaqScreen extends StatefulWidget {
  const FaqScreen({required this.service, required this.database, this.onReplayTour, this.onSetupEntity, super.key});
  final HelpService service; final AppDatabase database; final VoidCallback? onReplayTour; final VoidCallback? onSetupEntity;
  @override State<FaqScreen> createState() => _FaqScreenState();
}
class _FaqScreenState extends State<FaqScreen> {
  final searchController = TextEditingController();
  @override void dispose() { searchController.dispose(); super.dispose(); }
  @override Widget build(BuildContext context) {
    final filtered = widget.service.search(searchController.text);
    final tutorials = filtered['tutoriales']!;
    final faqs = filtered['preguntas_frecuentes']!;
    final tooltips = filtered['tooltips']!;
    return Scaffold(appBar: AppBar(title: const Text('Ayuda')), body: ListView(padding: const EdgeInsets.all(16), children: [
      TextField(controller: searchController, onChanged: (_) => setState(() {}), decoration: const InputDecoration(prefixIcon: Icon(Icons.search), labelText: 'Buscar en la ayuda', border: OutlineInputBorder())),
      const SizedBox(height: 14),
      FilledButton.tonalIcon(onPressed: widget.onReplayTour, icon: const Icon(Icons.replay), label: const Text('Ver tour de nuevo')),
      OutlinedButton.icon(onPressed: widget.onSetupEntity, icon: const Icon(Icons.business_outlined), label: const Text('Completar datos de entidad')),
      const SizedBox(height: 18), const Text('Tutoriales', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      ...tutorials.map((t) => ListTile(leading: const Icon(Icons.menu_book_outlined), title: Text(t['titulo'] as String), subtitle: Text(t['resumen'] as String? ?? ''), onTap: () => showTutorial(context, widget.service, t['id'] as String))),
      const SizedBox(height: 18), const Text('Preguntas frecuentes', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      ...faqs.map((f) => ExpansionTile(title: Text(f['pregunta'] as String), children: [Padding(padding: const EdgeInsets.all(16), child: Text(f['respuesta'] as String)), if (f['tutorialId'] is String) TextButton(onPressed: () => showTutorial(context, widget.service, f['tutorialId'] as String), child: const Text('Ver tutorial relacionado'))])),
      if (tooltips.isNotEmpty) ...[const SizedBox(height: 18), const Text('Ayuda por campo', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)), ...tooltips.map((tip) => ExpansionTile(title: Text(tip['titulo'] as String), children: [Padding(padding: const EdgeInsets.all(16), child: Text('${tip['cuerpo']}\n\n${tip['normativa'] ?? ''}'))]))],
    ]));
  }
}

class OnboardingFlow extends StatefulWidget {
  const OnboardingFlow({required this.service, required this.database, required this.onDone, this.initialIndex = 0, super.key});
  final HelpService service; final AppDatabase database; final VoidCallback onDone; final int initialIndex;
  @override State<OnboardingFlow> createState() => _OnboardingFlowState();
}
class _OnboardingFlowState extends State<OnboardingFlow> {
  late final controller = PageController(initialPage: widget.initialIndex);
  final name = TextEditingController(); final nit = TextEditingController(); final activity = TextEditingController();
  late int index = widget.initialIndex; String catalogType = 'paladar'; bool sampleAdded = false; bool demoAdded = false;
  List<Map<String, dynamic>> get steps => (widget.service.content['onboarding']['pasos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  @override void initState() { super.initState(); _loadProfile(); WidgetsBinding.instance.addPostFrameCallback((_) { for (final step in steps) { precacheImage(AssetImage(step['imagen'] as String), context).catchError((_) {}); } }); }
  Future<void> _loadProfile() async { final profile = await widget.service.obtenerPerfilEntidad(); name.text = profile['nombre']?.toString() ?? ''; nit.text = profile['nit']?.toString() ?? ''; activity.text = profile['actividad']?.toString() ?? ''; sampleAdded = await widget.service.catalogoEjemploCargado(catalogType); demoAdded = await widget.service.fichaDemoId() != null; if (mounted) setState(() {}); }
  @override void dispose() { controller.dispose(); name.dispose(); nit.dispose(); activity.dispose(); super.dispose(); }
  Future<void> _finish() async { await widget.service.guardarPerfilEntidad(nombre: name.text, nit: nit.text, actividad: activity.text); await widget.service.marcarOnboardingCompletado(); if (mounted) widget.onDone(); }
  Future<void> _addSample() async {
    if (await widget.service.catalogoEjemploCargado(catalogType)) { if (mounted) setState(() => sampleAdded = true); return; }
    final sample = Map<String, dynamic>.from(widget.service.content['datos_inicio']['catalogos'][catalogType] as Map);
    final id = const Uuid();
    for (final item in (sample['insumos'] as List).cast<Map>()) {
      final value = {'id': id.v4(), 'nombre': item['nombre'], 'unidadMedida': item['unidadMedida'], 'costoUnitario': {'valor': item['costoUnitario'], 'moneda': item['moneda']}};
      await widget.database.guardarCatalogo(value['id'] as String, 'insumo', jsonEncode(value));
    }
    for (final item in (sample['tarifas'] as List).cast<Map>()) {
      final value = {'id': id.v4(), 'cargo': item['cargo'], 'unidadTarifa': item['unidadTarifa'], 'tarifa': {'valor': item['valor'], 'moneda': item['moneda']}};
      await widget.database.guardarCatalogo(value['id'] as String, 'tarifa', jsonEncode(value));
    }
    await widget.service.marcarCatalogoEjemploCargado(catalogType);
    if (mounted) setState(() => sampleAdded = true);
  }
  Future<void> _addDemo() async {
    final existingDemo = await widget.service.fichaDemoId();
    if (existingDemo != null) { if (mounted) setState(() => demoAdded = true); return; }
    if (demoAdded) return;
    final data = Map<String, dynamic>.from(widget.service.content['datos_inicio']['ficha_demo'] as Map);
    final lines = (data['partidas'] as List).map((raw) { final p = Map<String, dynamic>.from(raw as Map); return PartidaCosto(categoria: CategoriaCosto.values.byName(p['categoria']), descripcion: p['descripcion'], cantidad: (p['cantidad'] as num).toDouble(), unidadMedida: p['unidadMedida'], costoUnitario: Importe((p['precioUnitario'] as num).toDouble(), Moneda.values.byName(p['moneda']))); }).toList();
    final ficha = FichaCosto(nombre: data['nombre'], descripcion: data['descripcion'], partidas: lines);
    final doc = ficha.toDocument(); final record = Map<String, dynamic>.from(doc['ficha']);
    await widget.database.guardarDocumento(record['id'], record['nombre'], record['estado'], record['fechaActualizacion'], jsonEncode(doc));
    await widget.service.marcarFichaDemo(record['id'] as String);
    if (mounted) setState(() => demoAdded = true);
  }
  void _next() async { if (index == 1) await widget.service.guardarPerfilEntidad(nombre: name.text, nit: nit.text, actividad: activity.text); if (index + 1 < steps.length) { setState(() => index++); controller.nextPage(duration: const Duration(milliseconds: 250), curve: Curves.easeOut); } else { await _finish(); } }
  @override Widget build(BuildContext context) {
    final step = steps[index];
    return Scaffold(appBar: AppBar(title: const Text('Primeros pasos'), actions: [TextButton(onPressed: _finish, child: const Text('Saltar'))]),
      body: SafeArea(child: Column(children: [Expanded(child: PageView(controller: controller, physics: const NeverScrollableScrollPhysics(), children: steps.map((s) => _stepPage(Map<String, dynamic>.from(s as Map))).toList())),
        Padding(padding: const EdgeInsets.all(16), child: Row(children: [Text('Paso ${index + 1} de ${steps.length}'), const Spacer(), if (index > 0) TextButton(onPressed: () { setState(() => index--); controller.previousPage(duration: const Duration(milliseconds: 200), curve: Curves.easeOut); }, child: const Text('Anterior')), FilledButton(onPressed: _next, child: Text(index == steps.length - 1 ? 'Empezar' : 'Siguiente'))]))])));
  }
  Widget _stepPage(Map<String, dynamic> step) => LayoutBuilder(builder: (context, constraints) => SingleChildScrollView(padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12), child: ConstrainedBox(constraints: BoxConstraints(minHeight: constraints.maxHeight - 24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Semantics(header: true, child: Text(step['titulo'] as String, style: Theme.of(context).textTheme.headlineSmall)), const SizedBox(height: 12),
    Center(child: Image.asset(step['imagen'] as String, height: 170, fit: BoxFit.contain, errorBuilder: (_, __, ___) => const SizedBox(height: 8))), const SizedBox(height: 14), Text(step['cuerpo'] as String),
    if (step['id'] == 'configurar_entidad') ...[
      const SizedBox(height: 16), TextField(controller: name, decoration: InputDecoration(label: HelpLabel(service: widget.service, tooltipId: 'campo_entidad_nombre', label: 'Nombre de la entidad'))),
      TextField(controller: nit, decoration: InputDecoration(label: HelpLabel(service: widget.service, tooltipId: 'campo_entidad_nit', label: 'NIT'))),
      TextField(controller: activity, decoration: InputDecoration(label: HelpLabel(service: widget.service, tooltipId: 'campo_entidad_actividad', label: 'Actividad económica'))),
    ],
    if (step['id'] == 'catalogos_iniciales') ...[
      const SizedBox(height: 16), DropdownButtonFormField<String>(value: catalogType, decoration: const InputDecoration(labelText: 'Ejemplo de catálogo'), items: const [DropdownMenuItem(value: 'paladar', child: Text('Paladar')), DropdownMenuItem(value: 'cafeteria', child: Text('Cafetería'))], onChanged: (v) async { final selected = v ?? 'paladar'; final loaded = await widget.service.catalogoEjemploCargado(selected); if (mounted) setState(() { catalogType = selected; sampleAdded = loaded; }); }),
      OutlinedButton.icon(onPressed: _addSample, icon: const Icon(Icons.inventory_2_outlined), label: Text(sampleAdded ? 'Ejemplos cargados' : 'Cargar y editar ejemplos')),
    ],
    if (step['id'] == 'primera_ficha') ...[
      const SizedBox(height: 16), OutlinedButton.icon(onPressed: _addDemo, icon: const Icon(Icons.description_outlined), label: Text(demoAdded ? 'Ficha de práctica creada' : 'Crear ficha demostrativa editable')),
      if (demoAdded) const Text('La ficha demostrativa se puede borrar desde la lista de fichas.'),
    ],
  ]))));
}
