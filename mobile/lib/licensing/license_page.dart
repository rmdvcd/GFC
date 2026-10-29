import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/app_database.dart';
import '../help/help_service.dart';
import '../help/help_widgets.dart';
import 'licensing_models.dart';
import 'licensing_service.dart';

class LicenciaPage extends StatefulWidget {
  const LicenciaPage({required this.db, required this.help, super.key});
  final AppDatabase db; final HelpService help;
  @override State<LicenciaPage> createState() => _LicenciaPageState();
}

class _LicenciaPageState extends State<LicenciaPage> {
  late final LicensingService service = LicensingService(widget.db);
  late Future<EstadoLicenciaActual> estado = service.estadoActual();
  String? fingerprint;
  bool importing = false;

  Future<void> _refresh() async {
    widget.help.invalidarCacheLicencia();
    setState(() { estado = service.estadoActual(); });
    try { fingerprint = await service.huellaDispositivo(); } catch (_) { fingerprint = null; }
    if (mounted) setState(() {});
  }

  Future<void> _importar() async {
    final picked = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: const ['lic']);
    if (picked == null || picked.files.isEmpty || picked.files.first.path == null) return;
    setState(() => importing = true);
    final result = await service.importarLicencia(File(picked.files.first.path!));
    if (!mounted) return;
    setState(() { importing = false; estado = service.estadoActual(); });
    final title = result.estado == EstadoLicencia.valida
        ? 'Licencia instalada'
        : result.payload != null && result.estado == EstadoLicencia.expirada
            ? 'Licencia instalada, pero expirada'
            : 'No se pudo instalar la licencia';
    await showDialog<void>(context: context, builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(result.motivoRechazo ?? result.advertencia ?? 'La licencia fue validada y guardada en la base local cifrada.'),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cerrar'))],
    ));
    await _refresh();
  }

  String _label(EstadoLicencia value) => switch (value) {
    EstadoLicencia.valida => 'Válida',
    EstadoLicencia.expirada => 'Expirada',
    EstadoLicencia.fingerprintNoCoincide => 'No corresponde a este dispositivo',
    EstadoLicencia.firmaInvalida => 'Firma inválida',
    EstadoLicencia.schemaInvalido => 'Archivo no válido',
    EstadoLicencia.noInstalada => 'No instalada',
  };

  @override Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Licencia y dispositivo'), actions: [IconButton(tooltip: 'Actualizar', onPressed: _refresh, icon: const Icon(Icons.refresh))]),
    body: FutureBuilder<EstadoLicenciaActual>(future: estado, builder: (context, snapshot) {
      if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
      final current = snapshot.data!;
      final active = current.estado == EstadoLicencia.valida;
      return ListView(padding: const EdgeInsets.all(16), children: [
        FutureBuilder<List<Map<String, dynamic>>>(future: widget.help.evaluarAvisosContextuales(context: {'screen': 'licencia', 'license_days_remaining': current.diasHastaExpiracion}, pantalla: 'licencia'), builder: (context, notices) => Column(children: [
          if (notices.hasData) ...notices.data!.map((notice) => ContextBanner(notice: notice,
            onDismiss: () => widget.help.marcarAvisoDescartado(notice['id'] as String),
            onNeverDismiss: () => widget.help.marcarAvisoDescartado(notice['id'] as String, noMostrarDeNuevo: true),
            onAction: () => widget.help.marcarAvisoDescartado(notice['id'] as String))),
        ])),
        Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Estado: ${_label(current.estado)}', style: Theme.of(context).textTheme.titleLarge),
          Padding(padding: const EdgeInsets.only(top: 8), child: HelpLabel(service: widget.help, tooltipId: 'licencia_tipo', label: 'Tipo de licencia: ${current.tipo ?? '—'}')),
          if (current.diasHastaExpiracion != null) Text('Días hasta expiración: ${current.diasHastaExpiracion}'),
          if (current.fichasRestantes != null) Text('Fichas restantes: ${current.fichasRestantes}'),
          if (current.features.isNotEmpty) Text('Funciones habilitadas: ${current.features.join(', ')}'),
          if (current.motivoRechazo != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(current.motivoRechazo!, style: TextStyle(color: active ? null : Theme.of(context).colorScheme.error))),
          if (current.advertencia != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(current.advertencia!, style: TextStyle(color: Theme.of(context).colorScheme.tertiary))),
        ]))),
        const SizedBox(height: 8),
        HelpLabel(service: widget.help, tooltipId: 'licencia_fingerprint', label: 'ID de este dispositivo', style: const TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 6),
        SelectableText(fingerprint ?? 'No disponible en esta plataforma'),
        Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: fingerprint == null ? null : () async {
          await Clipboard.setData(ClipboardData(text: fingerprint!));
          if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('ID copiado')));
        }, icon: const Icon(Icons.copy), label: const Text('Copiar ID'))),
        const SizedBox(height: 12),
        FilledButton.icon(onPressed: importing ? null : _importar, icon: importing ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.upload_file), label: const Text('Importar archivo .lic')),
        TextButton.icon(onPressed: () => showTutorial(context, widget.help, 'tutorial_importar_licencia'), icon: const Icon(Icons.menu_book), label: const Text('Ver tutorial de importación')),
        const SizedBox(height: 16),
        const Text('Sin una licencia activa puede consultar sus fichas existentes y exportar PDF con la marca «VERSIÓN NO LICENCIADA». La validación usa la hora y la base de datos locales; no existe un reloj o servicio de revocación confiable mientras el equipo permanezca desconectado.'),
      ]);
    }),
  );
}
