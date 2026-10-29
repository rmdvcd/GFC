import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:json_schema/json_schema.dart';
import 'package:unorm_dart/unorm_dart.dart' as unorm;

import '../data/app_database.dart';
import 'licensing_models.dart';
import 'license_public_key.dart';

// Provision the compile-time public key with the internal keygen tool. The private key is never embedded.
const int _maxLicenseBytes = 128 * 1024;
const Duration _clockGrace = Duration(hours: 24);

String canonicalJsonPayload(Map<String, dynamic> payload) {
  dynamic normalize(dynamic value) {
    if (value == null || value is bool || value is int) return value;
    if (value is String) return unorm.nfc(value);
    if (value is double) throw const FormatException('El payload no admite números decimales.');
    if (value is List) return value.map(normalize).toList(growable: false);
    if (value is Map) {
      final normalized = <String, dynamic>{};
      for (final entry in value.entries) {
        if (entry.key is! String) throw const FormatException('Las claves JSON deben ser texto.');
        final key = unorm.nfc(entry.key as String);
        if (normalized.containsKey(key)) throw const FormatException('Hay claves duplicadas tras normalizar Unicode.');
        normalized[key] = normalize(entry.value);
      }
      final keys = normalized.keys.toList()..sort();
      return <String, dynamic>{for (final key in keys) key: normalized[key]};
    }
    throw FormatException('Tipo JSON no permitido: ${value.runtimeType}.');
  }
  return jsonEncode(normalize(payload));
}

class LicensingService {
  LicensingService(this.database, {String? publicKeyB64, Future<String> Function()? fingerprintProvider, DateTime Function()? nowProvider})
      : _publicKeyB64 = publicKeyB64 ?? licensePublicKeyB64,
        _fingerprintProvider = fingerprintProvider ?? getAndroidFingerprint,
        _nowProvider = nowProvider ?? DateTime.now;

  final AppDatabase database;
  final String _publicKeyB64;
  final Future<String> Function() _fingerprintProvider;
  final DateTime Function() _nowProvider;
  JsonSchema? _schema;

  Future<JsonSchema> _licenseSchema() async {
    if (_schema != null) return _schema!;
    final decoded = jsonDecode(await rootBundle.loadString('assets/licencia_v1.schema.json'));
    if (decoded is! Map<String, dynamic>) throw const FormatException('No se pudo cargar el esquema de licencia v1.');
    return _schema = JsonSchema.create(decoded, schemaVersion: SchemaVersion.draft2020_12);
  }

  Future<ResultadoLicencia> importarLicencia(File file) async {
    try {
      final bytes = await file.openRead(0, _maxLicenseBytes + 1).fold<List<int>>(<int>[], (all, chunk) {
        all.addAll(chunk);
        return all;
      });
      if (bytes.length > _maxLicenseBytes) {
        return const ResultadoLicencia(EstadoLicencia.schemaInvalido, motivoRechazo: 'El archivo de licencia supera el tamaño permitido. Seleccione un archivo .lic válido.');
      }
      final text = utf8.decode(bytes);
      final decoded = jsonDecode(text);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      final schema = await _licenseSchema();
      final validation = schema.validateWithResults(decoded, validateFormats: true);
      if (!validation.isValid) {
        return const ResultadoLicencia(EstadoLicencia.schemaInvalido,
            motivoRechazo: 'El archivo no cumple el esquema de licencia v1. Compruebe que sea un .lic íntegro y vigente.');
      }
      final payload = Map<String, dynamic>.from(decoded['payload'] as Map);
      if (!await _verify(decoded)) {
        return const ResultadoLicencia(EstadoLicencia.firmaInvalida,
            motivoRechazo: 'La firma Ed25519 no es válida o esta aplicación aún no tiene configurada la clave pública. Solicite una licencia emitida por el proveedor.');
      }
      if (payload['deviceFingerprint'] != await _fingerprintProvider()) {
        return ResultadoLicencia(EstadoLicencia.fingerprintNoCoincide, payload: payload,
            motivoRechazo: 'La licencia fue emitida para otro dispositivo. Copie el ID de este equipo y solicite una licencia correspondiente.');
      }
      await database.guardarLicenciaEstado('license_document', jsonEncode(decoded));
      return estadoActual();
    } on FileSystemException {
      return const ResultadoLicencia(EstadoLicencia.schemaInvalido, motivoRechazo: 'No se pudo abrir el archivo. Verifique el almacenamiento y vuelva a intentarlo.');
    } on FormatException {
      return const ResultadoLicencia(EstadoLicencia.schemaInvalido, motivoRechazo: 'El archivo .lic no contiene JSON UTF-8 válido. Seleccione el archivo original sin modificar.');
    } catch (_) {
      return const ResultadoLicencia(EstadoLicencia.schemaInvalido, motivoRechazo: 'No se pudo validar el archivo .lic. Compruebe el formato e inténtelo nuevamente.');
    }
  }

