import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';
import 'data/app_database.dart';
import 'data/fichas_repository_sqlcipher.dart';
import 'data/intercambio.dart';
import 'data/ficha148_validator.dart';
import 'data/document_exports.dart';
import 'domain/models.dart';
import 'presentation/fichas_controller.dart';
import 'licensing/licensing_service.dart';
import 'licensing/license_page.dart';
import 'backup/backup_page.dart';
import 'help/help_service.dart';
import 'help/help_widgets.dart';

void main() => runApp(const ProviderScope(child: FichaCostoApp()));

final databaseProvider = FutureProvider<AppDatabase>((ref) => abrirBaseDatos());
final controllerProvider = ChangeNotifierProvider.family<FichasController, AppDatabase>((ref, db) {
  final controller = FichasController(FichasRepositorySqlCipher(db));
  controller.cargar();
  return controller;
});

class FichaCostoApp extends StatelessWidget {
  const FichaCostoApp({super.key});
  @override Widget build(BuildContext context) => MaterialApp(title: 'FichaCosto', theme: ThemeData(colorSchemeSeed: const Color(0xff176b73), useMaterial3: true), home: const Inicio());
}

class Inicio extends ConsumerWidget {
  const Inicio({super.key});
  @override Widget build(BuildContext context, WidgetRef ref) => ref.watch(databaseProvider).when(
    loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
    error: (e, _) => Scaffold(body: Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('No se pudo abrir la base cifrada: $e')))),
    data: (db) => HelpStartup(database: db));
}

class HelpStartup extends StatefulWidget {
  const HelpStartup({required this.database, super.key});
  final AppDatabase database;
  @override State<HelpStartup> createState() => _HelpStartupState();
}
class _HelpStartupState extends State<HelpStartup> {
  late final Future<HelpService> future = HelpService.load(widget.database);
  bool completedNow = false;
  @override Widget build(BuildContext context) => FutureBuilder<HelpService>(future: future, builder: (context, snapshot) {
    if (snapshot.hasError) return Scaffold(body: Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('No se pudo cargar la ayuda offline. Puede continuar desde Ayuda.'))));
    if (!snapshot.hasData) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final help = snapshot.data!;
    return FutureBuilder<bool>(future: help.onboardingCompletado, builder: (context, state) {
      if (!state.hasData) return const Scaffold(body: Center(child: CircularProgressIndicator()));
      if (!state.data! && !completedNow) return OnboardingFlow(service: help, database: widget.database, onDone: () => setState(() => completedNow = true));
      return ListaFichas(db: widget.database, help: help);
    });
  });
}

