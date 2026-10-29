import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../data/app_database.dart';
import '../help/help_service.dart';
import '../help/help_widgets.dart';
import 'backup_service.dart';

class BackupPage extends StatefulWidget {
  const BackupPage({required this.db, required this.help, super.key});
  final AppDatabase db; final HelpService help;
  @override State<BackupPage> createState() => _BackupPageState();
}

class _BackupPageState extends State<BackupPage> {
  late final BackupService service = BackupService(widget.db);
  final createPassword = TextEditingController();
  final createConfirm = TextEditingController();
  final restorePassword = TextEditingController();
  File? selectedBackup;
  BackupPreview? preview;
  bool busy = false;

  @override void dispose() {
    createPassword.dispose();
    createConfirm.dispose();
    restorePassword.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    if (createPassword.text != createConfirm.text) {
      _message('Las contraseñas no coinciden.'); return;
    }
    if (createPassword.text.runes.length < 8 || fortalezaContrasena(createPassword.text) == 'Débil') {
      _message('Elija una contraseña no común, de al menos 8 caracteres y con varios tipos de caracteres.'); return;
    }
    setState(() => busy = true);
    try {
      final file = await service.crearBackup(createPassword.text);
      await widget.help.registrarRespaldoCreado();
      if (!mounted) return;
      await Share.shareXFiles([XFile(file.path)], text: 'Respaldo cifrado de FichaCosto. Guarde la contraseña por separado.');
      if (mounted) _message('Respaldo cifrado creado. No pierda la contraseña: no existe recuperación.');
    } catch (error) {
      if (mounted) _message('No se pudo crear el respaldo: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _selectBackup() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: const ['bak']);
    if (result == null || result.files.isEmpty || result.files.first.path == null) return;
    setState(() { selectedBackup = File(result.files.first.path!); preview = null; });
  }

  Future<void> _preview() async {
    final file = selectedBackup;
    if (file == null) { _message('Seleccione un archivo .ficha148.bak.'); return; }
    if (restorePassword.text.runes.length < 8) { _message('La contraseña debe tener al menos 8 caracteres.'); return; }
    setState(() => busy = true);
    try {
      final result = await service.previsualizarBackup(file, restorePassword.text);
      if (!mounted) return;
      setState(() { preview = result; });
      await _showPreview(result);
    } catch (error) {
      if (mounted) _message('$error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _showPreview(BackupPreview value) async {
    var mode = 'fusionar';
    var restoreLicense = false;
    var restoreUsage = false;
    final confirmation = TextEditingController();
    await showDialog<void>(context: context, builder: (dialogContext) => StatefulBuilder(builder: (context, updateDialog) => AlertDialog(
      title: const Text('Previsualización del respaldo'),
      content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Fecha: ${value.fechaCreacion}'),
        Text('Fichas: ${value.fichas} · Insumos: ${value.insumos} · Salarios: ${value.salarios}'),
        Text('Incluye licencia: ${value.incluyeLicencia ? 'Sí' : 'No'}'),
        SelectableText('Fingerprint origen: ${value.fingerprintOrigen}'),
        if (value.origenDiferente) const Padding(padding: EdgeInsets.only(top: 8), child: Text('Este respaldo proviene de otro dispositivo. Los datos se restaurarán, pero necesitará importar una nueva licencia para este equipo.', style: TextStyle(color: Colors.deepOrange))),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(value: mode, decoration: const InputDecoration(labelText: 'Modo de restauración'),
          items: const [DropdownMenuItem(value: 'fusionar', child: Text('Fusionar por ID')), DropdownMenuItem(value: 'reemplazar', child: Text('Reemplazar todos los datos locales'))],
          onChanged: (value) => updateDialog(() { mode = value ?? 'fusionar'; })),
        if (mode == 'reemplazar') ...[
          const Text('Esto borrará los datos actuales. Para confirmar por segunda vez, escriba REEMPLAZAR.'),
          TextField(controller: confirmation, decoration: const InputDecoration(labelText: 'Escriba REEMPLAZAR')),
        ],
        CheckboxListTile(contentPadding: EdgeInsets.zero, value: restoreLicense, title: const Text('Restaurar la licencia como referencia (no se activa en otra huella)'), onChanged: (v) => updateDialog(() => restoreLicense = v ?? false)),
        CheckboxListTile(contentPadding: EdgeInsets.zero, value: restoreUsage, title: const Text('Restaurar historial de uso'), onChanged: (v) => updateDialog(() => restoreUsage = v ?? false)),
      ])),
      actions: [TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancelar')),
        FilledButton.icon(onPressed: () async {
          if (mode == 'reemplazar' && confirmation.text != 'REEMPLAZAR') {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Escriba exactamente REEMPLAZAR para confirmar.')));
            return;
          }
          Navigator.pop(dialogContext);
          await _apply(value, mode, restoreLicense, restoreUsage);
        }, icon: const Icon(Icons.restore), label: const Text('Confirmar restauración'))],
    )));
    confirmation.dispose();
  }

  Future<void> _apply(BackupPreview value, String mode, bool restoreLicense, bool restoreUsage) async {
    setState(() => busy = true);
    try {
      final result = await service.aplicarRestauracion(value, modo: mode,
          restaurarLicencia: restoreLicense, restaurarUsage: restoreUsage);
      if (mounted) _message('Restauración completada: ${result.fichas} fichas, ${result.insumos} insumos y ${result.salarios} salarios.');
    } catch (error) {
      if (mounted) await _showRecoveryDialog('$error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _showRecoveryDialog(String error) async {
    await showDialog<void>(context: context, builder: (dialogContext) => AlertDialog(
      title: const Text('No se pudo completar la restauración'),
      content: Text('$error\n\nLa transacción fue revertida. Si había un respaldo de seguridad, puede recuperarlo ahora.'),
      actions: [TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cerrar')),
        OutlinedButton(onPressed: () async {
          Navigator.pop(dialogContext);
          try {
            final result = await service.restaurarRespaldoSeguridad();
            if (mounted) _message('Respaldo de seguridad recuperado: ${result.fichas} fichas.');
          } catch (e) { if (mounted) _message('No se pudo recuperar el respaldo interno: $e'); }
        }, child: const Text('Recuperar respaldo interno'))],
    ));
  }

  void _message(String value) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(value)));

  @override Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Respaldo y restauración cifrados')),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Crear respaldo', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const SizedBox(height: 8),
      Row(children: [const Expanded(child: Text('Contraseña del respaldo (mínimo 8 caracteres)')), HelpTooltip(service: widget.help, id: 'backup_contrasena')]),
      TextField(controller: createPassword, obscureText: true, onChanged: (_) => setState(() {}), decoration: const InputDecoration(labelText: 'Contraseña')),
      TextField(controller: createConfirm, obscureText: true, decoration: const InputDecoration(labelText: 'Repita la contraseña')),
      Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text('Fortaleza: ${fortalezaContrasena(createPassword.text)}')),
      const SizedBox(height: 8),
      FilledButton.icon(onPressed: busy ? null : _create, icon: const Icon(Icons.lock), label: const Text('Crear respaldo cifrado')),
      const Divider(height: 32),
      const Text('Restaurar respaldo', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const SizedBox(height: 8),
      OutlinedButton.icon(onPressed: busy ? null : _selectBackup, icon: const Icon(Icons.folder_open), label: Text(selectedBackup?.path.split(Platform.pathSeparator).last ?? 'Seleccionar .ficha148.bak')),
      Row(children: [Expanded(child: TextField(controller: restorePassword, obscureText: true, decoration: const InputDecoration(labelText: 'Contraseña del respaldo'))), HelpTooltip(service: widget.help, id: 'backup_contrasena')]),
      Wrap(spacing: 8, children: [TextButton.icon(onPressed: () => showTutorial(context, widget.help, 'tutorial_respaldo_cifrado'), icon: const Icon(Icons.menu_book), label: const Text('Cómo crear un respaldo')), TextButton.icon(onPressed: () => showTutorial(context, widget.help, 'tutorial_restaurar_backup'), icon: const Icon(Icons.restore), label: const Text('Restaurar en otro dispositivo'))]),
      const SizedBox(height: 8),
      FilledButton.icon(onPressed: busy ? null : _preview, icon: const Icon(Icons.visibility), label: const Text('Validar y previsualizar')),
      if (busy) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
      const SizedBox(height: 16),
      const Text('El archivo se cifra localmente con Argon2id y AES-256-GCM; no se sube a la nube. El manifiesto en claro contiene solo versión, fecha, huella de origen y contadores. Si olvida la contraseña, no hay recuperación posible.'),
    ]),
  );
}