  Future<EstadoLicenciaActual> estadoActual() async {
    final raw = await database.licenciaEstado('license_document');
    if (raw == null || raw.isEmpty) {
      return const EstadoLicenciaActual(EstadoLicencia.noInstalada,
          motivoRechazo: 'No hay una licencia instalada. Puede importar un archivo .lic; sus fichas siguen disponibles.');
    }
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      final schema = await _licenseSchema();
      if (!schema.validateWithResults(decoded, validateFormats: true).isValid) {
        return const EstadoLicenciaActual(EstadoLicencia.schemaInvalido, motivoRechazo: 'La licencia guardada está dañada. Vuelva a importar el archivo .lic.');
      }
      final payload = Map<String, dynamic>.from(decoded['payload'] as Map);
      if (!await _verify(decoded)) return const EstadoLicenciaActual(EstadoLicencia.firmaInvalida,
          motivoRechazo: 'La firma de la licencia guardada no es válida. Solicite asistencia al proveedor.');
      if (payload['deviceFingerprint'] != await _fingerprintProvider()) {
        return EstadoLicenciaActual(EstadoLicencia.fingerprintNoCoincide, payload: payload,
            tipo: payload['tipo'] as String, features: List<String>.from(payload['features'] as List),
            motivoRechazo: 'La licencia no corresponde a este dispositivo. Solicite una licencia para el ID actual.');
      }
      final now = _nowProvider().toUtc();
      final lastSeenText = await database.licenciaEstado('last_seen_ts');
      final rollbackText = await database.licenciaEstado('clock_rollback_started_at');
      String? warning;
      if (lastSeenText != null) {
        final lastSeen = DateTime.tryParse(lastSeenText)?.toUtc() ?? now;
        if (now.isBefore(lastSeen)) {
          var startText = rollbackText;
          if (startText == null || startText.isEmpty) {
            startText = now.toIso8601String();
            await database.guardarLicenciaEstado('clock_rollback_started_at', startText);
          }
          final started = DateTime.tryParse(startText)?.toUtc() ?? now;
          if (now.difference(started) >= _clockGrace) {
            return _status(EstadoLicencia.expirada, payload, now,
                reason: 'Se detectó un retroceso del reloj y se agotó la gracia de 24 horas. Corrija la fecha del dispositivo.');
          }
          warning = 'Se detectó un retroceso del reloj. La licencia está en gracia temporal de 24 horas; corrija la fecha del dispositivo.';
        } else {
          await database.guardarLicenciaEstado('last_seen_ts', now.toIso8601String());
          if (rollbackText != null && rollbackText.isNotEmpty) await database.guardarLicenciaEstado('clock_rollback_started_at', '');
        }
      } else {
        await database.guardarLicenciaEstado('last_seen_ts', now.toIso8601String());
      }
      final expiryText = payload['fechaExpiracion'] as String?;
      if (expiryText != null && !now.isBefore(DateTime.parse(expiryText).toUtc()) && warning == null) {
        return _status(EstadoLicencia.expirada, payload, now,
            reason: 'La licencia expiró. Puede consultar sus fichas y exportar PDF con marca de agua.');
      }
      return _status(EstadoLicencia.valida, payload, now, warning: warning);
    } catch (_) {
      return const EstadoLicenciaActual(EstadoLicencia.schemaInvalido,
          motivoRechazo: 'No se pudo leer la licencia guardada. Vuelva a importar el archivo .lic.');
    }
  }

  Future<bool> consumirFeature(String feature) async {
    final current = await estadoActual();
    final payload = current.payload;
    if (current.estado != EstadoLicencia.valida || payload == null || !(payload['features'] as List).contains(feature)) return false;
    if (feature == 'fichas') {
      return database.consumirCuotaLicencia(payload['licenseId'] as String, feature, payload['maxFichas'] as int);
    }
    return true;
  }

  Future<bool> tieneFeature(String feature) async {
    final current = await estadoActual();
    return current.estado == EstadoLicencia.valida && current.features.contains(feature);
  }

  Future<String> huellaDispositivo() => _fingerprintProvider();

  Future<bool> _verify(Map<String, dynamic> document) async {
    try {
      final publicBytes = base64.decode(_publicKeyB64);
      final signatureBytes = base64.decode(document['signature'] as String);
      if (publicBytes.length != 32 || signatureBytes.length != 64) return false;
      final key = SimplePublicKey(publicBytes, type: KeyPairType.ed25519);
      return await Ed25519().verify(utf8.encode(canonicalJsonPayload(Map<String, dynamic>.from(document['payload'] as Map))),
          signature: Signature(signatureBytes, publicKey: key));
    } catch (_) {
      return false;
    }
  }

  Future<EstadoLicenciaActual> _status(EstadoLicencia state, Map<String, dynamic> payload, DateTime now,
      {String? reason, String? warning}) async {
    final used = await database.usoLicencia(payload['licenseId'] as String, 'fichas');
    final expiration = payload['fechaExpiracion'] as String?;
    final days = expiration == null ? null : DateTime.parse(expiration).toUtc().difference(now).inDays.clamp(0, 1000000).toInt();
    final maxFichas = payload['maxFichas'] as int;
    return EstadoLicenciaActual(state, payload: payload, tipo: payload['tipo'] as String,
        features: List<String>.from(payload['features'] as List), fichasRestantes: (maxFichas - used).clamp(0, maxFichas),
        diasHastaExpiracion: days, motivoRechazo: reason, advertencia: warning);
  }
}

/// Fingerprint específico de Android; los componentes originales no se muestran ni se guardan.
Future<String> getAndroidFingerprint() async {
  if (!Platform.isAndroid) throw UnsupportedError('La huella móvil está definida para Android.');
  final info = await DeviceInfoPlugin().androidInfo;
  final androidId = (info.data['androidId'] ?? info.id ?? '').toString();
  final components = <String>[
    'FichaCostoAndroidV1', androidId, info.id, info.model, info.manufacturer, info.version.release,
  ].map(unorm.nfc).toList();
  final bytes = utf8.encode(components.join('\u001f'));
  return crypto.sha256.convert(bytes).toString();
}