class ListaFichas extends ConsumerWidget {
  const ListaFichas({required this.db, required this.help, super.key});
  final AppDatabase db; final HelpService help;
  @override Widget build(BuildContext context, WidgetRef ref) {
    final c = ref.watch(controllerProvider(db));
    final ctrl = ref.read(controllerProvider(db));
    return Scaffold(appBar: AppBar(title: const Text('FichaCosto'), actions: [
      IconButton(tooltip: 'Ayuda', icon: const Icon(Icons.help_outline), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => FaqScreen(service: help, database: db, onReplayTour: () {
        Navigator.push(context, MaterialPageRoute(builder: (tourContext) => OnboardingFlow(service: help, database: db, onDone: () => Navigator.pop(tourContext))));
      }, onSetupEntity: () {
        Navigator.push(context, MaterialPageRoute(builder: (tourContext) => OnboardingFlow(service: help, database: db, initialIndex: 1, onDone: () => Navigator.pop(tourContext))));
      })))),
      IconButton(tooltip: 'Licencia y dispositivo', icon: const Icon(Icons.verified_user_outlined), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => LicenciaPage(db: db, help: help)))),
      IconButton(tooltip: 'Respaldo cifrado', icon: const Icon(Icons.backup_outlined), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => BackupPage(db: db, help: help)))),
      IconButton(tooltip: 'Importar .ficha148', icon: const Icon(Icons.file_open), onPressed: () async {
        final result = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['ficha148']);
        if (result == null || result.files.isEmpty || result.files.first.path == null) return;
        try {
          final summary = await IntercambioFicha148.validarArchivo(File(result.files.first.path!));
          if (!context.mounted) return;
          final confirm = await showDialog<bool>(context: context, builder: (dialogContext) => AlertDialog(
            title: const Text('Validación correcta'),
            content: Text('Ficha: ${(summary.document['ficha'] as Map<String, dynamic>)['nombre']}\nEntidad: ${summary.entity}\nPeríodo: ${summary.period}\nCosto total: ${summary.cup.toStringAsFixed(2)} CUP · ${summary.mlc.toStringAsFixed(2)} MLC\n\n¿Desea incorporar esta ficha a la base local cifrada?'),
            actions: [TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancelar')), FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Importar'))],
          ));
          if (confirm != true || !context.mounted) return;
          try {
            await FichasRepositorySqlCipher(db).importar(summary.document);
          } catch (_) {
            if (context.mounted) _mensaje(context, 'No se pudo guardar la ficha validada en la base local cifrada.');
            return;
          }
          await ctrl.cargar();
          if (context.mounted) _mensaje(context, 'Ficha validada e importada correctamente');
        } on Ficha148ValidationException catch (e) {
          if (context.mounted) await _mostrarErroresImportacion(context, e.messages);
        } catch (_) {
          if (context.mounted) _mensaje(context, 'No se pudo leer el paquete .ficha148. Compruebe el archivo e inténtelo nuevamente.');
        }
      }),
      IconButton(tooltip: 'Catálogos', icon: const Icon(Icons.inventory_2_outlined), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CatalogosPage(db: db, help: help))))]),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: help.evaluarAvisosContextuales(context: {'screen': 'fichas', 'has_data': c.fichas.isNotEmpty}, pantalla: 'fichas'),
        builder: (context, noticeSnapshot) => Column(children: [
          if (noticeSnapshot.hasData && noticeSnapshot.data!.isNotEmpty) ...noticeSnapshot.data!.map((notice) => ContextBanner(
            notice: notice,
            onDismiss: () { help.marcarAvisoDescartado(notice['id'] as String); ctrl.cargar(); },
            onNeverDismiss: () { help.marcarAvisoDescartado(notice['id'] as String, noMostrarDeNuevo: true); ctrl.cargar(); },
            onAction: () { help.marcarAvisoDescartado(notice['id'] as String); _openHelpAction(context, db, help, notice['accion'] as Map); },
          )),
          Expanded(child: c.cargando ? const Center(child: CircularProgressIndicator()) : c.error != null ? Center(child: Text(c.error!)) : c.fichas.isEmpty
            ? const Center(child: Text('Cree una ficha o importe un archivo .ficha148'))
            : ListView.builder(itemCount: c.fichas.length, itemBuilder: (context, i) {
              final f = c.fichas[i];
              return Card(margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5), child: ListTile(
                title: Text(f.nombre), subtitle: Text('${f.estado.name} · ${f.monedaBase.name} · ${f.partidas.length} partidas'),
                onTap: () async { await Navigator.push(context, MaterialPageRoute(builder: (_) => EditorFicha(db: db, help: help, inicial: f))); await ctrl.cargar(); },
                trailing: PopupMenuButton<String>(onSelected: (v) async {
                  if (v == 'export') { try { final doc = await FichasRepositorySqlCipher(db).exportar(f.id); final file = await IntercambioFicha148.exportar(doc); if (context.mounted) _mensaje(context, 'Archivo guardado: ${file.path}'); } catch (e) { if (context.mounted) _mensaje(context, '$e'); } }
                  if (v == 'delete') { await ctrl.eliminar(f.id); }
                }, itemBuilder: (_) => const [PopupMenuItem(value: 'export', child: Text('Exportar .ficha148')), PopupMenuItem(value: 'delete', child: Text('Eliminar'))])));
            })),
        ])),
      floatingActionButton: FloatingActionButton.extended(onPressed: () async { await Navigator.push(context, MaterialPageRoute(builder: (_) => EditorFicha(db: db, help: help))); await ctrl.cargar(); }, icon: const Icon(Icons.add), label: const Text('Nueva ficha')));
  }
}

