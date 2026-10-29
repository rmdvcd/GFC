import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:json_schema/json_schema.dart';

import '../data/app_database.dart';
import '../licensing/licensing_models.dart';
import '../licensing/licensing_service.dart';

class HelpContentException implements Exception {
  const HelpContentException(this.message);
  final String message;
  @override String toString() => message;
}

/// Servicio de ayuda offline; mantiene el mismo contrato y reglas que Desktop.
class HelpService {
  HelpService._(this.database, this.content);
  final AppDatabase database;
  final Map<String, dynamic> content;
  final Set<String> _shownThisSession = <String>{};
  Future<EstadoLicenciaActual>? _licenseStatusFuture;

  void invalidarCacheLicencia() { _licenseStatusFuture = null; }

  static Future<HelpService> load(AppDatabase database) async {
    try {
      final raw = await rootBundle.loadString('assets/help_content_v1.json');
      final schemaRaw = await rootBundle.loadString('assets/help_content_v1.schema.json');
      final decoded = jsonDecode(raw);
      final schemaValue = jsonDecode(schemaRaw);
      if (decoded is! Map<String, dynamic> || schemaValue is! Map<String, dynamic>) {
        throw const FormatException('Los archivos de ayuda deben ser objetos JSON.');
      }
      final schema = JsonSchema.create(schemaValue, schemaVersion: SchemaVersion.draft2020_12);
      final result = schema.validateWithResults(decoded, validateFormats: true);
      if (!result.isValid) {
        throw HelpContentException('El contenido de ayuda integrado no cumple su esquema.');
      }
      final service = HelpService._(database, decoded);
      if (await service._getPreference('help.onboarding_completed', null) == null) {
        await service._setPreference('help.onboarding_completed', false);
      }
      return service;
    } catch (error) {
      if (error is HelpContentException) rethrow;
      throw const HelpContentException('No se pudo cargar la ayuda offline incluida en la aplicación.');
    }
  }

  Map<String, dynamic>? getTooltip(String id) {
    final value = content['tooltips'][id];
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }

  Future<void> marcarTooltipVisto(String id) => _setPreference('help.tooltip_seen.$id', DateTime.now().toUtc().toIso8601String());
  Future<bool> tooltipVisto(String id) async {
    final value = await _getPreference('help.tooltip_seen.$id', null);
    return value is String;
  }
  Future<void> marcarTutorialVisto(String id) => _setPreference('help.tutorial_seen.$id', DateTime.now().toUtc().toIso8601String());

  Map<String, dynamic>? getTutorial(String id) {
    final items = (content['tutoriales'] as List).cast<Map>();
    for (final item in items) {
      if (item['id'] == id) return Map<String, dynamic>.from(item);
    }
    return null;
  }

  List<Map<String, dynamic>> getFaq() => (content['preguntas_frecuentes'] as List)
      .map((e) => Map<String, dynamic>.from(e as Map)).toList(growable: false);

  Map<String, List<Map<String, dynamic>>> search(String query) {
    final needle = query.trim().toLowerCase();
    final tips = (content['tooltips'] as Map).entries.map((e) => Map<String, dynamic>.from(e.value as Map))
        .where((item) => needle.isEmpty || _text(item.values).contains(needle)).toList();
    final tutorials = (content['tutoriales'] as List).map((e) => Map<String, dynamic>.from(e as Map))
        .where((item) => needle.isEmpty || _text(item.values).contains(needle)).toList();
    final faq = getFaq().where((item) => needle.isEmpty || _text(item.values).contains(needle)).toList();
    return {'tooltips': tips, 'tutoriales': tutorials, 'preguntas_frecuentes': faq};
  }

  Future<bool> get onboardingCompletado async => await _getPreference('help.onboarding_completed', false) == true;

  Future<void> marcarOnboardingCompletado() async {
    await _setPreference('help.onboarding_completed', true);
    await _setPreference('help.onboarding_completed_at', DateTime.now().toUtc().toIso8601String());
  }

  Future<void> reiniciarOnboarding() => _setPreference('help.onboarding_completed', false);

  Future<void> guardarPerfilEntidad({required String nombre, required String nit, required String actividad}) =>
      _setPreference('help.entity_profile', {'nombre': nombre.trim(), 'nit': nit.trim(), 'actividad': actividad.trim()});

  Future<Map<String, dynamic>> obtenerPerfilEntidad() async {
    final value = await _getPreference('help.entity_profile', {'nombre': '', 'nit': '', 'actividad': ''});
    return Map<String, dynamic>.from(value as Map);
  }

  Future<void> marcarAvisoDescartado(String id, {bool noMostrarDeNuevo = false}) async {
    await _setPreference('help.notice.$id.dismissed_at', DateTime.now().toUtc().toIso8601String());
    if (noMostrarDeNuevo) await _setPreference('help.notice.$id.disabled', true);
    _shownThisSession.add(id);
  }

  Future<void> reactivarAviso(String id) async {
    await _setPreference('help.notice.$id.disabled', false);
    await _setPreference('help.notice.$id.dismissed_at', null);
  }

  Future<void> registrarRespaldoCreado([DateTime? timestamp]) =>
      _setPreference('help.last_backup_at', (timestamp ?? DateTime.now().toUtc()).toUtc().toIso8601String());