class EditorFicha extends StatefulWidget {
  const EditorFicha({required this.db, required this.help, this.inicial, super.key});
  final AppDatabase db; final HelpService help; final FichaCosto? inicial;
  @override State<EditorFicha> createState() => _EditorFichaState();
}
class _EditorFichaState extends State<EditorFicha> {
  late FichaCosto ficha;
  late TextEditingController nombre, descripcion, coefIndirecto, margen;
  late String unidadCoeficiente;
  @override void initState() { super.initState(); ficha = widget.inicial ?? FichaCosto(nombre: ''); nombre = TextEditingController(text: ficha.nombre); descripcion = TextEditingController(text: ficha.descripcion); coefIndirecto = TextEditingController(text: ficha.coeficientes.coeficienteIndirecto?.toString() ?? ''); margen = TextEditingController(text: ficha.coeficientes.margenGanancia?.toString() ?? ''); unidadCoeficiente = ficha.coeficientes.unidadCoeficiente; }
  @override void dispose() { nombre.dispose(); descripcion.dispose(); coefIndirecto.dispose(); margen.dispose(); super.dispose(); }
  Future<void> _agregar([PartidaCosto? existente]) async {
    final form = GlobalKey<FormState>(); final desc = TextEditingController(text: existente?.descripcion ?? ''); final cant = TextEditingController(text: existente?.cantidad.toString() ?? '1'); final unit = TextEditingController(text: existente?.unidadMedida ?? 'unidad'); final price = TextEditingController(text: existente?.costoUnitario.valor.toString() ?? '0');
    var cat = existente?.categoria ?? CategoriaCosto.materias_primas_materiales; var mon = existente?.costoUnitario.moneda ?? ficha.monedaBase;
    final result = await showDialog<PartidaCosto>(context: context, builder: (ctx) => AlertDialog(title: Text(existente == null ? 'Nueva partida' : 'Editar partida'), content: Form(key: form, child: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
      Row(children: [Expanded(child: DropdownButtonFormField(value: cat, decoration: const InputDecoration(labelText: 'Categoría'), items: CategoriaCosto.values.map((c) => DropdownMenuItem(value: c, child: Text(c.name.replaceAll('_', ' ')))).toList(), onChanged: (v) => cat = v!)), IconButton(tooltip: 'Ayuda de la categoría', icon: const Icon(Icons.help_outline), onPressed: () { final tip = switch (cat) { CategoriaCosto.materias_primas_materiales => 'campo_fila_1', CategoriaCosto.fuerza_trabajo_directa => 'campo_fila_4', CategoriaCosto.gastos_indirectos_produccion => 'campo_fila_5', CategoriaCosto.otros_gastos_directos => 'campo_fila_7' }; showTooltip(ctx, widget.help, tip); })]),
      TextFormField(controller: desc, decoration: const InputDecoration(labelText: 'Descripción'), validator: (v) => v == null || v.isEmpty ? 'Obligatorio' : null),
      TextFormField(controller: cant, decoration: const InputDecoration(labelText: 'Cantidad'), keyboardType: TextInputType.number),
      TextFormField(controller: unit, decoration: const InputDecoration(labelText: 'Unidad de medida')),
      TextFormField(controller: price, decoration: const InputDecoration(labelText: 'Costo unitario'), keyboardType: TextInputType.number),
      Row(children: [Expanded(child: DropdownButtonFormField(value: mon, decoration: const InputDecoration(labelText: 'Moneda'), items: Moneda.values.map((m) => DropdownMenuItem(value: m, child: Text(m.name))).toList(), onChanged: (v) => mon = v!)), HelpTooltip(service: widget.help, id: 'selector_moneda')]),
    ]))), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')), FilledButton(onPressed: () { if (form.currentState!.validate()) Navigator.pop(ctx, PartidaCosto(id: existente?.id, categoria: cat, descripcion: desc.text, cantidad: double.tryParse(cant.text) ?? 0, unidadMedida: unit.text, costoUnitario: Importe(double.tryParse(price.text) ?? 0, mon))); }, child: const Text('Añadir'))]));
    if (result != null) setState(() { final index = ficha.partidas.indexWhere((p) => p.id == result.id); if (index < 0) { ficha.partidas.add(result); } else { ficha.partidas[index] = result; } });
  }
  Future<void> _guardar() async {
    if (nombre.text.trim().isEmpty) { _mensaje(context, 'El nombre es obligatorio'); return; }
    final licensing = LicensingService(widget.db);
    final usaMultimoneda = ficha.monedaBase == Moneda.MLC || ficha.partidas.any((p) => p.costoUnitario.moneda == Moneda.MLC);
    if (usaMultimoneda && !await licensing.tieneFeature('multimoneda')) {
      if (mounted) _mensaje(context, 'El uso de MLC requiere una licencia activa con la función multimoneda. Puede consultar las fichas existentes o importar una licencia.');
      return;
    }
    if (widget.inicial == null && !await licensing.consumirFeature('fichas')) {
      if (mounted) _mensaje(context, 'No hay licencia activa para crear fichas o se alcanzó el límite. Las fichas existentes siguen disponibles; importe una licencia o revise su límite.');
      return;
    }
    final updated = FichaCosto(id: ficha.id, nombre: nombre.text.trim(), descripcion: descripcion.text,
      fechaCreacion: DateTime.parse(ficha.fechaCreacion), fechaActualizacion: DateTime.now().toUtc(), estado: ficha.estado,
      monedaBase: ficha.monedaBase, partidas: ficha.partidas, coeficientes: Coeficientes(coeficienteIndirecto: double.tryParse(coefIndirecto.text), margenGanancia: double.tryParse(margen.text), unidadCoeficiente: unidadCoeficiente), catalogosSnapshot: ficha.catalogosSnapshot, extensionData: ficha.extensionData);
    await FichasRepositorySqlCipher(widget.db).guardar(updated);
    if (mounted) Navigator.pop(context);
  }
  @override Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: Text(widget.inicial == null ? 'Nueva ficha' : 'Editar ficha'), actions: [IconButton(tooltip: 'Tutorial para crear una ficha', icon: const Icon(Icons.menu_book_outlined), onPressed: () => showTutorial(context, widget.help, 'tutorial_crear_ficha')), PopupMenuButton<String>(onSelected: (v) async { try { final doc = FichaCosto(id: ficha.id, nombre: nombre.text, descripcion: descripcion.text, fechaCreacion: DateTime.parse(ficha.fechaCreacion), estado: ficha.estado, monedaBase: ficha.monedaBase, partidas: ficha.partidas, coeficientes: Coeficientes(coeficienteIndirecto: double.tryParse(coefIndirecto.text), margenGanancia: double.tryParse(margen.text), unidadCoeficiente: unidadCoeficiente), catalogosSnapshot: ficha.catalogosSnapshot, extensionData: ficha.extensionData); final licensing = LicensingService(widget.db); final licenseState = await licensing.estadoActual(); final watermark = licenseState.pdfConMarcaAgua; if (v == 'pdf_preview') { await ExportacionesDocumento.previsualizarPdf(doc, marcaAgua: watermark); return; } if (v != 'pdf' && !await licensing.consumirFeature('import_export')) { throw Exception('La exportación avanzada requiere una licencia activa con la función de importación/exportación.'); } final repository = FichasRepositorySqlCipher(widget.db); final document = doc.toDocument(); final payload = v == 'ficha148' ? await repository.conSnapshotCatalogos(document) : document; File file; if (v == 'ficha148') { file = await IntercambioFicha148.exportar(payload); } else if (v == 'pdf') { file = await ExportacionesDocumento.pdf(doc, marcaAgua: watermark); await widget.help.registrarPdfExportado(doc.id); } else if (v == 'csv') { file = await ExportacionesDocumento.csv(doc); } else { file = await ExportacionesDocumento.excel(doc); } await Share.shareXFiles([XFile(file.path)], text: 'Exportación FichaCosto'); if (context.mounted) _mensaje(context, 'Archivo exportado: ${file.path}'); } catch (e) { if (context.mounted) _mensaje(context, 'Error de exportación: $e'); } }, itemBuilder: (_) => const [PopupMenuItem(value: 'ficha148', child: Text('Exportar .ficha148')), PopupMenuItem(value: 'pdf_preview', child: Text('Vista previa / imprimir PDF')), PopupMenuItem(value: 'pdf', child: Text('Exportar PDF')), PopupMenuItem(value: 'csv', child: Text('Exportar CSV')), PopupMenuItem(value: 'xlsx', child: Text('Exportar Excel'))]), IconButton(onPressed: _guardar, icon: const Icon(Icons.save))]),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      FutureBuilder<List<Map<String, dynamic>>>(future: widget.help.evaluarAvisosContextuales(context: {'screen': 'editor_ficha', 'has_data': ficha.partidas.isNotEmpty}, pantalla: 'editor_ficha'), builder: (context, snapshot) {
        if (!snapshot.hasData || snapshot.data!.isEmpty) return const SizedBox.shrink();
        final notice = snapshot.data!.first;
        return ContextBanner(notice: notice,
          onDismiss: () => widget.help.marcarAvisoDescartado(notice['id'] as String),
          onNeverDismiss: () => widget.help.marcarAvisoDescartado(notice['id'] as String, noMostrarDeNuevo: true),
          onAction: () { widget.help.marcarAvisoDescartado(notice['id'] as String); _openHelpAction(context, widget.db, widget.help, notice['accion'] as Map); });
      }),
      TextField(controller: nombre, decoration: InputDecoration(label: HelpLabel(service: widget.help, tooltipId: 'campo_nombre_ficha', label: 'Producto o servicio'))),
      TextField(controller: descripcion, decoration: const InputDecoration(labelText: 'Descripción'), maxLines: 2), const SizedBox(height: 16),
      Row(children: [const Expanded(child: Text('Partidas de costo', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold))), IconButton(onPressed: _agregar, icon: const Icon(Icons.add_circle))]),
      ...ficha.partidas.map((p) => ListTile(title: Text(p.descripcion), subtitle: Text('${p.cantidad} ${p.unidadMedida} × ${p.costoUnitario.valor} ${p.costoUnitario.moneda.name} = ${p.subtotal.valor.toStringAsFixed(2)} ${p.subtotal.moneda.name}\n${p.categoria.name.replaceAll('_', ' ')}'), isThreeLine: true, trailing: Row(mainAxisSize: MainAxisSize.min, children: [IconButton(icon: const Icon(Icons.edit_outlined), onPressed: () => _agregar(p)), IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => setState(() => ficha.partidas.remove(p)))]))),
      Card(child: Padding(padding: const EdgeInsets.all(14), child: Text('Costo total: ${(ficha.totales['costoTotal']['CUP'] as num).toStringAsFixed(2)} CUP · ${(ficha.totales['costoTotal']['MLC'] as num).toStringAsFixed(2)} MLC', style: const TextStyle(fontWeight: FontWeight.bold)))),
      if (ficha.totales['precioCalculado'] != null) Text('Precio estimado: ${(ficha.totales['precioCalculado']['CUP'] as num).toStringAsFixed(2)} CUP · ${(ficha.totales['precioCalculado']['MLC'] as num).toStringAsFixed(2)} MLC', style: const TextStyle(fontWeight: FontWeight.bold)),
      Row(children: [const Expanded(child: Text('Los valores CUP y MLC se totalizan por separado.')), HelpTooltip(service: widget.help, id: 'selector_moneda')]),
      ExpansionTile(title: const Text('Guía de las filas 1–11 del modelo'), children: List.generate(11, (i) { final id = 'campo_fila_${i + 1}'; final item = widget.help.getTooltip(id)!; return ListTile(title: Text(item['titulo'] as String), trailing: HelpTooltip(service: widget.help, id: id)); })),
      TextButton.icon(onPressed: () => showTutorial(context, widget.help, 'tutorial_crear_ficha'), icon: const Icon(Icons.menu_book), label: const Text('Ver tutorial paso a paso')),
      DropdownButtonFormField(value: ficha.estado, decoration: const InputDecoration(labelText: 'Estado'), items: EstadoFicha.values.map((e) => DropdownMenuItem(value: e, child: Text(e.name))).toList(), onChanged: (v) { if (v != null) setState(() => ficha = FichaCosto(id: ficha.id, nombre: ficha.nombre, descripcion: ficha.descripcion, fechaCreacion: DateTime.parse(ficha.fechaCreacion), estado: v, monedaBase: ficha.monedaBase, partidas: ficha.partidas, coeficientes: Coeficientes(coeficienteIndirecto: double.tryParse(coefIndirecto.text), margenGanancia: double.tryParse(margen.text), unidadCoeficiente: unidadCoeficiente), catalogosSnapshot: ficha.catalogosSnapshot, extensionData: ficha.extensionData)); }),
      TextField(controller: coefIndirecto, decoration: const InputDecoration(labelText: 'Coeficiente indirecto (dato conservado; no se aplica automáticamente)'), keyboardType: TextInputType.number),
      TextField(controller: margen, decoration: InputDecoration(label: HelpLabel(service: widget.help, tooltipId: 'margen_utilidad', label: 'Margen de ganancia')), keyboardType: TextInputType.number),
      DropdownButtonFormField<String>(value: unidadCoeficiente, decoration: const InputDecoration(labelText: 'Interpretar margen como'), items: const [DropdownMenuItem(value: 'porcentaje', child: Text('Porcentaje')), DropdownMenuItem(value: 'factor', child: Text('Factor'))], onChanged: (v) { if (v != null) setState(() => unidadCoeficiente = v); }),
      const Text('Precio estimado configurable; no es una fórmula normativa. Porcentaje: costo × (1 + margen/100); factor: costo × factor.'),
      const SizedBox(height: 18), FilledButton.icon(onPressed: _guardar, icon: const Icon(Icons.save), label: const Text('Guardar ficha'))]));
}

class CatalogosPage extends StatefulWidget { const CatalogosPage({required this.db, required this.help, super.key}); final AppDatabase db; final HelpService help; @override State<CatalogosPage> createState() => _CatalogosPageState(); }
class _CatalogosPageState extends State<CatalogosPage> {
  List<Map<String, dynamic>> insumos = [], tarifas = [];
  @override void initState() { super.initState(); _cargar(); }
  Future<void> _cargar() async { final repo = FichasRepositorySqlCipher(widget.db); insumos = await repo.listarInsumos(); tarifas = await repo.listarTarifas(); if (mounted) setState(() {}); }

  Future<void> _editar(bool salario, [Map<String, dynamic>? existente]) async {
    final nombre = TextEditingController(text: existente == null ? '' : (salario ? existente['cargo'] : existente['nombre']));
    final unidad = TextEditingController(text: existente == null ? (salario ? 'hora' : 'unidad') : (salario ? existente['unidadTarifa'] : existente['unidadMedida']));
    final datosImporte = existente == null ? null : (salario ? existente['tarifa'] : existente['costoUnitario']);
    final valor = TextEditingController(text: datosImporte?['valor']?.toString() ?? '0');
    var moneda = Moneda.values.byName(datosImporte?['moneda'] ?? 'CUP');
    await showDialog(context: context, builder: (ctx) => AlertDialog(
      title: Text(existente == null ? (salario ? 'Nueva tarifa salarial' : 'Nuevo insumo') : 'Editar catálogo'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: nombre, decoration: InputDecoration(labelText: salario ? 'Cargo' : 'Nombre')),
        TextField(controller: unidad, decoration: InputDecoration(labelText: salario ? 'Unidad de tarifa' : 'Unidad de medida')),
        TextField(controller: valor, decoration: const InputDecoration(labelText: 'Tarifa / costo unitario'), keyboardType: TextInputType.number),
        Row(children: [Expanded(child: DropdownButton<Moneda>(value: moneda, items: Moneda.values.map((m) => DropdownMenuItem(value: m, child: Text(m.name))).toList(), onChanged: (v) => moneda = v!)), HelpTooltip(service: widget.help, id: 'selector_moneda')]),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')), FilledButton(onPressed: () async {
        final repo = FichasRepositorySqlCipher(widget.db); final id = existente?['id']; final amount = Importe(double.tryParse(valor.text) ?? 0, moneda);
        if (salario) { await repo.guardarTarifa(TarifaSalario(id: id, cargo: nombre.text, unidadTarifa: unidad.text, tarifa: amount)); }
        else { await repo.guardarInsumo(Insumo(id: id, nombre: nombre.text, unidadMedida: unidad.text, costoUnitario: amount)); }
        if (ctx.mounted) Navigator.pop(ctx);
      }, child: const Text('Guardar'))]));
    await _cargar();
  }

  Future<void> _eliminar(Map<String, dynamic> elemento) async { await FichasRepositorySqlCipher(widget.db).eliminarCatalogo(elemento['id']); await _cargar(); }

  @override Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('Catálogos')), body: ListView(children: [
    TextButton.icon(onPressed: () => showTutorial(context, widget.help, 'tutorial_insumos'), icon: const Icon(Icons.menu_book), label: const Text('Cómo agregar insumos')),
    const ListTile(title: Text('Insumos', style: TextStyle(fontWeight: FontWeight.bold))),
    ...insumos.map((e) => ListTile(title: Text(e['nombre']), subtitle: Text('${e['unidadMedida']} · ${e['costoUnitario']['valor']} ${e['costoUnitario']['moneda']}'), onTap: () => _editar(false, e), trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _eliminar(e)))),
    ListTile(leading: const Icon(Icons.add), title: const Text('Añadir insumo'), onTap: () => _editar(false)), const Divider(),
    const ListTile(title: Text('Tarifas salariales', style: TextStyle(fontWeight: FontWeight.bold))),
    ...tarifas.map((e) => ListTile(title: Text(e['cargo']), subtitle: Text('${e['unidadTarifa']} · ${e['tarifa']['valor']} ${e['tarifa']['moneda']}'), onTap: () => _editar(true, e), trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _eliminar(e)))),
    ListTile(leading: const Icon(Icons.add), title: const Text('Añadir tarifa'), onTap: () => _editar(true)),
  ]));
}