  Future<void> registrarPdfExportado(String fichaId) => _setPreference('help.pdf_exported.$fichaId', true);
  Future<bool> catalogoEjemploCargado(String tipo) async => await _getPreference('help.sample_catalog.$tipo', false) == true;
  Future<void> marcarCatalogoEjemploCargado(String tipo) => _setPreference('help.sample_catalog.$tipo', true);
  Future<String?> fichaDemoId() async {
    final value = await _getPreference('help.demo_ficha_id', null);
    return value as String?;
  }
  Future<void> marcarFichaDemo(String id) => _setPreference('help.demo_ficha_id', id);

  Future<List<Map<String, dynamic>>> evaluarAvisosContextuales({Map<String, dynamic> context = const {}, String? pantalla}) async {
    final values = Map<String, dynamic>.from(context);
    final now = DateTime.now().toUtc();
    values['screen'] = pantalla ?? values['screen'];
    if (!values.containsKey('catalog_items')) {
      values['catalog_items'] = await (database.select(database.catalogos)..where((t) => t.tipo.equals('insumo'))).get().then((v) => v.length);
    }
    values['last_backup_at'] ??= await _getPreference('help.last_backup_at', null);
    if (!values.containsKey('entity_profile_complete')) {
      final profileValue = await _getPreference('help.entity_profile', {'nombre': '', 'nit': '', 'actividad': ''});
      final profile = Map<String, dynamic>.from(profileValue as Map);
      values['entity_profile_complete'] = ['nombre', 'nit', 'actividad'].every((key) => (profile[key] as String? ?? '').trim().isNotEmpty);
    }
    if (!values.containsKey('finished_fichas_unexported')) {
      var pendingPdf = false;
      for (final row in await database.listarFichas()) {
        try {
          final document = jsonDecode(row.documento) as Map<String, dynamic>;
          final ficha = Map<String, dynamic>.from(document['ficha'] as Map);
          if (ficha['estado'] == 'finalizada' && await _getPreference('help.pdf_exported.${ficha['id']}', false) != true) { pendingPdf = true; break; }
        } catch (_) {}
      }
      values['finished_fichas_unexported'] = pendingPdf;
    }
    if (!values.containsKey('license_active') || !values.containsKey('license_days_remaining')) {
      try {
        final state = await (_licenseStatusFuture ??= LicensingService(database).estadoActual());
        values['license_active'] ??= state.estado == EstadoLicencia.valida;
        if (!values.containsKey('license_days_remaining')) {
          values['license_days_remaining'] = state.estado == EstadoLicencia.valida ? state.diasHastaExpiracion : null;
        }
      } catch (_) {
        values['license_active'] ??= false;
      }
    }
    values['clock_suspicious'] ??= (await database.licenciaEstado('clock_rollback_started_at'))?.isNotEmpty ?? false;
    final result = <Map<String, dynamic>>[];
    final notices = Map<String, dynamic>.from(content['avisos_contextuales'] as Map);
    for (final entry in notices.entries) {
      final id = entry.key;
      final notice = Map<String, dynamic>.from(entry.value as Map);
      if (_shownThisSession.contains(id) || await _getPreference('help.notice.$id.disabled', false) == true) continue;
      if (!_condition(id, values, now)) continue;
      final dismissed = await _getPreference('help.notice.$id.dismissed_at', null);
      if (dismissed is String) {
        final elapsed = now.difference(_parseTime(dismissed)).inDays;
        if (elapsed < (notice['repetirTrasDias'] as num).toInt()) continue;
      }
      _shownThisSession.add(id);
      var days = '';
      if (id == 'backup_vencido') {
        final last = values['last_backup_at'];
        days = last is String ? '${now.difference(_parseTime(last)).inDays}' : '8';
      } else if (id == 'licencia_por_expirar') {
        days = '${values['license_days_remaining']}';
      }
      result.add({'id': id, 'mensaje': (notice['mensaje'] as String).replaceAll('{dias}', days),
        'accion': notice['accion'], 'repetirTrasDias': notice['repetirTrasDias']});
    }
    return result;
  }

  bool _condition(String id, Map<String, dynamic> c, DateTime now) {
    switch (id) {
      case 'primera_ficha_sin_catalogo':
        return const {'editor_ficha', 'editor_ficha_nueva', 'ficha_editor'}.contains(c['screen']) && (c['catalog_items'] as num? ?? 0) == 0;
      case 'backup_vencido':
        final last = c['last_backup_at'];
        return last is String ? now.difference(_parseTime(last)).inDays > 7 : c['has_data'] == true;
      case 'licencia_por_expirar':
        final days = c['license_days_remaining'] as num?;
        return c['license_active'] == true && days != null && days >= 0 && days < 7;
      case 'fichas_sin_exportar': return c['finished_fichas_unexported'] == true;
      case 'reloj_sospechoso': return c['clock_suspicious'] == true;
      case 'entidad_sin_configurar': return c['screen'] == 'fichas' && c['entity_profile_complete'] != true;
      default: return false;
    }
  }

  Future<void> _setPreference(String key, dynamic value) async {
    await database.customStatement('INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)',
      [Variable(key), Variable(jsonEncode(value))]);
  }

  Future<dynamic> _getPreference(String key, dynamic fallback) async {
    final row = await database.customSelect('SELECT value_json FROM preferences WHERE key = ?', variables: [Variable(key)]).getSingleOrNull();
    return row == null ? fallback : jsonDecode(row.read<String>('value_json'));
  }

  static DateTime _parseTime(String value) => DateTime.parse(value).toUtc();
  static String _text(Iterable<dynamic> items) => items.map((e) => e is String ? e : e is Map ? _text(e.values) : e is Iterable ? _text(e) : '').join(' ').toLowerCase();
}