Future<void> _mostrarErroresImportacion(BuildContext context, List<String> errores) => showDialog<void>(
  context: context,
  builder: (dialogContext) => AlertDialog(
    title: const Text('No se pudo validar el archivo'),
    content: SingleChildScrollView(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min,
      children: errores.map((error) => Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('• $error'))).toList())),
    actions: [TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cerrar'))],
  ),
);

void _openHelpAction(BuildContext context, AppDatabase db, HelpService help, Map action) {
  final target = action['target'];
  if (action['tipo'] == 'abrir_tutorial' && target is String) { showTutorial(context, help, target); return; }
  if (target == 'catalogo_insumos') {
    Navigator.push(context, MaterialPageRoute(builder: (_) => CatalogosPage(db: db, help: help)));
  } else if (target == 'respaldo') {
    Navigator.push(context, MaterialPageRoute(builder: (_) => BackupPage(db: db, help: help)));
  } else if (target == 'licencia') {
    Navigator.push(context, MaterialPageRoute(builder: (_) => LicenciaPage(db: db, help: help)));
  } else if (target == 'configuracion_entidad') {
    Navigator.push(context, MaterialPageRoute(builder: (tourContext) => OnboardingFlow(service: help, database: db, initialIndex: 1, onDone: () => Navigator.pop(tourContext))));
  } else if (target == 'editor_ficha_nueva') {
    Navigator.push(context, MaterialPageRoute(builder: (_) => EditorFicha(db: db, help: help)));
  }
}

void _mensaje(BuildContext context, String texto) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));
